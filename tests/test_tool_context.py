"""Tests for v8.39 tool-context accounting (owner decision OD-A).

``core.tool_context.render_tool_context`` renders the offered tool declarations
and the run's tool exchanges deterministically; ``ContextManager.prepare_context``
counts that text as required, never-truncated context inside the existing
token budget (``tool_context=`` keyword); ``AIService`` wires the two together.
"""

from __future__ import annotations

import ast
import os

import pytest

import core.tool_context as tc_module
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.context_manager import ContextManager, ContextValidationError
from core.conversation_history import ConversationHistory, Message
from core.memory_context import MemoryRequest
from core.memory_engine import MemoryEngine
from core.tool_calling import ToolCall, ToolCallResult, ToolExchange
from core.tool_catalog import ToolSpec
from core.tool_context import render_tool_context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}


def spec(name: str = "weather", description: str = "Get weather", **kw: object) -> ToolSpec:
    kw.setdefault("model_invocable", True)
    return ToolSpec(name, description, PARAMS, **kw)  # type: ignore[arg-type]


def exchange(call_id: str = "c1", output: str = "sunny", text: str = "") -> ToolExchange:
    return ToolExchange(
        calls=(ToolCall(call_id, "weather", {"city": "Rome"}),),
        results=(ToolCallResult(call_id, "weather", output),),
        text=text,
    )


class WordCounter:
    """One token per whitespace-separated word (test-controlled counting)."""

    def count(self, text: str) -> int:
        return len(text.split())


# ── rendering ───────────────────────────────────────────────────────────


class TestRender:
    def test_empty_inputs_render_empty_text(self) -> None:
        assert render_tool_context((), ()) == ""

    def test_deterministic(self) -> None:
        a = render_tool_context((spec(),), (exchange(),))
        b = render_tool_context((spec(),), (exchange(),))
        assert a == b and isinstance(a, str) and a

    def test_key_order_does_not_change_the_text(self) -> None:
        one = ToolSpec("t", "d", {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}},
                       model_invocable=True)
        two = ToolSpec("t", "d", {"properties": {"b": {"type": "string"}, "a": {"type": "string"}}, "type": "object"},
                       model_invocable=True)
        assert render_tool_context((one,), ()) == render_tool_context((two,), ())

    def test_only_declaration_data_that_is_sent_is_rendered(self) -> None:
        text = render_tool_context((spec(idempotent=True, side_effects=False),), ())
        assert '"name":"weather"' in text and "Get weather" in text and '"city"' in text
        for forbidden in ("idempotent", "side_effects", "model_invocable"):
            assert forbidden not in text

    def test_exchange_data_is_rendered(self) -> None:
        text = render_tool_context((spec(),), (exchange("call-9", "windy", text="Looking up"),))
        for needle in ("call-9", "windy", "Looking up", "Rome"):
            assert needle in text

    def test_order_of_tools_and_exchanges_is_kept(self) -> None:
        text = render_tool_context((spec("zeta"), spec("alpha")), (exchange("one"), exchange("two")))
        assert text.index("zeta") < text.index("alpha") and text.index('"one"') < text.index('"two"')

    def test_unicode_is_not_escaped(self) -> None:
        assert "日本" in render_tool_context((spec(description="日本"),), ())

    def test_more_content_renders_more_text(self) -> None:
        assert len(render_tool_context((spec(),), (exchange(),))) > len(render_tool_context((spec(),), ()))

    def test_leaf_is_stdlib_only_and_stateless(self) -> None:
        with open(tc_module.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert mods == {"__future__", "json", "collections.abc"}
        assigns = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets]
        assert assigns == ["__all__"] and tc_module.__all__ == ["render_tool_context"]


# ── ContextManager keyword ──────────────────────────────────────────────


def history(*texts: str) -> ConversationHistory:
    h = ConversationHistory()
    for i, text in enumerate(texts):
        (h.append_user if i % 2 == 0 else h.append_assistant)(text)
    return h


