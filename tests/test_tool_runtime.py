"""Tests for v8.39 ``core.tool_runtime`` — the tool runtime loop.

Covers the locked owner decisions: OD-C (5 model rounds / 10 tool executions,
either limit raises ``ToolLoopExhaustedError``; not the v8.33 retry bound),
O1 (side-effecting calls need an injected hook returning exactly ``True``),
O2 (sanitized model-facing strings, loop continues), O9 (per-call outcome
records, no writes) and the C8 audit counting rules R1-R5.
"""

from __future__ import annotations

import ast
import dataclasses
import os

import pytest

import core.tool_runtime as rt
from core.ai_provider import AIRequest, AIResponse
from core.tool_calling import ToolCall
from core.tool_catalog import ToolSpec
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult, TransientToolError
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter
from core.tool_runtime import (
    MAX_MODEL_ROUNDS,
    MAX_TOOL_EXECUTIONS,
    ToolCallOutcome,
    ToolLoopExhaustedError,
    ToolLoopResult,
    run_tool_loop,
)

PARAMS = {"type": "object", "properties": {"city": {"type": "string"}}}
SECRET = "SECRET-tool-message-text"


def spec(name: str = "read", *, side_effects: bool = False) -> ToolSpec:
    return ToolSpec(name, f"{name} tool", PARAMS, side_effects=side_effects, model_invocable=True)


def call(call_id: str, name: str = "read", **arguments: object) -> ToolCall:
    return ToolCall(call_id, name, arguments or {"city": "Rome"})


def respond(*calls: ToolCall, text: str = "") -> AIResponse:
    return AIResponse(text=text, provider_name="fake", tool_calls=calls)


def final(text: str = "done") -> AIResponse:
    return AIResponse(text=text, provider_name="fake")


