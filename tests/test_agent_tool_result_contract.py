"""Tests for v8.19 Tool Result Integration — the public contract of
``Agent.execute_request_with_tool_dispatch``."""

from __future__ import annotations

import dataclasses
import inspect
import typing

import pytest

import core.agent as agent_module
from core.agent import Agent
from core.execution_result import ExecutionResult
from core.planner import PlanningEngine as LegacyPlanningEngine
from core.tool_dispatch import ToolDispatchDecision
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

METHOD = "execute_request_with_tool_dispatch"


class Desc:
    def __init__(self, task_id: str, problem: str) -> None:
        self.task_id = task_id
        self.work_item = type("W", (), {"problem": problem})()


def force_ready(monkeypatch: pytest.MonkeyPatch, agent: Agent, *problems: str) -> None:
    descs = tuple(Desc(f"t{i}", pr) for i, pr in enumerate(problems, 1))
    monkeypatch.setattr(
        agent, "coordinate_execution",
        lambda session: type("Coord", (), {"ready_descriptors": descs})(),
    )


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise self.exc


class TestContractShape:
    def test_return_annotation(self) -> None:
        hints = typing.get_type_hints(getattr(Agent, METHOD))
        assert hints["return"] == tuple[ExecutionResult, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]

    def test_signature_stable(self) -> None:
        sig = inspect.signature(getattr(Agent, METHOD))
        assert str(sig).startswith("(self, goal: 'str', *, project: 'str | None' = None, metadata:")

    def test_three_tuple_of_exact_types(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        result, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert type(result) is ExecutionResult
        assert all(type(d) is ToolDispatchDecision for d in decisions)
        assert all(type(r) is ToolResult for r in results)
        assert isinstance(decisions, tuple) and isinstance(results, tuple)

    def test_execution_result_is_legacy_type(self) -> None:
        result, _, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert type(result).__module__ == "core.execution_result"
        assert not hasattr(result, "tool_results")

    def test_tool_result_not_inside_decision(self) -> None:
        names = {f.name for f in dataclasses.fields(ToolDispatchDecision)}
        assert "result" not in names and "tool_result" not in names and "output" not in names


class TestScenarios:
    def test_empty_goal_follows_planning_semantics(self) -> None:
        a = Agent()
        with pytest.raises(ValueError):
            a.planning.plan("")
        with pytest.raises(ValueError):
            a.execute_request_with_tool_dispatch("")
        a.tool_registry.register(StaticMockTool(name="x"))
        assert a.tool_registry.get("x").call_count == 0

    def test_zero_ready_descriptors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        force_ready(monkeypatch, a)
        result, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert isinstance(result, ExecutionResult)
        assert decisions == () and results == ()

    def test_all_tools_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        force_ready(monkeypatch, a, "one", "two")
        _, decisions, results = a.execute_request_with_tool_dispatch("g")
        assert [d.action for d in decisions] == ["skip", "skip"]
        assert results == ()

    def test_one_successful_tool(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi", output="done"))
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert [d.action for d in decisions] == ["dispatch"]
        assert results == (ToolResult("fix the wifi", "done"),)

    def test_multiple_successful_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        for n in ("one", "two", "three"):
            a.tool_registry.register(StaticMockTool(name=n, output=n.upper()))
        force_ready(monkeypatch, a, "one", "two", "three")
        _, decisions, results = a.execute_request_with_tool_dispatch("g")
        assert [d.action for d in decisions] == ["dispatch"] * 3
        assert [r.output for r in results] == ["ONE", "TWO", "THREE"]

    def test_mixed_skip_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="two", output="2"))
        force_ready(monkeypatch, a, "one", "two", "three")
        _, decisions, results = a.execute_request_with_tool_dispatch("g")
        assert [d.action for d in decisions] == ["skip", "dispatch", "skip"]
        assert results == (ToolResult("two", "2"),)

    def test_exact_result_ordering_matches_dispatch_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        for n in ("c", "a", "b"):
            a.tool_registry.register(StaticMockTool(name=n, output=n))
        force_ready(monkeypatch, a, "c", "x", "a", "y", "b")
        _, decisions, results = a.execute_request_with_tool_dispatch("g")
        dispatched = [d.tool_name for d in decisions if d.would_dispatch]
        assert [r.tool_name for r in results] == dispatched == ["c", "a", "b"]

    def test_results_count_equals_dispatched_decisions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one"))
        a.tool_registry.register(StaticMockTool(name="three"))
        force_ready(monkeypatch, a, "one", "two", "three", "four")
        _, decisions, results = a.execute_request_with_tool_dispatch("g")
        assert len(results) == sum(1 for d in decisions if d.would_dispatch) == 2

    def test_exact_object_identity(self) -> None:
        class Fixed:
            name = "fix the wifi"
            description = "d"
            result = ToolResult("fix the wifi", "fixed")

            def invoke(self, request: ToolRequest) -> ToolResult:
                return self.result

        tool = Fixed()
        a = Agent()
        a.tool_registry.register(tool)
        _, _, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert results[0] is tool.result

    def test_failure_propagation_runtime_error(self) -> None:
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi", RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            a.execute_request_with_tool_dispatch("fix the wifi")

    def test_failure_propagation_tool_error(self) -> None:
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi", ToolError("tool failed")))
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_request_with_tool_dispatch("fix the wifi")

    def test_exception_never_converted_to_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one", output="1"))
        a.tool_registry.register(Failing("two", KeyError("k")))
        force_ready(monkeypatch, a, "one", "two")
        with pytest.raises(KeyError):
            a.execute_request_with_tool_dispatch("g")

    def test_partial_dispatch_stops_at_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        first = StaticMockTool(name="one", output="1")
        third = StaticMockTool(name="three", output="3")
        a.tool_registry.register(first)
        a.tool_registry.register(Failing("two", RuntimeError("x")))
        a.tool_registry.register(third)
        force_ready(monkeypatch, a, "one", "two", "three")
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch("g")
        assert first.call_count == 1
        assert third.call_count == 0

    def test_repeated_calls_isolated_tuples(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi", output="o"))
        out1 = a.execute_request_with_tool_dispatch("fix the wifi")
        out2 = a.execute_request_with_tool_dispatch("fix the wifi")
        assert out1[1] == out2[1] and out1[1] is not out2[1]
        assert out1[2] == out2[2] and out1[2] is not out2[2]
        assert out1[0].session_id == out2[0].session_id

    def test_deterministic_across_agents(self) -> None:
        def run() -> tuple:
            a = Agent()
            a.tool_registry.register(StaticMockTool(name="fix the wifi", output="o"))
            r, d, res = a.execute_request_with_tool_dispatch("fix the wifi", project="p")
            return r.session_id, d, res

        assert run() == run()


class TestInjectionBehaviour:
    def test_injected_registry_and_router(self) -> None:
        reg = ToolRegistry()
        reg.register(StaticMockTool(name="fix the wifi", output="inj"))
        router = ToolRouter(reg)
        a = Agent(tool_registry=reg, tool_router=router)
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "dispatch"
        assert results == (ToolResult("fix the wifi", "inj"),)

    def test_router_only_injection_from_v8_15_intact(self) -> None:
        own = ToolRegistry()
        own.register(StaticMockTool(name="fix the wifi", output="own"))
        router = ToolRouter(own)
        a = Agent(tool_router=router)
        assert a.tool_router is router and a.tool_router.registry is own
        assert a.tool_registry is not own
        # Gate is Agent's (empty) registry -> skip; the router's registry is not consulted.
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "skip" and results == ()
        # Registering into Agent's registry makes the gate pass, and the
        # injected router (bound to its own registry) then resolves it.
        a.tool_registry.register(StaticMockTool(name="fix the wifi", output="agent"))
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "dispatch"
        assert results == (ToolResult("fix the wifi", "own"),)

    def test_registry_only_injection(self) -> None:
        reg = ToolRegistry()
        reg.register(StaticMockTool(name="fix the wifi", output="r"))
        a = Agent(tool_registry=reg)
        assert a.tool_router.registry is reg
        _, _, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert results == (ToolResult("fix the wifi", "r"),)

    def test_shared_registry_between_agents(self) -> None:
        reg = ToolRegistry()
        reg.register(StaticMockTool(name="fix the wifi", output="s"))
        a, b = Agent(tool_registry=reg), Agent(tool_registry=reg)
        assert a.execute_request_with_tool_dispatch("fix the wifi")[2] == b.execute_request_with_tool_dispatch("fix the wifi")[2]


class TestNoRegression:
    def test_agent_properties_unchanged(self) -> None:
        a = Agent()
        for name in (
            "history", "context", "knowledge", "learning", "memory_index", "reflection",
            "reasoning", "planning", "execution_orchestrator", "execution_pipeline",
            "ai_service", "conversation_history", "memory_engine", "reflection_engine",
            "goal_manager", "planning_engine", "task_graph", "execution_planner",
            "pipeline_engine", "pipeline_run_manager", "tool_registry", "tool_router",
        ):
            assert isinstance(inspect.getattr_static(Agent, name), property), name
            assert getattr(a, name) is not None, name
        assert isinstance(a.planning, LegacyPlanningEngine)

    def test_all_unchanged(self) -> None:
        assert set(agent_module.__all__) == {
            "Agent", "CoordinationSnapshot", "ContextManager", "ExecutionCoordinator",
            "ExecutionOrchestrator", "ExecutionPipeline", "ExecutionResult",
            "ExecutionSession", "HistoryManager", "KnowledgeManager", "LearningManager",
            "MemoryIndexManager", "PlanningEngine", "ReasoningManager",
            "ReflectionManager", "SkillDispatchDecision",
        }

    def test_legacy_methods_unaffected_by_tool_chain_use(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch("fix the wifi")
        ref = Agent()
        assert a.handle_request("fix the wifi").ready_task_ids == ref.handle_request("fix the wifi").ready_task_ids
        r1, d1 = a.execute_request_with_skill_execution("fix the wifi")
        r2, d2 = ref.execute_request_with_skill_execution("fix the wifi")
        assert (r1.session_id, [x.action for x in d1]) == (r2.session_id, [x.action for x in d2])
        assert a.execute_request("fix the wifi").session_id == ref.execute_request("fix the wifi").session_id

    def test_no_writeback_in_tool_chain(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch("fix the wifi", project="p")
        assert a.memory_engine.count() == 0
        assert a.reflection_engine.count() == 0
        snap = a.snapshot()
        assert snap["learning"] == [] and snap["reflection"] == [] and snap["history"] == []

    def test_tool_routing_method_from_v8_16_unchanged(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m", output="single"))
        assert a.execute_request_with_tool_routing("m") == ToolResult("m", "single")