class TestContextManagerToolContext:
    def test_default_none_and_empty_are_identical_to_before(self) -> None:
        cm = ContextManager(token_counter=WordCounter())
        h = history("a b", "c d")
        base = cm.prepare_context(h, "p q", system="s")
        assert cm.prepare_context(h, "p q", system="s", tool_context=None) == base
        assert cm.prepare_context(h, "p q", system="s", tool_context="") == base

    def test_counts_as_required_context_and_trims_history_to_make_room(self) -> None:
        cm = ContextManager(max_tokens=10, token_counter=WordCounter())
        h = history("one two", "three four", "five six", "seven eight")  # two pairs, 4 tokens each
        assert len(cm.prepare_context(h, "p", tool_context=None).messages) == 4
        trimmed = cm.prepare_context(h, "p", tool_context="t1 t2 t3 t4")
        assert [m.content for m in trimmed.messages] == ["five six", "seven eight"]  # oldest pair dropped

    def test_overflow_raises_and_names_the_tool_context(self) -> None:
        cm = ContextManager(max_tokens=5, token_counter=WordCounter())
        with pytest.raises(ContextValidationError) as info:
            cm.prepare_context(history(), "p", system="s", tool_context="a b c d e f")
        assert "tool context (6 tokens)" in str(info.value)

    def test_history_that_cannot_fit_with_the_tool_context_raises(self) -> None:
        cm = ContextManager(max_tokens=8, token_counter=WordCounter())
        with pytest.raises(ContextValidationError):
            cm.prepare_context(history("one two three four five"), "p", tool_context="a b c d")

    def test_memory_is_dropped_before_history_is_trimmed(self) -> None:
        engine = MemoryEngine()
        engine.remember("fact", "k1", "alpha value one")
        engine.remember("fact", "k2", "alpha value two")
        cm = ContextManager(max_tokens=40, token_counter=WordCounter())
        h = history("hello there", "hi")
        free = cm.prepare_context(h, "alpha", memory=MemoryRequest(source=engine))
        squeezed = cm.prepare_context(h, "alpha", memory=MemoryRequest(source=engine),
                                      tool_context=" ".join(["w"] * (40 - 4 - 1 - 2)))
        assert free.memory_count >= 1
        assert squeezed.memory_count < free.memory_count and len(squeezed.messages) == 2

    def test_type_validation(self) -> None:
        with pytest.raises(TypeError):
            ContextManager().prepare_context(history(), "p", tool_context=5)  # type: ignore[arg-type]

    def test_canonical_history_is_never_mutated(self) -> None:
        cm = ContextManager(max_tokens=10, token_counter=WordCounter())
        h = history("one two", "three four", "five six", "seven eight")
        before = h.messages()
        cm.prepare_context(h, "p", tool_context="t1 t2 t3 t4")
        assert h.messages() == before

    def test_context_manager_module_contract_is_intact(self) -> None:
        import core.context_manager as cm_module

        assert cm_module.__all__ == ["ContextManager", "ContextValidationError", "PreparedContext"]
        with open(cm_module.__file__, encoding="utf-8") as f:
            mods = {n.module for n in ast.walk(ast.parse(f.read())) if isinstance(n, ast.ImportFrom)}
        assert "core.tool_context" not in mods and "core.tool_catalog" not in mods  # text only, no tool types


# ── AIService accounting ────────────────────────────────────────────────


class Capture:
    name = "capable"
    supports_tool_calling = True

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse("ok", self.name)


def service(max_tokens: int, counter: object = None) -> tuple[AIService, Capture]:
    cm = ContextManager(max_tokens=max_tokens, **({"token_counter": counter} if counter else {}))
    s = AIService(cm)
    cap = Capture()
    s._registry.register(cap)  # noqa: SLF001 - test double
    return s, cap


class TestAIServiceAccounting:
    def test_declarations_alone_can_exceed_the_budget(self) -> None:
        tools_tokens = len(render_tool_context((spec(),), ()).split())
        s, cap = service(tools_tokens, WordCounter())  # the 1-token prompt tips it over the budget
        with pytest.raises(ContextValidationError):
            s.complete("capable", AIRequest("hello", tools=[spec()]))
        assert cap.requests == []  # the provider is never invoked over budget

    def test_exchanges_grow_the_accounted_context(self) -> None:
        text = render_tool_context((spec(),), ())
        budget = len(text.split()) + 2
        s, cap = service(budget, WordCounter())
        s.complete("capable", AIRequest("hello", tools=[spec()]))  # fits
        with pytest.raises(ContextValidationError):
            s.complete("capable", AIRequest("hello", tools=[spec()], tool_exchanges=[exchange(output="x " * 50)]))
        assert len(cap.requests) == 1

    def test_history_is_trimmed_to_make_room_for_tools(self) -> None:
        text = render_tool_context((spec(),), ())
        tools_tokens = len(text.split())
        s, cap = service(tools_tokens + 1 + 4, WordCounter())
        h = history("one two", "three four", "five six", "seven eight")
        s.complete("capable", AIRequest("p", tools=[spec()]), history=h)
        assert [m.content for m in cap.requests[0].history.messages()] == ["five six", "seven eight"]

    def test_default_budget_passes_a_normal_tool_run(self) -> None:
        s, cap = service(8192)
        s.complete("capable", AIRequest("p", tools=[spec()], tool_exchanges=[exchange()]))
        assert len(cap.requests) == 1

    def test_no_tools_uses_the_unchanged_request_budget_path(self) -> None:
        s, cap = service(5, WordCounter())
        s.complete("capable", AIRequest("a b c"))  # 3 tokens: unchanged v8.35 behaviour
        with pytest.raises(ContextValidationError):
            s.complete("capable", AIRequest("a b c d e f"))
        assert len(cap.requests) == 1
