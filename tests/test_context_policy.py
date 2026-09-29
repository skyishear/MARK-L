"""Tests for v8.34 context policy and history trimming
(``core.context_manager.ContextManager.prepare``).

Locked owner policy: max_messages=50, max_chars=20_000 (``Message.content``
characters only; the request prompt is not counted), enabled by default;
within limits the history is returned unchanged; otherwise the oldest
complete user/assistant pairs (or single non-pair messages) are dropped,
never leaving an orphan assistant message first, never reordering or
rewriting; an oversized newest message raises ``ContextValidationError``;
the canonical ``ConversationHistory`` is never mutated. No token logic.
"""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.context_manager as cm_module
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.agent import Agent
from core.context_manager import ContextManager, ContextValidationError
from core.conversation_history import ConversationHistory, Message

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
MODULE_PATH = os.path.join(ROOT, "core", "context_manager.py")


def history(*turns: tuple[str, str]) -> ConversationHistory:
    h = ConversationHistory()
    h.extend(Message(role, content) for role, content in turns)  # type: ignore[arg-type]
    return h


def pairs(n: int, size: int = 1, prefix: str = "") -> ConversationHistory:
    turns: list[tuple[str, str]] = []
    for i in range(n):
        # Word-character padding: each message is a single token under the
        # v8.35 local tokenizer, so these fixtures exercise the v8.34
        # message / character limits with the token budget satisfied.
        turns.append(("user", f"{prefix}u{i}".ljust(size, "x")))
        turns.append(("assistant", f"{prefix}a{i}".ljust(size, "x")))
    return history(*turns)


def chars(msgs: tuple[Message, ...]) -> int:
    return sum(len(m.content) for m in msgs)


# ── defaults & configuration ────────────────────────────────────────────


class TestPolicy:
    def test_defaults_are_50_and_20000(self) -> None:
        c = ContextManager()
        assert (c.max_messages, c.max_chars) == (50, 20_000)

    def test_aiservice_and_agent_use_the_default_policy(self) -> None:
        cm = AIService().context_manager
        assert (cm.max_messages, cm.max_chars) == (50, 20_000)
        cm = Agent().ai_service.context_manager
        assert (cm.max_messages, cm.max_chars) == (50, 20_000)

    def test_explicit_configuration(self) -> None:
        c = ContextManager(max_messages=4, max_chars=100)
        out = c.prepare(pairs(5))
        assert [m.content for m in out] == ["u3", "a3", "u4", "a4"]
        assert c.prepare(pairs(5)) == out

    @pytest.mark.parametrize("kw", [{"max_messages": 0}, {"max_chars": 0}, {"max_messages": -1},
                                    {"max_chars": 1.5}, {"max_messages": True}, {"max_chars": "20"}])
    def test_invalid_configuration(self, kw: dict) -> None:
        with pytest.raises(ValueError):
            ContextManager(**kw)

    def test_keyword_only_and_zero_arg_compatible(self) -> None:
        params = inspect.signature(ContextManager.__init__).parameters
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for n, p in params.items() if n != "self")
        ContextManager()


# ── within limits ───────────────────────────────────────────────────────


class TestWithinLimits:
    def test_empty_and_none(self) -> None:
        assert ContextManager().prepare(ConversationHistory()) == ()
        assert ContextManager().prepare(None) == ()  # type: ignore[arg-type]

    def test_single_message(self) -> None:
        h = history(("user", "hi"))
        assert ContextManager().prepare(h) == h.messages()

    def test_small_history_unchanged(self) -> None:
        h = pairs(10, size=100)
        assert ContextManager().prepare(h) == h.messages()

    def test_exactly_50_messages_unchanged(self) -> None:
        h = pairs(25)
        assert len(h) == 50 and ContextManager().prepare(h) == h.messages()

    def test_exactly_20000_chars_unchanged(self) -> None:
        h = pairs(10, size=1000)
        assert chars(h.messages()) == 20_000
        assert ContextManager().prepare(h) == h.messages()

    def test_within_limits_is_identity_even_if_starting_with_assistant(self) -> None:
        # Nothing is trimmed, so nothing is dropped (backward compatible).
        h = history(("assistant", "hello"), ("user", "hi"))
        assert ContextManager().prepare(h) == h.messages()


