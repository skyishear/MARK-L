"""Tests for v8.39 ``Agent.ask_with_tools`` — the thin wiring over the tool loop.

The Agent mirrors ``ask``: canonical history is read as prior context and, only
on success, receives the user prompt and the final reply (tool exchanges stay
loop-local, owner decision OD-B). The method writes nothing else (owner
decision O9) and consults the router / registry only through their public
properties, so the v8.15 consultation allowlist is unchanged.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import core.agent as agent_module
from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.memory_context import MemoryRequest
from core.tool_calling import ToolCall
from core.tool_catalog import ToolSpec
from core.tool_interface import ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter
from core.tool_runtime import ToolLoopExhaustedError, ToolLoopResult

PARAMS = {"type": "object", "properties": {"city": {"type": "string"}}}


def spec(name: str = "read", *, side_effects: bool = False, model_invocable: bool = True) -> ToolSpec:
    return ToolSpec(name, f"{name} tool", PARAMS, side_effects=side_effects, model_invocable=model_invocable)


class Tool:
    def __init__(self, name: str, output: str = "ok", error: Exception | None = None) -> None:
        self.name, self.description, self.output, self.error = name, name, output, error
        self.calls: list[ToolRequest] = []

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return ToolResult(self.name, self.output)


class Provider:
    name = "fake"
    supports_tool_calling = True

    def __init__(self, *responses: AIResponse) -> None:
        self.responses = list(responses)
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def build(*tools: Tool, specs: tuple[ToolSpec, ...] = (), provider: Provider | None = None) -> tuple[Agent, Provider]:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    agent = Agent(tool_registry=registry, tool_router=ToolRouter(registry))
    for s in specs:
        agent.tool_catalog.register(s)
    provider = provider or Provider(AIResponse("final answer", "fake"))
    agent.ai_service._registry.register(provider)  # noqa: SLF001 - test double
    return agent, provider


def calling(*calls: ToolCall, text: str = "") -> AIResponse:
    return AIResponse(text, "fake", tool_calls=calls)


# ── surface ─────────────────────────────────────────────────────────────


class TestSurface:
    def test_signature(self) -> None:
        sig = inspect.signature(Agent.ask_with_tools)
        assert list(sig.parameters) == ["self", "provider_name", "prompt", "tools", "confirm", "memory"]
        assert all(sig.parameters[n].kind is inspect.Parameter.KEYWORD_ONLY for n in ("tools", "confirm", "memory"))
        assert not inspect.iscoroutinefunction(Agent.ask_with_tools)

    def test_public_all_is_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16 and "ToolLoopResult" not in agent_module.__all__

    def test_method_consults_neither_private_router_nor_route(self) -> None:
        tree = ast.parse(inspect.getsource(agent_module))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "ask_with_tools")
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert not attrs & {"_tool_router", "_tool_registry", "route", "has"}
        assert {"tool_router", "tool_registry", "tool_catalog"} <= attrs

    def test_method_is_thin(self) -> None:
        tree = ast.parse(inspect.getsource(agent_module))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "ask_with_tools")
        assert node.end_lineno - node.lineno < 50
        called = {c.func.id for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert "run_tool_loop" in called and not [n for n in ast.walk(node) if isinstance(n, (ast.While, ast.For))]


# ── behaviour ───────────────────────────────────────────────────────────


class TestBehaviour:
    def test_default_tools_are_the_model_invocable_catalog_specs(self) -> None:
        agent, provider = build(Tool("read"), specs=(spec("read"), spec("hidden", model_invocable=False)))
        result = agent.ask_with_tools("fake", "hello")
        assert isinstance(result, ToolLoopResult) and result.response.text == "final answer"
        assert [s.name for s in provider.requests[0].tools] == ["read"]

    def test_explicit_tools_override_the_catalog(self) -> None:
        agent, provider = build(Tool("a"), specs=(spec("read"),))
        agent.ask_with_tools("fake", "hello", tools=[spec("a")])
        assert [s.name for s in provider.requests[0].tools] == ["a"]

    def test_no_model_invocable_tools_fails_closed_and_leaves_history_alone(self) -> None:
        agent, provider = build(Tool("read"), specs=(spec("hidden", model_invocable=False),))
        with pytest.raises(ValueError):
            agent.ask_with_tools("fake", "hello")
        assert provider.requests == [] and len(agent.conversation_history) == 0

    def test_full_run_executes_the_tool_and_returns_the_audit(self) -> None:
        tool = Tool("read", "sunny")
        provider = Provider(calling(ToolCall("c1", "read", {"city": "Rome"})), AIResponse("It is sunny", "fake"))
        agent, _ = build(tool, specs=(spec("read"),), provider=provider)
        result = agent.ask_with_tools("fake", "weather?")
        assert result.response.text == "It is sunny" and result.tool_executions == 1
        assert [(o.call_id, o.outcome) for o in result.outcomes] == [("c1", "executed")]
        assert provider.requests[1].tool_exchanges[0].results[0].output == "sunny"
        assert len(tool.calls) == 1 and dict(tool.calls[0].arguments) == {"city": "Rome"}

    def test_prior_history_is_sent_and_only_the_final_turn_is_appended(self) -> None:
        provider = Provider(calling(ToolCall("c1", "read", {})), AIResponse("final", "fake"))
        agent, _ = build(Tool("read"), specs=(spec("read"),), provider=provider)
        agent.conversation_history.append_user("earlier")
        agent.conversation_history.append_assistant("reply")
        agent.ask_with_tools("fake", "now")
        assert [(m.role, m.content) for m in agent.conversation_history.messages()] == [
            ("user", "earlier"), ("assistant", "reply"), ("user", "now"), ("assistant", "final")]
        for request in provider.requests:  # both rounds saw exactly the prior context
            assert [m.content for m in request.history.messages()] == ["earlier", "reply"]

    def test_history_is_untouched_when_the_run_raises(self) -> None:
        provider = Provider(*[calling(ToolCall(f"id{i}", "read", {})) for i in range(5)])
        agent, _ = build(Tool("read"), specs=(spec("read"),), provider=provider)
        with pytest.raises(ToolLoopExhaustedError):
            agent.ask_with_tools("fake", "loop forever")
        assert len(agent.conversation_history) == 0

    def test_confirm_hook_is_passed_through(self) -> None:
        tool = Tool("write")
        asked: list[str] = []

        def approve(call: ToolCall, s: ToolSpec) -> bool:
            asked.append(call.name)
            return True

        provider = Provider(calling(ToolCall("c1", "write", {})), AIResponse("done", "fake"))
        agent, _ = build(tool, specs=(spec("write", side_effects=True),), provider=provider)
        result = agent.ask_with_tools("fake", "go", confirm=approve)
        assert asked == ["write"] and len(tool.calls) == 1 and result.outcomes[0].outcome == "executed"

    def test_side_effecting_call_without_a_hook_is_refused(self) -> None:
        tool = Tool("write")
        provider = Provider(calling(ToolCall("c1", "write", {})), AIResponse("done", "fake"))
        agent, _ = build(tool, specs=(spec("write", side_effects=True),), provider=provider)
        result = agent.ask_with_tools("fake", "go")
        assert tool.calls == [] and result.outcomes[0].outcome == "refused"

    def test_tool_failure_is_sanitized_end_to_end(self) -> None:
        provider = Provider(calling(ToolCall("c1", "read", {})), AIResponse("recovered", "fake"))
        agent, _ = build(Tool("read", error=ToolError("secret path /etc/x")), specs=(spec("read"),), provider=provider)
        result = agent.ask_with_tools("fake", "go")
        assert provider.requests[1].tool_exchanges[0].results[0].output == "error: failed (ToolError)"
        assert "secret" not in repr(provider.requests[1]) and result.outcomes[0].exception_type == "ToolError"

    def test_memory_request_is_forwarded_to_the_system_channel(self) -> None:
        agent, provider = build(Tool("read"), specs=(spec("read"),))
        agent.memory_engine.remember("fact", "color", "blue", source="test")
        agent.ask_with_tools("fake", "color", memory=MemoryRequest(source=agent.memory_engine))
        assert provider.requests[0].system is not None and "blue" in provider.requests[0].system

    def test_unsupported_provider_is_rejected_before_invocation(self) -> None:
        from core.ai_provider import ToolCallingUnsupportedError

        plain = Provider(AIResponse("x", "plain"))
        plain.name, plain.supports_tool_calling = "plain", False
        agent, _ = build(Tool("read"), specs=(spec("read"),))
        agent.ai_service._registry.register(plain)  # noqa: SLF001 - test double
        with pytest.raises(ToolCallingUnsupportedError):
            agent.ask_with_tools("plain", "go")
        assert plain.requests == [] and len(agent.conversation_history) == 0


# ── nothing else is written (O9) ────────────────────────────────────────


class TestWritesNothingElse:
    def test_no_memory_reflection_learning_or_run_records(self) -> None:
        provider = Provider(calling(ToolCall("c1", "read", {})), AIResponse("done", "fake"))
        agent, _ = build(Tool("read"), specs=(spec("read"),), provider=provider)
        before = {k: v for k, v in agent.snapshot().items() if k != "history"}
        agent.ask_with_tools("fake", "go")
        after = {k: v for k, v in agent.snapshot().items() if k != "history"}
        assert after == before  # context, knowledge, learning, reflection, reasoning unchanged
        assert agent.pipeline_run_manager.count() == 0
        assert agent.memory_engine.recall() == []  # nothing was remembered

    def test_is_a_pure_delegation_to_the_ai_service_for_provider_calls(self) -> None:
        provider = Provider(AIResponse("only", "fake"))
        agent, _ = build(Tool("read"), specs=(spec("read"),), provider=provider)
        calls: list[str] = []
        original = agent.ai_service.complete
        agent.ai_service.complete = lambda *a, **k: (calls.append("c"), original(*a, **k))[1]  # type: ignore[method-assign]
        agent.ask_with_tools("fake", "go")
        assert calls == ["c"]


# ── end to end through the real Claude provider (fake SDK client) ───────


class TestEndToEndWithClaude:
    def test_two_round_run_through_claude_mapping(self) -> None:
        from types import SimpleNamespace

        sdk_replies = [
            SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="text", text="Let me check."),
                SimpleNamespace(type="tool_use", id="toolu_1", name="read", input={"city": "Rome"}),
            ]),
            SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="It is sunny.")]),
        ]
        sent: list[dict] = []

        class Messages:
            def create(self, **kwargs: object) -> SimpleNamespace:
                sent.append(kwargs)
                return sdk_replies.pop(0)

        tool = Tool("read", "sunny, 24C")
        agent, _ = build(tool, specs=(spec("read"),))
        agent.ai_service.router.select("claude")._client = SimpleNamespace(messages=Messages())  # noqa: SLF001
        result = agent.ask_with_tools("claude", "weather in Rome?")
        assert result.response.text == "It is sunny." and (result.rounds, result.tool_executions) == (2, 1)
        assert "tools" in sent[0] and "tools" in sent[1]
        assert sent[0]["messages"] == [{"role": "user", "content": "weather in Rome?"}]
        assert sent[1]["messages"] == [
            {"role": "user", "content": "weather in Rome?"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {"city": "Rome"}},
            ]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "sunny, 24C"}]},
        ]
        assert [(m.role, m.content) for m in agent.conversation_history.messages()] == [
            ("user", "weather in Rome?"), ("assistant", "It is sunny.")]

    def test_a_cut_off_tool_call_is_never_executed(self) -> None:
        from types import SimpleNamespace

        from core.ai_provider import ToolCallNormalizationError

        class Messages:
            def create(self, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(stop_reason="max_tokens", content=[
                    SimpleNamespace(type="tool_use", id="toolu_1", name="read", input={"city": "Ro"})])

        tool = Tool("read")
        agent, _ = build(tool, specs=(spec("read"),))
        agent.ai_service.router.select("claude")._client = SimpleNamespace(messages=Messages())  # noqa: SLF001
        with pytest.raises(ToolCallNormalizationError):
            agent.ask_with_tools("claude", "weather?")
        assert tool.calls == [] and len(agent.conversation_history) == 0
