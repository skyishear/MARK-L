"""Tests for v8.36 system channel and opt-in memory injection.

Locked contract: request-level ``AIRequest.system`` (no system / developer
``Message`` role), supplied through ``AIService`` configuration and mapped
only inside provider modules; memory injection is opt-in, sourced only from
``core.memory_engine.MemoryEngine`` via ``recall(query=<prompt>)``, at most
10 memories in recall order; **O3: ``sensitive=True`` memories never reach
provider context**; order SYSTEM -> MEMORY -> HISTORY -> PROMPT; the
8,192-token input budget covers system + memory + history + prompt, memory
is the removable part; canonical history is never mutated; with no system
and no memory, v8.35 behaviour is unchanged.
"""

from __future__ import annotations

import ast
import os
import typing

import pytest

from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.claude_provider import ClaudeProvider
from core.context_manager import ContextManager, ContextValidationError, PreparedContext
from core.conversation_history import ConversationHistory, Message, Role
from core.gemini_provider import GeminiProvider
from core.memory_context import MemoryRequest, render_memories, select_memories
from core.memory_engine import MemoryEngine
from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider
from core.token_counter import LocalTokenCounter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
T = LocalTokenCounter()
SECRET = "PASSWORD-hunter2-SECRET"


def words(n: int, prefix: str = "w") -> str:
    return prefix + " a" * (n - 1)


def history(*turns: tuple[str, str]) -> ConversationHistory:
    h = ConversationHistory()
    h.extend(Message(role, content) for role, content in turns)  # type: ignore[arg-type]
    return h


class Capture:
    name = "cap"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse(text="ok", provider_name=self.name)


def service(**kw) -> tuple[AIService, Capture]:
    s = AIService(**kw)
    cap = Capture()
    s._registry.register(cap)  # noqa: SLF001 - test double
    return s, cap


def agent(**kw) -> tuple[Agent, Capture]:
    a = Agent(**kw)
    cap = Capture()
    a.ai_service._registry.register(cap)  # noqa: SLF001
    return a, cap


# ── provider-specific fake SDK clients ──────────────────────────────────


class _Rec:
    def __init__(self, result: object) -> None:
        self.calls: list[dict] = []
        self.result = result

    def __call__(self, **kw):
        self.calls.append(kw)
        return self.result