# ── trimming ────────────────────────────────────────────────────────────


class TestTrimming:
    def test_51_messages_trims_oldest_complete_pair(self) -> None:
        h = history(*[(r, c) for i in range(25) for r, c in (("user", f"u{i}"), ("assistant", f"a{i}"))],
                    ("user", "latest"))
        assert len(h) == 51
        out = ContextManager().prepare(h)
        assert len(out) == 49 and out[0].content == "u1" and out[-1].content == "latest"
        assert out == h.messages()[2:]

    def test_many_messages_keeps_newest_50(self) -> None:
        h = pairs(40)
        out = ContextManager().prepare(h)
        assert out == h.messages()[-50:] and out[0].role == "user"

    def test_over_20000_chars_trims_oldest_pairs(self) -> None:
        h = pairs(11, size=1000)  # 22,000 chars, 22 messages
        out = ContextManager().prepare(h)
        assert chars(out) == 20_000 and out == h.messages()[2:]

    def test_char_budget_uneven_pairs(self) -> None:
        h = history(("user", "x" * 15_000), ("assistant", "y" * 3_000),
                    ("user", "z" * 1_000), ("assistant", "w" * 1_500))
        out = ContextManager().prepare(h)
        assert [m.content[0] for m in out] == ["z", "w"] and chars(out) == 2_500

    def test_both_limits_simultaneously(self) -> None:
        h = pairs(30, size=500)  # 60 messages, 30,000 chars
        out = ContextManager().prepare(h)
        assert len(out) <= 50 and chars(out) <= 20_000
        assert out == h.messages()[-40:]  # char budget is the binding constraint: 40 x 500

    def test_order_newest_no_duplicates_no_rewrite(self) -> None:
        h = pairs(40, size=10)
        out = ContextManager().prepare(h)
        src = h.messages()
        assert out[-1] is src[-1]
        idx = [src.index(m) for m in out]
        assert idx == sorted(idx) and len(set(idx)) == len(idx)
        assert all(m is src[i] for m, i in zip(out, idx))  # same objects, content untouched

    def test_canonical_history_never_mutated(self) -> None:
        h = pairs(40, size=600)
        before = h.messages()
        ContextManager().prepare(h)
        ContextManager().prepare(h)
        assert h.messages() == before and len(h) == 80

    def test_deterministic(self) -> None:
        h = pairs(40, size=333)
        c = ContextManager()
        assert c.prepare(h) == c.prepare(h) == ContextManager().prepare(h)

    def test_never_begins_with_orphan_assistant_after_trimming(self) -> None:
        h = history(("user", "u0"), ("assistant", "a0"), ("assistant", "orphan"),
                    ("user", "u1"), ("assistant", "a1"))
        out = ContextManager(max_messages=4, max_chars=1000).prepare(h)
        assert [m.content for m in out] == ["u1", "a1"]

    def test_incomplete_latest_user_turn_is_kept_as_its_own_unit(self) -> None:
        h = history(*[(r, "x" * 5_000) for _ in range(2) for r in ("user", "assistant")],
                    ("user", "latest question"))
        out = ContextManager().prepare(h)
        assert [m.role for m in out] == ["user", "assistant", "user"]
        assert out[-1].content == "latest question" and chars(out) == 10_015

    def test_incomplete_latest_user_turn_alone_when_nothing_else_fits(self) -> None:
        h = history(("user", "x" * 12_000), ("assistant", "y" * 7_000), ("user", "z" * 5_000))
        out = ContextManager().prepare(h)
        assert [m.content[0] for m in out] == ["z"]


# ── oversized newest context ────────────────────────────────────────────


