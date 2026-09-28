"""Tests for v8.35 token budgeting (``core.token_counter`` and the
``ContextManager`` input/context token budget).

Locked owner decisions: pluggable provider-neutral ``TokenCounter``
(``count(text) -> int``) with a deterministic local tokenizer (no network,
no provider imports, not a character approximation); ``max_tokens = 8192``
input/context budget, enabled by default, covering ``history + prompt``; no
output reservation (provider output caps untouched); a third independent
limit beside 50 messages / 20,000 characters with the v8.34 trimming rules
(oldest complete pairs first, no orphan leading assistant, never mutate,
never truncate, raise ``ContextValidationError`` when the newest required
context cannot fit). No provider / model identity in ``ContextManager``.
"""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.token_counter as counter_module
from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.context_manager import ContextManager, ContextValidationError
from core.conversation_history import ConversationHistory, Message
from core.token_counter import LocalTokenCounter, TokenCounter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
COUNTER_PATH = os.path.join(CORE_DIR, "token_counter.py")
T = LocalTokenCounter()


def words(n: int, prefix: str = "w") -> str:
    """Text of exactly ``n`` tokens: one distinguishing prefix word plus
    single-letter words (~2 characters per token, so the token budget — not
    the 20,000-character limit — is the binding constraint)."""
    return prefix + " a" * (n - 1)


def history(*turns: tuple[str, str]) -> ConversationHistory:
    h = ConversationHistory()
    h.extend(Message(role, content) for role, content in turns)  # type: ignore[arg-type]
    return h


def token_pairs(n: int, tokens_each: int) -> ConversationHistory:
    turns = []
    for i in range(n):
        turns.append(("user", words(tokens_each, f"u{i}_")))
        turns.append(("assistant", words(tokens_each, f"a{i}_")))
    return history(*turns)


def tokens(msgs: tuple[Message, ...]) -> int:
    return sum(T.count(m.content) for m in msgs)


# ── the local tokenizer ─────────────────────────────────────────────────