class Script:
    """A scripted ``complete``: returns the next response and records requests."""

    def __init__(self, *responses: AIResponse, repeat: AIResponse | None = None) -> None:
        self.responses = list(responses)
        self.repeat = repeat
        self.requests: list[AIRequest] = []

    def __call__(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        assert self.repeat is not None, "script exhausted"
        return self.repeat


class Tool:
    def __init__(self, name: str, behavior: object = None) -> None:
        self.name = name
        self.description = name
        self.behavior = behavior
        self.calls: list[ToolRequest] = []

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        if isinstance(self.behavior, BaseException):
            raise self.behavior
        if self.behavior is not None and not isinstance(self.behavior, str):
            return self.behavior  # type: ignore[return-value]
        return ToolResult(self.name, self.behavior if isinstance(self.behavior, str) else f"{self.name}-ok")


def stack(*tools: Tool) -> tuple[ToolRouter, ToolRegistry]:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolRouter(registry), registry


def run(script: Script, tools: list[ToolSpec], *registered: Tool, confirm: object = None, prompt: str = "go") -> ToolLoopResult:
    router, registry = stack(*registered)
    return run_tool_loop(script, prompt=prompt, tools=tools, router=router, registry=registry, confirm=confirm)  # type: ignore[arg-type]


# ── basic runs ──────────────────────────────────────────────────────────


class TestBasicRuns:
    def test_no_tool_call_is_a_single_round(self) -> None:
        script = Script(final("hi"))
        result = run(script, [spec()], Tool("read"))
        assert result.response.text == "hi" and (result.rounds, result.tool_executions) == (1, 0)
        assert result.outcomes == () and len(script.requests) == 1
        assert script.requests[0].tools == (spec(),) and script.requests[0].tool_exchanges == ()
        assert script.requests[0].prompt == "go"

    def test_one_round_executes_then_follows_up_with_the_exchange(self) -> None:
        tool = Tool("read", "sunny")
        script = Script(respond(call("c1", city="Rome"), text="Checking"), final("It is sunny"))
        result = run(script, [spec()], tool)
        assert result.response.text == "It is sunny" and (result.rounds, result.tool_executions) == (2, 1)
        assert [r.tool_name for r in tool.calls] == ["read"] and dict(tool.calls[0].arguments) == {"city": "Rome"}
        (exchange,) = script.requests[1].tool_exchanges
        assert exchange.text == "Checking" and exchange.calls[0].call_id == "c1"
        assert exchange.results[0].output == "sunny" and exchange.results[0].call_id == "c1"
        assert result.outcomes == (ToolCallOutcome("c1", "read", "executed"),)

    def test_calls_run_in_order_and_results_keep_it(self) -> None:
        a, b = Tool("a"), Tool("b")
        script = Script(respond(call("1", "a"), call("2", "b"), call("3", "a")), final())
        result = run(script, [spec("a"), spec("b")], a, b)
        (exchange,) = script.requests[1].tool_exchanges
        assert [r.call_id for r in exchange.results] == ["1", "2", "3"]
        assert [o.call_id for o in result.outcomes] == ["1", "2", "3"] and result.tool_executions == 3
        assert len(a.calls) == 2 and len(b.calls) == 1

    def test_every_round_resends_the_same_tools_and_prompt_with_growing_exchanges(self) -> None:
        script = Script(respond(call("1")), respond(call("2")), final())
        run(script, [spec()], Tool("read"))
        assert [len(r.tool_exchanges) for r in script.requests] == [0, 1, 2]
        assert all(r.prompt == "go" and r.tools == (spec(),) for r in script.requests)

    def test_arguments_reach_the_tool_unchanged(self) -> None:
        tool = Tool("read")
        run(Script(respond(ToolCall("1", "read", {"city": "X", "tags": ["p", "q"]})), final()), [spec()], tool)
        assert dict(tool.calls[0].arguments)["tags"] == ("p", "q")


# ── gates: offered / registered (baseline fail-closed rules) ────────────


class TestGates:
    def test_unoffered_tool_is_refused_and_never_invoked(self) -> None:
        other = Tool("other")
        script = Script(respond(call("1", "other")), final())
        result = run(script, [spec("read")], Tool("read"), other)
        assert other.calls == []
        assert script.requests[1].tool_exchanges[0].results[0].output == "error: refused (not_offered)"
        assert result.outcomes == (ToolCallOutcome("1", "other", "refused"),) and result.tool_executions == 0

    def test_offered_but_unregistered_tool_is_refused(self) -> None:
        script = Script(respond(call("1")), final())
        result = run(script, [spec("read")])  # nothing registered
        assert script.requests[1].tool_exchanges[0].results[0].output == "error: refused (not_registered)"
        assert result.outcomes[0].outcome == "refused"

    def test_non_model_invocable_spec_cannot_be_offered(self) -> None:
        hidden = ToolSpec("read", "d", PARAMS)  # model_invocable defaults to False
        with pytest.raises(ValueError):
            run(Script(final()), [hidden], Tool("read"))

    def test_empty_tools_rejected(self) -> None:
        with pytest.raises(ValueError):
            run(Script(final()), [], Tool("read"))

    def test_duplicate_tool_names_rejected(self) -> None:
        with pytest.raises(ValueError):
            run(Script(final()), [spec("read"), spec("read")], Tool("read"))


# ── O1: side-effecting confirmation ─────────────────────────────────────


class TestConfirmation:
    def test_read_only_tool_runs_without_any_hook(self) -> None:
        tool = Tool("read")
        run(Script(respond(call("1")), final()), [spec("read", side_effects=False)], tool)
        assert len(tool.calls) == 1

    def test_hook_is_not_asked_for_read_only_tools(self) -> None:
        asked: list[object] = []
        run(Script(respond(call("1")), final()), [spec("read")], Tool("read"),
            confirm=lambda c, s: asked.append(c) or True)
        assert asked == []

    def test_side_effecting_tool_without_hook_is_refused(self) -> None:
        tool = Tool("write")
        script = Script(respond(call("1", "write")), final())
        result = run(script, [spec("write", side_effects=True)], tool)
        assert tool.calls == [] and result.tool_executions == 0
        assert script.requests[1].tool_exchanges[0].results[0].output == "error: refused (confirmation_denied)"
        assert result.outcomes[0].outcome == "refused"

    def test_hook_returning_true_allows_and_receives_call_and_spec(self) -> None:
        seen: list[tuple[ToolCall, ToolSpec]] = []
        tool, s = Tool("write"), spec("write", side_effects=True)

        def hook(c: ToolCall, sp: ToolSpec) -> bool:
            seen.append((c, sp))
            return True

        run(Script(respond(call("1", "write")), final()), [s], tool, confirm=hook)
        assert len(tool.calls) == 1 and seen == [(call("1", "write"), s)]

    @pytest.mark.parametrize("answer", [False, None, 1, "yes", [True], object()])
    def test_only_an_exact_true_approves(self, answer: object) -> None:
        tool = Tool("write")
        result = run(Script(respond(call("1", "write")), final()), [spec("write", side_effects=True)], tool,
                     confirm=lambda c, s: answer)
        assert tool.calls == [] and result.outcomes[0].outcome == "refused"

    def test_hook_exceptions_propagate_unchanged_and_the_tool_never_runs(self) -> None:
        boom = RuntimeError("hook failed")
        tool = Tool("write")

        def hook(c: ToolCall, s: ToolSpec) -> bool:
            raise boom

        with pytest.raises(RuntimeError) as info:
            run(Script(respond(call("1", "write")), final()), [spec("write", side_effects=True)], tool, confirm=hook)
        assert info.value is boom and tool.calls == []

    def test_hook_is_not_asked_for_unoffered_or_unregistered_calls(self) -> None:
        asked: list[object] = []
        hook = lambda c, s: asked.append(c) or True  # noqa: E731
        run(Script(respond(call("1", "ghost"), call("2", "write")), final()), [spec("write", side_effects=True)],
            confirm=hook)  # "ghost" not offered; "write" not registered
        assert asked == []

    def test_hook_must_be_callable_or_none(self) -> None:
        with pytest.raises(TypeError):
            run(Script(final()), [spec()], Tool("read"), confirm="yes")


# ── O2: failures and sanitized strings ──────────────────────────────────


class TestFailures:
    def test_tool_failure_becomes_a_sanitized_string_and_the_loop_continues(self) -> None:
        tool = Tool("read", ToolError(SECRET))
        script = Script(respond(call("1")), final("recovered"))
        result = run(script, [spec()], tool)
        (exchange,) = script.requests[1].tool_exchanges
        assert exchange.results[0].output == "error: failed (ToolError)"
        assert result.response.text == "recovered"
        assert result.outcomes == (ToolCallOutcome("1", "read", "failed", "ToolError"),)
        assert result.tool_executions == 1  # a failing call counts as an execution

    def test_nothing_but_the_type_name_leaves_the_loop(self) -> None:
        script = Script(respond(call("1", city="PrivateCity")), final())
        result = run(script, [spec()], Tool("read", ValueError(SECRET)))
        for artifact in (repr(script.requests[1].tool_exchanges[0].results), repr(result.outcomes)):
            assert SECRET not in artifact and "PrivateCity" not in artifact.replace("Rome", "")
        assert "ValueError" in repr(result.outcomes)

    def test_non_string_tool_output_is_a_failure(self) -> None:
        script = Script(respond(call("1")), final())
        result = run(script, [spec()], Tool("read", ToolResult("read", 123)))  # type: ignore[arg-type]
        assert script.requests[1].tool_exchanges[0].results[0].output == "error: failed (TypeError)"
        assert result.outcomes[0] == ToolCallOutcome("1", "read", "failed", "TypeError")

    def test_malformed_tool_result_object_is_a_failure(self) -> None:
        script = Script(respond(call("1")), final())
        result = run(script, [spec()], Tool("read", SimpleResult()))
        assert result.outcomes[0].outcome == "failed" and result.outcomes[0].exception_type == "AttributeError"

    def test_non_exception_base_exceptions_propagate(self) -> None:
        with pytest.raises(KeyboardInterrupt):
            run(Script(respond(call("1")), final()), [spec()], Tool("read", KeyboardInterrupt()))

    def test_provider_exceptions_propagate_unchanged(self) -> None:
        boom = RuntimeError("provider down")

        def complete(request: AIRequest) -> AIResponse:
            raise boom

        router, registry = stack(Tool("read"))
        with pytest.raises(RuntimeError) as info:
            run_tool_loop(complete, prompt="p", tools=[spec()], router=router, registry=registry)
        assert info.value is boom

    def test_failure_text_for_a_transient_error_is_the_same_shape(self) -> None:
        tool = Tool("read", TransientToolError(SECRET))
        script = Script(respond(call("1")), final())
        run(script, [spec()], tool)
        assert script.requests[1].tool_exchanges[0].results[0].output == "error: failed (TransientToolError)"


class SimpleResult:
    """A result object without ``output`` (a broken tool)."""


# ── no retry: the router is called at most once per call ────────────────


class TestNoRetry:
    def test_transient_errors_are_not_retried(self) -> None:
        tool = Tool("read", TransientToolError("flaky"))
        run(Script(respond(call("1")), final()), [spec()], tool)
        assert len(tool.calls) == 1

    def test_the_v8_33_retry_helper_is_unused_by_the_leaf(self) -> None:
        tree = ast.parse(open(rt.__file__, encoding="utf-8").read())
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "route" in called and not any("retry" in c or "classify" in c for c in called)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not any("retry" in n.lower() or "transient" in n.lower() or "classif" in n.lower() for n in names)


# ── OD-C limits: model rounds ───────────────────────────────────────────


class TestModelRoundLimit:
    def test_locked_values(self) -> None:
        assert (MAX_MODEL_ROUNDS, MAX_TOOL_EXECUTIONS) == (5, 10)

    def test_a_final_answer_on_round_five_is_allowed(self) -> None:
        script = Script(*[respond(call(str(i))) for i in range(4)], final("fifth"))
        result = run(script, [spec()], Tool("read"))
        assert result.rounds == 5 and result.response.text == "fifth" and len(script.requests) == 5
        assert result.tool_executions == 4

    def test_tool_calls_on_round_five_raise_and_are_not_executed(self) -> None:
        tool = Tool("read")
        calls_made: list[int] = []

        def complete(request: AIRequest) -> AIResponse:
            calls_made.append(1)
            return respond(call(f"id{len(calls_made)}"))

        router, registry = stack(tool)
        with pytest.raises(ToolLoopExhaustedError) as info:
            run_tool_loop(complete, prompt="p", tools=[spec()], router=router, registry=registry)
        err = info.value
        assert len(calls_made) == 5  # exactly five provider calls, never a sixth
        assert (err.limit, err.rounds, err.tool_executions) == ("model_rounds", 5, 4)
        assert len(tool.calls) == 4  # the fifth response's call was not run
        assert [o.call_id for o in err.outcomes] == ["id1", "id2", "id3", "id4"]

    def test_error_message_is_structural(self) -> None:
        def complete(request: AIRequest) -> AIResponse:
            return respond(call(f"id{len(request.tool_exchanges)}", city=SECRET))

        router, registry = stack(Tool("read"))
        with pytest.raises(ToolLoopExhaustedError) as info:
            run_tool_loop(complete, prompt="p", tools=[spec()], router=router, registry=registry)
        assert str(info.value) == "tool loop exhausted: model_rounds limit (5) reached" and SECRET not in str(info.value)


# ── OD-C limits: tool executions ────────────────────────────────────────


class TestToolExecutionLimit:
    def test_ten_executions_in_one_round_are_allowed(self) -> None:
        tool = Tool("read")
        result = run(Script(respond(*[call(str(i)) for i in range(10)]), final()), [spec()], tool)
        assert result.tool_executions == 10 and len(tool.calls) == 10

    def test_the_eleventh_execution_raises_before_it_is_invoked(self) -> None:
        tool = Tool("read")
        with pytest.raises(ToolLoopExhaustedError) as info:
            run(Script(respond(*[call(str(i)) for i in range(11)]), final()), [spec()], tool)
        err = info.value
        assert len(tool.calls) == 10 and (err.limit, err.tool_executions) == ("tool_executions", 10)
        assert len(err.outcomes) == 10 and all(o.outcome == "executed" for o in err.outcomes)
        assert str(err) == "tool loop exhausted: tool_executions limit (10) reached"

    def test_limit_is_checked_before_the_confirmation_hook(self) -> None:
        asked: list[ToolCall] = []
        tool = Tool("write")
        reads = [call(str(i), "write") for i in range(10)]
        with pytest.raises(ToolLoopExhaustedError):
            run(Script(respond(*reads, call("11", "write")), final()), [spec("write", side_effects=True)], tool,
                confirm=lambda c, s: asked.append(c) or True)
        assert len(asked) == 10 and len(tool.calls) == 10  # never asked about the 11th

    def test_executions_accumulate_across_rounds(self) -> None:
        tool = Tool("read")
        rounds = [respond(*[call(f"r{r}-{i}") for i in range(3)]) for r in range(4)]  # 12 calls over 4 rounds
        with pytest.raises(ToolLoopExhaustedError) as info:
            run(Script(*rounds, final()), [spec()], tool)
        assert info.value.limit == "tool_executions" and len(tool.calls) == 10 and info.value.rounds == 4

    def test_refused_calls_are_not_executions(self) -> None:
        result = run(Script(respond(*[call(str(i), "ghost") for i in range(25)]), final()), [spec()], Tool("read"))
        assert result.tool_executions == 0 and len(result.outcomes) == 25

    def test_denied_confirmations_are_not_executions(self) -> None:
        tool = Tool("write")
        result = run(Script(respond(*[call(str(i), "write") for i in range(15)]), final()),
                     [spec("write", side_effects=True)], tool, confirm=lambda c, s: False)
        assert result.tool_executions == 0 and tool.calls == []

    def test_failed_calls_count_as_executions(self) -> None:
        tool = Tool("read", ToolError("x"))
        with pytest.raises(ToolLoopExhaustedError) as info:
            run(Script(respond(*[call(str(i)) for i in range(11)]), final()), [spec()], tool)
        assert len(tool.calls) == 10 and all(o.outcome == "failed" for o in info.value.outcomes)

    def test_refusals_and_executions_mix_without_miscounting(self) -> None:
        tool = Tool("read")
        calls = [call(f"g{i}", "ghost") for i in range(8)] + [call(f"r{i}") for i in range(10)]
        result = run(Script(respond(*calls), final()), [spec()], tool)
        assert result.tool_executions == 10 and len(result.outcomes) == 18


# ── the exhaustion error and the loop's separation from v8.33 ───────────


class TestExhaustedError:
    def test_hierarchy_and_attributes(self) -> None:
        err = ToolLoopExhaustedError("model_rounds", 5, 3, (ToolCallOutcome("a", "t", "refused"),))
        assert isinstance(err, Exception) and not isinstance(err, (ValueError, ToolError))
        assert (err.limit, err.rounds, err.tool_executions) == ("model_rounds", 5, 3)
        assert err.outcomes == (ToolCallOutcome("a", "t", "refused"),) and isinstance(err.outcomes, tuple)

    def test_unknown_limit_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolLoopExhaustedError("something", 1, 1, ())

    def test_counters_are_local_to_a_run(self) -> None:
        tool = Tool("read")
        with pytest.raises(ToolLoopExhaustedError):
            run(Script(respond(*[call(str(i)) for i in range(11)]), final()), [spec()], tool)
        result = run(Script(respond(*[call(str(i)) for i in range(10)]), final()), [spec()], Tool("read"))
        assert result.tool_executions == 10  # a fresh run starts from zero


# ── O9 records and results ──────────────────────────────────────────────


class TestOutcomeRecords:
    def test_locked_fields_exactly(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolCallOutcome)] == ["call_id", "tool_name", "outcome", "exception_type"]
        assert [f.name for f in dataclasses.fields(ToolLoopResult)] == ["response", "outcomes", "rounds", "tool_executions"]

    def test_records_are_frozen_and_slotted(self) -> None:
        o = ToolCallOutcome("a", "t", "executed")
        with pytest.raises(dataclasses.FrozenInstanceError):
            o.outcome = "failed"  # type: ignore[misc]
        assert not hasattr(o, "__dict__")

    @pytest.mark.parametrize("kwargs", [
        dict(call_id="", tool_name="t", outcome="executed"),
        dict(call_id="a", tool_name=" ", outcome="executed"),
        dict(call_id="a", tool_name="t", outcome="weird"),
        dict(call_id="a", tool_name="t", outcome="failed"),
        dict(call_id="a", tool_name="t", outcome="failed", exception_type=" "),
        dict(call_id="a", tool_name="t", outcome="executed", exception_type="X"),
        dict(call_id="a", tool_name="t", outcome="refused", exception_type="X"),
    ])
    def test_record_validation(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            ToolCallOutcome(**kwargs)

    def test_outcomes_are_one_per_call_in_order_and_hold_no_arguments(self) -> None:
        calls = [call("1", "read", city="PrivateCity"), call("2", "ghost"), call("3", "read")]
        result = run(Script(respond(*calls), final()), [spec()], Tool("read"))
        assert [(o.call_id, o.outcome) for o in result.outcomes] == [("1", "executed"), ("2", "refused"), ("3", "executed")]
        assert "PrivateCity" not in repr(result.outcomes)


# ── argument validation ─────────────────────────────────────────────────


class TestArguments:
    def test_collaborators_are_checked(self) -> None:
        router, registry = stack(Tool("read"))
        with pytest.raises(TypeError):
            run_tool_loop("nope", prompt="p", tools=[spec()], router=router, registry=registry)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            run_tool_loop(Script(final()), prompt="p", tools=[spec()], router=object(), registry=registry)
        with pytest.raises(TypeError):
            run_tool_loop(Script(final()), prompt="p", tools=[spec()], router=router, registry=object())


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def _tree(self) -> ast.Module:
        with open(rt.__file__, encoding="utf-8") as f:
            return ast.parse(f.read())

    def test_imports_are_limited(self) -> None:
        tree = self._tree()
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Import)]
        assert mods == {"__future__", "collections.abc", "dataclasses", "typing", "core.ai_provider",
                        "core.tool_calling", "core.tool_interface"}

    def test_no_router_registry_catalog_agent_or_provider_modules(self) -> None:
        source = open(rt.__file__, encoding="utf-8").read().lower()
        for token in ("tool_router", "tool_registry", "tool_catalog"):  # the v8.12 / v8.14 / v8.31 source-text pins
            assert token not in source, token
        tree = self._tree()
        words = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                 | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                 | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
        lowered = {w.lower() for w in words if w}
        for token in ("claude", "openai", "gemini", "ollama", "anthropic", "agent", "memory", "reflection", "learning"):
            assert not any(token in w for w in lowered), token

    def test_hard_bounded_loop_without_while_async_or_sleep(self) -> None:
        tree = self._tree()
        assert not [n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.AsyncFunctionDef, ast.Await))]
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not {"sleep", "time", "threading", "asyncio", "random", "uuid"} & names
        fors = [n for n in ast.walk(tree) if isinstance(n, ast.For)]
        assert any(isinstance(f.iter, ast.Call) and getattr(f.iter.func, "id", "") == "range" for f in fors)

    def test_no_module_level_mutable_state(self) -> None:
        for node in self._tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target])]
                if targets == ["__all__"]:
                    continue
                assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp)), targets

    def test_public_surface(self) -> None:
        assert rt.__all__ == ["MAX_MODEL_ROUNDS", "MAX_TOOL_EXECUTIONS", "ToolCallOutcome", "ToolLoopExhaustedError",
                              "ToolLoopResult", "run_tool_loop"]

    def test_nothing_else_in_core_imports_the_leaf_except_the_agent(self) -> None:
        core_dir = os.path.dirname(rt.__file__)
        for dirpath, _, files in os.walk(core_dir):
            for name in files:
                if name.endswith(".py") and name != "tool_runtime.py":
                    path = os.path.join(dirpath, name)
                    if os.path.basename(dirpath) == "agent" and name == "__init__.py":
                        continue
                    assert "tool_runtime" not in open(path, encoding="utf-8").read(), path

    def test_static_mock_tool_round_trip(self) -> None:
        mock = StaticMockTool(output="mock-out", name="read")
        result = run(Script(respond(call("1")), final()), [spec()], mock)
        assert mock.call_count == 1 and result.outcomes[0].outcome == "executed"