class TestOversized:
    def test_oversized_newest_message_raises(self) -> None:
        h = history(("user", "a"), ("assistant", "b"), ("user", "x" * 20_001))
        with pytest.raises(ContextValidationError) as info:
            ContextManager().prepare(h)
        assert "20001 characters" in str(info.value) and "x" * 10 not in str(info.value)

    def test_oversized_single_message_history_raises(self) -> None:
        with pytest.raises(ContextValidationError):
            ContextManager().prepare(history(("user", "x" * 20_001)))

    def test_exactly_max_single_message_is_kept(self) -> None:
        h = history(("user", "old"), ("assistant", "old"), ("user", "x" * 20_000))
        assert ContextManager().prepare(h) == (h.messages()[-1],)

    def test_newest_pair_that_cannot_fit_raises(self) -> None:
        h = history(("user", "x" * 12_000), ("assistant", "y" * 12_000))
        with pytest.raises(ContextValidationError):
            ContextManager().prepare(h)

    def test_newest_orphan_assistant_raises_with_accurate_reason(self) -> None:
        h = history(("user", "u"), ("assistant", "a"), ("assistant", "orphan"))
        with pytest.raises(ContextValidationError, match="orphan assistant"):
            ContextManager(max_messages=2).prepare(h)

    def test_error_is_value_error_and_history_untouched(self) -> None:
        h = history(("user", "x" * 30_000))
        with pytest.raises(ValueError):
            ContextManager().prepare(h)
        assert len(h) == 1 and len(h.messages()[0].content) == 30_000


# ── AIService integration ───────────────────────────────────────────────


class Capture:
    name = "cap"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse(text="ok", provider_name=self.name)


def service_with_capture() -> tuple[AIService, Capture]:
    s = AIService()
    cap = Capture()
    s._registry.register(cap)  # noqa: SLF001 - test double registration
    return s, cap


class TestIntegration:
    def test_aiservice_sends_bounded_view_and_prompt_not_counted(self) -> None:
        # The prompt is outside the v8.34 *character* budget (v8.35 counts its
        # tokens: one word -> 1 token, well within 8,192).
        s, cap = service_with_capture()
        h = pairs(10, size=1000)  # exactly 20,000 chars of history
        s.complete("cap", AIRequest(prompt="p" * 50_000), history=h)
        sent = cap.requests[0]
        assert sent.prompt == "p" * 50_000  # untouched, not counted
        assert sent.history.messages() == h.messages()

    def test_aiservice_trims_long_history(self) -> None:
        s, cap = service_with_capture()
        h = pairs(40)
        s.complete("cap", AIRequest(prompt="q"), history=h)
        assert cap.requests[0].history.messages() == h.messages()[-50:]
        assert len(h) == 80  # canonical untouched

    def test_agent_ask_keeps_full_canonical_history(self) -> None:
        a = Agent()
        cap = Capture()
        a.ai_service._registry.register(cap)  # noqa: SLF001
        for i in range(30):
            a.ask("cap", f"q{i}")
        assert len(a.conversation_history) == 60  # never trimmed
        assert len(cap.requests[-1].history.messages()) == 50  # bounded view sent


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_imports_only_conversation_history(self) -> None:
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        # v8.35: + the provider-neutral token counter leaf (and typing).
        # v8.36: + the provider-neutral memory-context leaf (and dataclasses).
        assert mods == {"__future__", "dataclasses", "typing", "core.conversation_history",
                        "core.token_counter", "core.memory_context"}
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import)]
        assert cm_module.__all__ == ["ContextManager", "ContextValidationError", "PreparedContext"]  # v8.36

    def test_no_token_or_provider_logic(self) -> None:
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                  | {getattr(n, "name", "") for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))})
        lowered = {i.lower() for i in idents}
        # v8.35: token *budgeting* identifiers are allowed; tokenizer logic
        # (regexes, encoders) and provider / model names are not.
        for token in ("tokenizer", "tiktoken", "encode", "findall", "compile", "openai", "anthropic", "gemini",
                      "ollama", "summar", "embed", "model", "provider"):
            assert not any(token in i for i in lowered), token
        assert "re" not in {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}

    def test_prepare_never_mutates(self) -> None:
        tree = ast.parse(inspect.getsource(ContextManager))
        attrs = {c.func.attr for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert not attrs & {"append_user", "append_assistant", "extend", "clear", "pop", "remove"}

    def test_no_module_state(self) -> None:
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        assigns = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        assert assigns == ["__all__"]