class TestLocalTokenCounter:
    @pytest.mark.parametrize("text, expected", [
        ("", 0), ("   \n\t", 0), ("hello", 1), ("hello world", 2), ("Hello, world!", 4),
        ("abc123 45.6", 4), ("naïve café", 2), ("snake_case_word", 1), ("a+b=c", 5),
        ("x" * 10_000, 1), ("🙂🙂", 2), ("don't", 3),
    ])
    def test_counts(self, text: str, expected: int) -> None:
        assert T.count(text) == expected

    def test_is_not_a_character_ratio(self) -> None:
        assert T.count("a" * 4000) == 1 and T.count("a " * 4000) == 4000

    def test_deterministic_and_stateless(self) -> None:
        text = words(500) + "!?,."
        assert {LocalTokenCounter().count(text) for _ in range(3)} == {504}
        assert LocalTokenCounter.__slots__ == ()

    def test_rejects_non_str(self) -> None:
        with pytest.raises(TypeError):
            T.count(None)  # type: ignore[arg-type]

    def test_satisfies_the_protocol(self) -> None:
        counter: TokenCounter = LocalTokenCounter()
        assert counter.count("a b") == 2

    def test_stdlib_only_no_network_no_provider(self) -> None:
        tree = ast.parse(open(COUNTER_PATH, encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert mods == {"__future__", "re", "typing"}
        assert counter_module.__all__ == ["LocalTokenCounter", "TokenCounter"]

    def test_only_context_manager_imports_it(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name not in ("token_counter.py", "context_manager.py"):
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "token_counter" not in f.read(), name


# ── ContextManager configuration ────────────────────────────────────────


class TestConfiguration:
    def test_defaults(self) -> None:
        c = ContextManager()
        assert (c.max_messages, c.max_chars, c.max_tokens) == (50, 20_000, 8_192)
        assert isinstance(c.token_counter, LocalTokenCounter)

    def test_default_through_aiservice_and_agent(self) -> None:
        for cm in (AIService().context_manager, Agent().ai_service.context_manager):
            assert cm.max_tokens == 8_192 and isinstance(cm.token_counter, LocalTokenCounter)

    def test_custom_counter_is_used(self) -> None:
        class CharCounter:
            def count(self, text: str) -> int:
                return len(text)

        c = ContextManager(max_tokens=5, token_counter=CharCounter())
        h = history(("user", "abc"), ("assistant", "de"), ("user", "fg"), ("assistant", "hi"))
        assert [m.content for m in c.prepare(h)] == ["fg", "hi"]

    @pytest.mark.parametrize("kw", [{"max_tokens": 0}, {"max_tokens": -5}, {"max_tokens": 1.0},
                                    {"max_tokens": True}, {"token_counter": object()}])
    def test_invalid(self, kw: dict) -> None:
        with pytest.raises((ValueError, TypeError)):
            ContextManager(**kw)

    def test_bad_counter_result_rejected(self) -> None:
        class Negative:
            def count(self, text: str) -> int:
                return -1

        with pytest.raises(TypeError):
            ContextManager(token_counter=Negative()).prepare(history(("user", "x")))

    def test_no_provider_or_model_identity(self) -> None:
        params = set(inspect.signature(ContextManager.__init__).parameters)
        assert params == {"self", "max_messages", "max_chars", "max_tokens", "token_counter"}
        assert list(inspect.signature(ContextManager.prepare_request).parameters) == ["self", "history", "prompt"]


# ── token budget on the history ─────────────────────────────────────────


class TestHistoryBudget:
    def test_within_budget_unchanged(self) -> None:
        h = token_pairs(4, 1000)  # 8,000 tokens, 8 messages
        assert ContextManager().prepare(h) == h.messages()

    def test_exactly_8192_tokens_unchanged(self) -> None:
        h = history(("user", words(4096)), ("assistant", words(4096)))
        assert tokens(h.messages()) == 8_192
        assert ContextManager().prepare(h) == h.messages()

    def test_over_budget_trims_oldest_complete_pairs(self) -> None:
        h = token_pairs(5, 1000)  # 10,000 tokens
        out = ContextManager().prepare(h)
        assert out == h.messages()[-8:] and tokens(out) == 8_000
        assert out[0].role == "user" and len(h) == 10  # canonical untouched

    def test_oversized_newest_message_by_tokens(self) -> None:
        big = "a " * 8_193  # 8,193 tokens, 16,386 characters (< 20,000)
        h = history(("user", "hi"), ("assistant", "yo"), ("user", big))
        with pytest.raises(ContextValidationError, match="8193 tokens"):
            ContextManager().prepare(h)

    def test_newest_pair_not_fitting_tokens_raises(self) -> None:
        h = history(("user", words(5000)), ("assistant", words(5000)))
        with pytest.raises(ContextValidationError):
            ContextManager().prepare(h)

    def test_orphan_assistant_never_leads_after_token_trim(self) -> None:
        h = history(("user", words(3000)), ("assistant", words(3000)), ("assistant", words(3000)),
                    ("user", words(10)), ("assistant", words(10)))
        out = ContextManager().prepare(h)
        assert [m.content for m in out] == [words(10), words(10)]


# ── history + prompt ────────────────────────────────────────────────────


class TestPromptBudget:
    def test_prompt_participates(self) -> None:
        h = token_pairs(4, 1000)  # 8,000 tokens: fits alone
        assert ContextManager().prepare(h) == h.messages()
        out = ContextManager().prepare_request(h, words(300))  # 8,300 total
        assert out == h.messages()[-6:] and tokens(out) + 300 <= 8_192

    def test_exact_total_budget_retained(self) -> None:
        h = history(("user", words(4000)), ("assistant", words(4000)))
        out = ContextManager().prepare_request(h, words(192))
        assert out == h.messages()  # 8,192 total: no output reservation

    def test_prompt_alone_over_budget_raises(self) -> None:
        for h in (None, ConversationHistory(), history(("user", "hi"))):
            with pytest.raises(ContextValidationError, match="prompt"):
                ContextManager().prepare_request(h, words(8_193))

    def test_prompt_exactly_budget_with_empty_history(self) -> None:
        assert ContextManager().prepare_request(None, words(8_192)) == ()

    def test_newest_unit_plus_prompt_cannot_fit_raises(self) -> None:
        h = history(("user", "old"), ("assistant", "old"), ("user", words(8_000)))
        with pytest.raises(ContextValidationError):
            ContextManager().prepare_request(h, words(500))

    def test_prompt_is_never_truncated_or_returned(self) -> None:
        h = token_pairs(2, 10)
        out = ContextManager().prepare_request(h, "question")
        assert all(m.content != "question" for m in out)

    def test_prompt_type_checked(self) -> None:
        with pytest.raises(TypeError):
            ContextManager().prepare_request(None, None)  # type: ignore[arg-type]

    def test_subclass_prepare_override_is_honoured(self) -> None:
        class UsersOnly(ContextManager):
            def prepare(self, history):  # type: ignore[override]
                return tuple(m for m in history.messages() if m.role == "user")

        h = history(("user", words(10)), ("assistant", words(10)), ("user", words(10)))
        out = UsersOnly().prepare_request(h, "q")
        assert [m.role for m in out] == ["user", "user"]


# ── three independent limits ────────────────────────────────────────────


class TestIndependentLimits:
    def test_message_limit_binding(self) -> None:
        h = token_pairs(30, 1)  # 60 messages, 60 tokens, few chars
        assert ContextManager().prepare(h) == h.messages()[-50:]

    def test_char_limit_binding(self) -> None:
        h = history(*[(r, "x" * 5_000) for _ in range(3) for r in ("user", "assistant")])  # 30k chars, 6 tokens
        out = ContextManager().prepare(h)
        assert out == h.messages()[-4:] and sum(len(m.content) for m in out) == 20_000

    def test_token_limit_binding(self) -> None:
        h = token_pairs(3, 2000)  # 6 messages, 12,000 tokens
        cm = ContextManager(max_chars=10_000_000)  # isolate the token limit
        out = cm.prepare(h)
        assert out == h.messages()[-4:] and tokens(out) == 8_000

    def test_all_three_respected_simultaneously(self) -> None:
        h = token_pairs(40, 150)  # 80 messages, 12,000 tokens
        out = ContextManager().prepare_request(h, words(100))
        assert len(out) <= 50 and sum(len(m.content) for m in out) <= 20_000
        assert tokens(out) + 100 <= 8_192 and out == h.messages()[-len(out):]

    def test_deterministic_and_non_mutating(self) -> None:
        h = token_pairs(40, 150)
        before = h.messages()
        c = ContextManager()
        assert c.prepare_request(h, "q") == c.prepare_request(h, "q") == ContextManager().prepare_request(h, "q")
        assert h.messages() == before


# ── AIService / Agent integration ───────────────────────────────────────


class Capture:
    name = "cap"

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse(text="ok", provider_name=self.name)


def service() -> tuple[AIService, Capture]:
    s = AIService()
    cap = Capture()
    s._registry.register(cap)  # noqa: SLF001 - test double
    return s, cap


class TestIntegration:
    def test_single_turn_request_sent_unchanged(self) -> None:
        s, cap = service()
        req = AIRequest(prompt="hello")
        s.complete("cap", req)
        assert cap.requests[0] is req and req.history is None

    def test_single_turn_prompt_over_budget_raises_before_provider(self) -> None:
        s, cap = service()
        with pytest.raises(ContextValidationError):
            s.complete("cap", AIRequest(prompt=words(8_193)))
        assert cap.requests == []

    def test_history_plus_prompt_bounded(self) -> None:
        s, cap = service()
        h = token_pairs(4, 1000)
        s.complete("cap", AIRequest(prompt=words(300)), history=h)
        sent = cap.requests[0]
        assert sent.prompt == words(300) and sent.history.messages() == h.messages()[-6:]
        assert len(h) == 8

    def test_prepare_request_called_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s, _ = service()
        calls: list[tuple] = []
        orig = s.context_manager.prepare_request
        monkeypatch.setattr(s.context_manager, "prepare_request",
                            lambda h, p: calls.append((h, p)) or orig(h, p))
        s.complete("cap", AIRequest(prompt="q"), history=token_pairs(1, 1))
        assert len(calls) == 1 and calls[0][1] == "q"

    def test_agent_ask_keeps_canonical_history(self) -> None:
        a = Agent()
        cap = Capture()
        a.ai_service._registry.register(cap)  # noqa: SLF001
        for i in range(6):
            a.ask("cap", words(1500, f"q{i}_"))
        assert len(a.conversation_history) == 12
        last = cap.requests[-1]
        assert tokens(last.history.messages()) + T.count(last.prompt) <= 8_192

    def test_provider_output_caps_untouched(self) -> None:
        src = open(os.path.join(CORE_DIR, "claude_provider.py"), encoding="utf-8").read()
        assert "max_tokens=1024" in src