def openai_client():
    msg = type("M", (), {"content": "ok"})()
    rec = _Rec(type("R", (), {"choices": [type("C", (), {"message": msg})()]})())
    return type("Cl", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": rec})()})()})(), rec


def claude_client():
    rec = _Rec(type("R", (), {"content": [type("B", (), {"text": "ok"})()]})())
    return type("Cl", (), {"messages": type("Ms", (), {"create": rec})()})(), rec


def gemini_client():
    rec = _Rec(type("R", (), {"text": "ok"})())
    return type("Cl", (), {"models": type("Md", (), {"generate_content": rec})()})(), rec


def ollama_client():
    rec = _Rec({"response": "ok"})
    return type("Cl", (), {"generate": rec})(), rec


# ── system channel ──────────────────────────────────────────────────────


class TestSystemChannel:
    def test_airequest_system_defaults_to_none(self) -> None:
        r = AIRequest(prompt="p")
        assert r.system is None and r.history is None
        assert AIRequest("p", None, "S").system == "S"

    def test_no_system_or_developer_role(self) -> None:
        assert typing.get_args(Role) == ("user", "assistant")

    @pytest.mark.parametrize("with_history", [False, True])
    def test_system_none_payloads_unchanged(self, with_history: bool) -> None:
        h = history(("user", "u"), ("assistant", "a")) if with_history else None
        req = AIRequest(prompt="p", history=h)
        c, rec = openai_client()
        OpenAIProvider(client=c).complete(req)
        assert rec.calls[-1]["messages"][0]["role"] != "system"
        c, rec = claude_client()
        ClaudeProvider(client=c).complete(req)
        assert "system" not in rec.calls[-1] and set(rec.calls[-1]) == {"model", "max_tokens", "messages"}
        c, rec = gemini_client()
        GeminiProvider(client=c).complete(req)
        assert "config" not in rec.calls[-1]
        c, rec = ollama_client()
        OllamaProvider(client=c).complete(req)
        assert "system" not in rec.calls[-1]

    @pytest.mark.parametrize("with_history", [False, True])
    def test_system_mapped_to_native_field(self, with_history: bool) -> None:
        h = history(("user", "u"), ("assistant", "a")) if with_history else None
        req = AIRequest(prompt="p", history=h, system="Be brief.")
        c, rec = openai_client()
        OpenAIProvider(client=c).complete(req)
        msgs = rec.calls[-1]["messages"]
        assert msgs[0] == {"role": "system", "content": "Be brief."} and msgs[-1] == {"role": "user", "content": "p"}
        c, rec = claude_client()
        ClaudeProvider(client=c).complete(req)
        assert rec.calls[-1]["system"] == "Be brief." and rec.calls[-1]["max_tokens"] == 1024
        assert all(m["role"] != "system" for m in rec.calls[-1]["messages"])
        c, rec = gemini_client()
        GeminiProvider(client=c).complete(req)
        assert rec.calls[-1]["config"] == {"system_instruction": "Be brief."}
        c, rec = ollama_client()
        OllamaProvider(client=c).complete(req)
        assert rec.calls[-1]["system"] == "Be brief."

    def test_aiservice_configured_system(self) -> None:
        s, cap = service(system="You are EDITH.")
        assert s.system == "You are EDITH."
        s.complete("cap", AIRequest(prompt="hi"))
        assert cap.requests[0].system == "You are EDITH." and cap.requests[0].history is None

    def test_default_aiservice_has_no_system(self) -> None:
        s, cap = service()
        req = AIRequest(prompt="hi")
        s.complete("cap", req)
        assert s.system is None and cap.requests[0] is req

    def test_request_system_takes_precedence(self) -> None:
        s, cap = service(system="configured")
        s.complete("cap", AIRequest(prompt="hi", system="explicit"))
        assert cap.requests[0].system == "explicit"

    def test_invalid_system_config(self) -> None:
        with pytest.raises(TypeError):
            AIService(system=42)  # type: ignore[arg-type]

    def test_system_never_enters_conversation_history(self) -> None:
        a, cap = agent(ai_service=AIService(system="S"))
        a.ai_service._registry.register(cap)  # noqa: SLF001
        a.ask("cap", "q1")
        a.ask("cap", "q2")
        assert [m.role for m in a.conversation_history] == ["user", "assistant"] * 2
        assert all(m.content != "S" for m in a.conversation_history)
        assert cap.requests[-1].system == "S"


# ── memory selection / rendering (leaf) ─────────────────────────────────


def engine_with(*entries: tuple[str, str, str, bool]) -> MemoryEngine:
    e = MemoryEngine()
    for category, key, value, sensitive in entries:
        e.remember(category, key, value, sensitive=sensitive)
    return e


class TestMemorySelection:
    def test_prompt_is_the_recall_query(self) -> None:
        e = engine_with(("prefs", "color", "likes wifi blue", False), ("prefs", "food", "pizza", False))
        out = select_memories(MemoryRequest(e), "wifi")
        assert [m["key"] for m in out] == ["color"]

    def test_max_10_in_recall_order(self) -> None:
        e = engine_with(*[("notes", f"k{i:02d}", f"wifi {i}", False) for i in range(15)])
        out = select_memories(MemoryRequest(e), "wifi")
        assert [m["key"] for m in out] == [f"k{i:02d}" for i in range(10)]

    def test_sensitive_excluded_and_does_not_consume_the_limit(self) -> None:
        entries = [("notes", f"s{i}", f"wifi {SECRET}", True) for i in range(5)]
        entries += [("notes", f"k{i:02d}", f"wifi {i}", False) for i in range(12)]
        e = engine_with(*entries)
        out = select_memories(MemoryRequest(e), "wifi")
        assert [m["key"] for m in out] == [f"k{i:02d}" for i in range(10)]
        assert all(m["sensitive"] is False for m in out)

    def test_fail_closed_on_missing_or_non_bool_flag(self) -> None:
        class Source:
            def count(self) -> int:
                return 3

            def recall(self, **kw):
                return [{"category": "c", "key": "a", "value": "v"},
                        {"category": "c", "key": "b", "value": "v", "sensitive": 0},
                        {"category": "c", "key": "c", "value": "v", "sensitive": False}]

        assert [m["key"] for m in select_memories(MemoryRequest(Source()), "v")] == ["c"]

    def test_optional_filters_use_recall_semantics(self) -> None:
        e = MemoryEngine()
        e.remember("prefs", "a", "wifi", project="home")
        e.remember("notes", "b", "wifi", project="home")
        e.remember("prefs", "c", "wifi", project="work", memory_type="session")
        pick = lambda **kw: [m["key"] for m in select_memories(MemoryRequest(e, **kw), "wifi")]  # noqa: E731
        assert pick() == ["a", "b", "c"]
        assert pick(category="prefs") == ["a", "c"]
        assert pick(project="home") == ["a", "b"]
        assert pick(memory_type="session") == ["c"]

    def test_empty_engine(self) -> None:
        assert select_memories(MemoryRequest(MemoryEngine()), "x") == ()

    def test_request_validation(self) -> None:
        with pytest.raises(TypeError):
            MemoryRequest(object())  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            MemoryRequest(MemoryEngine(), category=3)  # type: ignore[arg-type]

    def test_rendering_deterministic(self) -> None:
        entries = ({"category": "prefs", "key": "color", "value": "blue"},
                   {"category": "notes", "key": "wifi", "value": "reset router"})
        assert render_memories(entries) == ("Relevant memories:\n- [prefs] color: blue\n"
                                            "- [notes] wifi: reset router")
        assert render_memories(entries) == render_memories(entries) and render_memories(()) is None

    def test_ttl_semantics_untouched(self) -> None:
        e = engine_with()
        e.remember("notes", "old", "wifi", ttl_days=0)
        assert [m["key"] for m in select_memories(MemoryRequest(e), "wifi")] == ["old"]


# ── opt-in injection through AIService / Agent ─────────────────────────


class TestInjection:
    def test_default_ask_and_reason_never_inject(self) -> None:
        a, cap = agent()
        a.memory_engine.remember("prefs", "wifi", "wifi password is on the router")
        a.ask("cap", "wifi")
        a.reason("cap", "wifi")
        assert [r.system for r in cap.requests] == [None, None]

    def test_opt_in_injects_non_sensitive_memories_only(self) -> None:
        a, cap = agent()
        a.memory_engine.remember("prefs", "router", "wifi router is in the hall")
        a.memory_engine.remember("secrets", "wifi_pw", f"wifi {SECRET}", sensitive=True)
        a.ask("cap", "wifi", memory=MemoryRequest(a.memory_engine))
        sent = cap.requests[0]
        assert sent.system == "Relevant memories:\n- [prefs] router: wifi router is in the hall"
        assert SECRET not in repr(cap.requests) and "wifi_pw" not in repr(cap.requests)

    def test_sensitive_never_reaches_any_provider_payload(self) -> None:
        e = engine_with(("secrets", "pw", f"wifi {SECRET}", True))
        s, cap = service(system="S")
        s.complete("cap", AIRequest(prompt="wifi"), history=history(("user", "wifi?"), ("assistant", "ok")),
                   memory=MemoryRequest(e))
        sent = cap.requests[0]
        assert sent.system == "S" and SECRET not in repr(sent)
        c, rec = claude_client()
        ClaudeProvider(client=c).complete(sent)
        assert SECRET not in repr(rec.calls)

    def test_order_system_memory_history_prompt(self) -> None:
        e = engine_with(("prefs", "k", "wifi fact", False))
        s, cap = service(system="SYS")
        h = history(("user", "old q"), ("assistant", "old a"))
        s.complete("cap", AIRequest(prompt="wifi"), history=h, memory=MemoryRequest(e))
        sent = cap.requests[0]
        assert sent.system == "SYS\n\nRelevant memories:\n- [prefs] k: wifi fact"
        c, rec = openai_client()
        OpenAIProvider(client=c).complete(sent)
        roles = [m["role"] for m in rec.calls[0]["messages"]]
        contents = [m["content"] for m in rec.calls[0]["messages"]]
        assert roles == ["system", "user", "assistant", "user"] and contents[-1] == "wifi"

    def test_canonical_history_unchanged(self) -> None:
        a, cap = agent()
        a.memory_engine.remember("prefs", "k", "wifi fact")
        for _ in range(3):
            a.ask("cap", "wifi", memory=MemoryRequest(a.memory_engine))
        assert [m.content for m in a.conversation_history] == ["wifi", "ok"] * 3
        assert len(a.memory_engine.recall()) == 1  # nothing written back

    def test_no_system_no_memory_uses_the_v8_35_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s, _ = service()
        calls: list[str] = []
        orig = s.context_manager.prepare_request
        monkeypatch.setattr(s.context_manager, "prepare_request",
                            lambda h, p: calls.append("prepare_request") or orig(h, p))
        monkeypatch.setattr(s.context_manager, "prepare_context",
                            lambda *x, **k: calls.append("prepare_context"))
        s.complete("cap", AIRequest(prompt="q"), history=history(("user", "u"), ("assistant", "a")))
        assert calls == ["prepare_request"]

    def test_memory_without_matches_sends_no_system(self) -> None:
        e = engine_with(("prefs", "k", "nothing relevant", False))
        s, cap = service()
        s.complete("cap", AIRequest(prompt="wifi"), memory=MemoryRequest(e))
        assert cap.requests[0].system is None

    def test_invalid_memory_argument(self) -> None:
        s, _ = service()
        with pytest.raises(TypeError):
            s.complete("cap", AIRequest(prompt="q"), memory="not a request")


# ── budget ──────────────────────────────────────────────────────────────


class TestBudget:
    def test_budget_counts_system_memory_history_prompt(self) -> None:
        e = engine_with(*[("notes", f"k{i}", f"wifi {words(400, 'm')}", False) for i in range(10)])
        h = history(("user", words(2000)), ("assistant", words(2000)))  # 4,000 tokens
        # remaining after system (1,000) + history + prompt: ~3,191 < 10 x ~402
        ctx = ContextManager().prepare_context(h, "wifi", system=words(1000, "s"), memory=MemoryRequest(e))
        total = T.count(ctx.system) + sum(T.count(m.content) for m in ctx.messages) + T.count("wifi")
        assert total <= 8_192 and ctx.messages == h.messages()
        assert 0 < ctx.memory_count < 10  # memory is what gave way

    def test_memories_dropped_from_the_end_deterministically(self) -> None:
        e = engine_with(*[("notes", f"k{i}", f"wifi {words(400, 'm')}", False) for i in range(10)])
        h = history(("user", words(3000)), ("assistant", words(3000)))
        cm = ContextManager()
        first = cm.prepare_context(h, "wifi", memory=MemoryRequest(e))
        again = cm.prepare_context(h, "wifi", memory=MemoryRequest(e))
        assert first == again
        kept = [line.split("]")[1].split(":")[0].strip() for line in first.system.splitlines()[1:]]
        assert kept == [f"k{i}" for i in range(first.memory_count)]

    def test_all_memories_dropped_keeps_system_verbatim(self) -> None:
        e = engine_with(("notes", "k", f"wifi {words(500, 'm')}", False))
        system = words(4000, "s")
        h = history(("user", words(2000)), ("assistant", words(2000)))
        ctx = ContextManager().prepare_context(h, "wifi", system=system, memory=MemoryRequest(e))
        assert ctx.system == system and ctx.memory_count == 0 and ctx.messages == h.messages()

    def test_memory_never_trims_history(self) -> None:
        e = engine_with(("notes", "k", f"wifi {words(3000, 'm')}", False))
        h = history(("user", words(4000)), ("assistant", words(4000)))
        ctx = ContextManager().prepare_context(h, "wifi", memory=MemoryRequest(e))
        assert ctx.messages == h.messages() and ctx.memory_count == 0

    def test_system_counts_like_the_prompt_for_history(self) -> None:
        # v8.35 semantics with system as required context: oldest pairs go.
        h = history(("user", words(2000)), ("assistant", words(2000)),
                    ("user", words(2000)), ("assistant", words(2000)))
        ctx = ContextManager().prepare_context(h, "q", system=words(500, "s"))
        assert ctx.messages == h.messages()[2:] and ctx.system == words(500, "s")

    def test_system_plus_prompt_over_budget_raises(self) -> None:
        with pytest.raises(ContextValidationError, match="system"):
            ContextManager().prepare_context(None, words(200), system=words(8_000))

    def test_newest_history_unit_plus_system_prompt_cannot_fit_raises(self) -> None:
        h = history(("user", "old"), ("assistant", "old"), ("user", words(6000)))
        with pytest.raises(ContextValidationError):
            ContextManager().prepare_context(h, words(100), system=words(3000))

    def test_prompt_and_system_never_truncated(self) -> None:
        s, cap = service(system=words(3000, "s"))
        # 2,000 + 1 + 1,500 + 1 history + 3,000 system + 2,000 prompt = 8,502 > 8,192
        h = history(("user", words(2000)), ("assistant", "a"), ("user", words(1500)), ("assistant", "b"))
        s.complete("cap", AIRequest(prompt=words(2000, "p")), history=h)
        sent = cap.requests[0]
        assert sent.prompt == words(2000, "p") and sent.system == words(3000, "s")
        assert sent.history.messages() == h.messages()[2:]  # oldest pair gave way, never system/prompt

    def test_required_context_that_cannot_fit_raises_before_sending(self) -> None:
        # newest pair (~5,001) + system (3,000) + prompt (2,000) > 8,192: raise,
        # never truncate system / prompt, never silently empty the history.
        s, cap = service(system=words(3000, "s"))
        with pytest.raises(ContextValidationError):
            s.complete("cap", AIRequest(prompt=words(2000, "p")),
                       history=history(("user", words(5000)), ("assistant", "a")))
        assert cap.requests == []

    def test_v8_34_char_and_message_limits_apply_to_history_only(self) -> None:
        big_system = "x" * 30_000  # one token, 30,000 characters
        h = history(*[(r, "y" * 100) for _ in range(30) for r in ("user", "assistant")])
        ctx = ContextManager().prepare_context(h, "q", system=big_system)
        assert ctx.system == big_system and len(ctx.messages) == 50

    def test_prepared_context_shape(self) -> None:
        ctx = ContextManager().prepare_context(None, "q")
        assert ctx == PreparedContext(messages=(), system=None, memory_count=0)


# ── architecture ────────────────────────────────────────────────────────


def _imports(path: str) -> set[str]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    return {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


class TestArchitecture:
    def test_memory_context_is_a_stdlib_leaf(self) -> None:
        assert _imports(os.path.join(CORE_DIR, "memory_context.py")) == {"__future__", "dataclasses", "typing"}

    def test_aiservice_stays_free_of_memory_imports(self) -> None:
        mods = _imports(os.path.join(CORE_DIR, "ai_service.py"))
        assert not [m for m in mods if m.startswith("core.memory")]

    def test_providers_import_neither_context_nor_memory(self) -> None:
        for name in ("openai_provider.py", "claude_provider.py", "gemini_provider.py", "ollama_provider.py"):
            mods = _imports(os.path.join(CORE_DIR, name))
            assert not [m for m in mods if m.startswith(("core.context_manager", "core.memory"))], name

    def test_legacy_memory_never_used(self) -> None:
        for name in ("memory_context.py", "context_manager.py", "ai_service.py"):
            mods = _imports(os.path.join(CORE_DIR, name))
            assert not [m for m in mods if m == "memory" or m.startswith(("memory.", "sqlite3"))], name
            assert "core.memory_engine" not in mods, name  # the engine is injected, never imported

    def test_provider_output_cap_unchanged(self) -> None:
        assert '"max_tokens": 1024' in open(os.path.join(CORE_DIR, "claude_provider.py"), encoding="utf-8").read()
