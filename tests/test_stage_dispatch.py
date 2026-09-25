"""Tests for v8.22 Pipeline-Stage Dispatch Decisions (``core.stage_dispatch``)
and ``Agent.execute_projection_with_tool_dispatch``."""

from __future__ import annotations

import ast
import inspect
import os
from datetime import datetime, timezone

import pytest

import core.agent as agent_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
import core.stage_dispatch as stage_module
from core.agent import Agent
from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager
from core.pipeline_engine import PipelineEngine, PipelineRecord
from core.plan_projection import PlanProjection, project_execution_plan
from core.planner import ExecutionPlan, Goal, InvalidGoalError, Task
from core.planning_engine import PlanningEngine
from core.stage_dispatch import build_stage_dispatch_decisions
from core.task_graph import TaskGraph
from core.tool_dispatch import ToolDispatchDecision
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "stage_dispatch.py")
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")
METHOD = "execute_projection_with_tool_dispatch"


def _tree(path: str = MODULE_PATH) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def _agent_method() -> ast.FunctionDef:
    for node in ast.walk(_tree(AGENT_FILE)):
        if isinstance(node, ast.FunctionDef) and node.name == METHOD:
            return node
    raise AssertionError("method not found")


class Stores:
    def __init__(self) -> None:
        self.goal_manager = GoalManager()
        self.planning_engine = PlanningEngine()
        self.task_graph = TaskGraph()
        self.execution_planner = ExecutionPlanner(
            goal_manager=self.goal_manager, planning_engine=self.planning_engine, task_graph=self.task_graph,
        )
        self.pipeline_engine = PipelineEngine(self.execution_planner, task_graph=self.task_graph)
        self.registry = ToolRegistry()

    def project(self, plan: ExecutionPlan) -> PipelineRecord:
        p = project_execution_plan(
            plan, goal_manager=self.goal_manager, planning_engine=self.planning_engine,
            task_graph=self.task_graph, execution_planner=self.execution_planner,
            pipeline_engine=self.pipeline_engine,
        )
        return self.pipeline_engine.get_pipeline(p.pipeline_id)

    def decisions(self, pipeline: PipelineRecord, context=None) -> tuple[ToolDispatchDecision, ...]:
        return build_stage_dispatch_decisions(
            pipeline, task_graph=self.task_graph, registry=self.registry, context=context,
        )


def make_plan(*tasks: tuple[str, tuple[str, ...]], goal: str = "the goal") -> ExecutionPlan:
    now = datetime.now(timezone.utc)
    return ExecutionPlan(
        id="legacy-plan",
        goal=Goal(id="legacy-goal", description=goal, created_at=now),
        tasks=tuple(Task(id=tid, description=f"do {tid}", depends_on=deps, metadata={}) for tid, deps in tasks),
        created_at=now,
    )


def diamond() -> ExecutionPlan:
    return make_plan(("a", ()), ("b", ("a",)), ("c", ("a",)), ("d", ("b", "c")))


class SpyRouter(ToolRouter):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(registry)
        self.requests: list[ToolRequest] = []

    def route(self, request: ToolRequest) -> ToolResult:
        self.requests.append(request)
        return super().route(request)


class Failing:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fails"
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"simulated tool failure: {request.tool_name}")


# ── build_stage_dispatch_decisions ──────────────────────────────────────


class TestStageDecisions:
    def test_one_decision_per_stage_in_order(self) -> None:
        s = Stores()
        pipeline = s.project(diamond())
        decisions = s.decisions(pipeline)
        assert len(decisions) == 4
        assert [d.task_id for d in decisions] == ["a", "b", "c", "d"]
        assert [d.tool_name for d in decisions] == ["do a", "do b", "do c", "do d"]

    def test_task_id_from_node_metadata_and_tool_name_from_title(self) -> None:
        s = Stores()
        pipeline = s.project(make_plan(("t1", ())))
        (d,) = s.decisions(pipeline)
        node = s.task_graph.get_node(pipeline.stages[0].node_id)
        assert d.task_id == node.metadata["task_id"] == "t1"
        assert d.tool_name == node.title == "do t1"

    def test_gated_by_registry(self) -> None:
        s = Stores()
        s.registry.register(StaticMockTool(name="do b"))
        pipeline = s.project(diamond())
        decisions = s.decisions(pipeline)
        assert [d.action for d in decisions] == ["skip", "dispatch", "skip", "skip"]
        assert decisions[1].would_dispatch is True

    def test_context_propagated(self) -> None:
        s = Stores()
        pipeline = s.project(make_plan(("t1", ())))
        (d,) = s.decisions(pipeline, context={"project": "p"})
        assert dict(d.context) == {"project": "p"}

    def test_empty_pipeline(self) -> None:
        s = Stores()
        pipeline = s.project(make_plan())
        assert s.decisions(pipeline) == ()

    def test_unknown_node_raises_key_error(self) -> None:
        s = Stores()
        pipeline = s.project(make_plan(("t1", ())))
        other = TaskGraph()
        with pytest.raises(KeyError):
            build_stage_dispatch_decisions(pipeline, task_graph=other, registry=s.registry)

    def test_node_without_task_id_falls_back_to_node_id(self) -> None:
        s = Stores()
        planner = ExecutionPlanner(task_graph=s.task_graph)
        engine = PipelineEngine(planner, task_graph=s.task_graph)
        s.task_graph.create_node(title="manual tool", node_id="n1")
        m = planner.create_execution_plan(ordered_node_ids=("n1",))
        pipeline = engine.build_pipeline(m.id)
        (d,) = build_stage_dispatch_decisions(pipeline, task_graph=s.task_graph, registry=s.registry)
        assert d.task_id == "n1" and d.tool_name == "manual tool"

    def test_type_validation(self) -> None:
        s = Stores()
        pipeline = s.project(make_plan(("t1", ())))
        with pytest.raises(TypeError):
            build_stage_dispatch_decisions("x", task_graph=s.task_graph, registry=s.registry)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            build_stage_dispatch_decisions(pipeline, task_graph=object(), registry=s.registry)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            build_stage_dispatch_decisions(pipeline, task_graph=s.task_graph, registry=object())  # type: ignore[arg-type]

    def test_read_only_no_invocation_no_mutation(self) -> None:
        s = Stores()
        tool = StaticMockTool(name="do a")
        s.registry.register(tool)
        pipeline = s.project(diamond())
        before = (s.task_graph.count(), s.registry.names(), s.pipeline_engine.count())
        s.decisions(pipeline)
        assert tool.call_count == 0
        assert (s.task_graph.count(), s.registry.names(), s.pipeline_engine.count()) == before

    def test_deterministic(self) -> None:
        s = Stores()
        pipeline = s.project(diamond())
        assert s.decisions(pipeline, context={"p": 1}) == s.decisions(pipeline, context={"p": 1})

    def test_depends_on_not_evaluated(self) -> None:
        # Every stage yields a decision regardless of depends_on (descriptive only).
        s = Stores()
        for n in ("do a", "do b", "do c", "do d"):
            s.registry.register(StaticMockTool(name=n))
        decisions = s.decisions(s.project(diamond()))
        assert all(d.would_dispatch for d in decisions)


# ── Agent.execute_projection_with_tool_dispatch ─────────────────────────


def agent_with(*tools: object) -> tuple[Agent, SpyRouter]:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    router = SpyRouter(reg)
    return Agent(tool_registry=reg, tool_router=router), router


class TestAgentProjectionDispatch:
    def test_signature_and_return_shape(self) -> None:
        params = inspect.signature(getattr(Agent, METHOD)).parameters
        assert list(params) == ["self", "goal", "project"]
        assert params["project"].kind is inspect.Parameter.KEYWORD_ONLY
        a, _ = agent_with()
        out = a.execute_projection_with_tool_dispatch("fix the wifi")
        assert isinstance(out, tuple) and len(out) == 3
        projection, decisions, results = out
        assert isinstance(projection, PlanProjection)
        assert all(isinstance(d, ToolDispatchDecision) for d in decisions)
        assert results == ()

    def test_projects_then_dispatches_in_stage_order(self) -> None:
        a, router = agent_with(StaticMockTool(name="step one", output="1"), StaticMockTool(name="step three", output="3"))
        projection, decisions, results = a.execute_projection_with_tool_dispatch("step one then step two then step three")
        assert [d.action for d in decisions] == ["dispatch", "skip", "dispatch"]
        assert [r.output for r in results] == ["1", "3"]
        assert [r.tool_name for r in router.requests] == ["step one", "step three"]
        stages = a.pipeline_engine.get_pipeline(projection.pipeline_id).stages
        assert [d.tool_name for d in decisions] == [a.task_graph.get_node(st.node_id).title for st in stages]

    def test_all_stages_dispatched_not_only_roots(self) -> None:
        # Unlike the legacy coordinator (roots only), every stage runs in order.
        a, router = agent_with(StaticMockTool(name="step one"), StaticMockTool(name="step two"))
        _, decisions, results = a.execute_projection_with_tool_dispatch("step one then step two")
        assert [d.action for d in decisions] == ["dispatch", "dispatch"]
        assert len(results) == 2
        legacy_result, legacy_decisions, _ = a.execute_request_with_tool_dispatch("step one then step two")
        assert len(legacy_decisions) == 1  # legacy path unchanged: roots only

    def test_exact_request_arguments_and_identity(self) -> None:
        class Spy:
            name = "fix the wifi"
            description = "d"
            received: list[ToolRequest] = []
            result = ToolResult("fix the wifi", "ok")

            def invoke(self, request: ToolRequest) -> ToolResult:
                self.received.append(request)
                return self.result

        spy = Spy()
        a, router = agent_with(spy)
        _, _, results = a.execute_projection_with_tool_dispatch("fix the wifi", project="p")
        assert results[0] is spy.result
        assert spy.received[0] is router.requests[0]
        assert dict(router.requests[0].arguments) == {"problem": "fix the wifi"}
        assert "project" not in router.requests[0].arguments

    def test_project_in_decision_context(self) -> None:
        a, _ = agent_with()
        _, decisions, _ = a.execute_projection_with_tool_dispatch("fix the wifi", project="mark_l")
        assert dict(decisions[0].context) == {"project": "mark_l"}

    def test_decisions_task_ids_are_legacy_task_ids(self) -> None:
        a, _ = agent_with()
        projection, decisions, _ = a.execute_projection_with_tool_dispatch("step one then step two")
        assert [d.task_id for d in decisions] == list(projection.step_ids)

    def test_exception_propagates_and_stops(self) -> None:
        later = StaticMockTool(name="step two")
        failing = Failing("step one")
        a, router = agent_with(failing, later)
        with pytest.raises(RuntimeError, match="simulated tool failure: step one"):
            a.execute_projection_with_tool_dispatch("step one then step two")
        assert failing.calls == 1
        assert later.call_count == 0
        assert [r.tool_name for r in router.requests] == ["step one"]

    def test_tool_error_propagates(self) -> None:
        class F:
            name = "fix the wifi"
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError("tool failed")

        a, _ = agent_with(F())
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_projection_with_tool_dispatch("fix the wifi")

    def test_blank_goal_legacy_error_before_projection(self) -> None:
        a, _ = agent_with()
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_tool_dispatch("  ")
        assert a.goal_manager.count() == 0

    def test_projection_persisted_in_agent_stores(self) -> None:
        a, _ = agent_with()
        projection, _, _ = a.execute_projection_with_tool_dispatch("fix the wifi")
        assert a.pipeline_engine.get_pipeline(projection.pipeline_id) is not None
        assert a.goal_manager.get_goal(projection.goal_id) is not None

    def test_repeated_calls_isolated(self) -> None:
        a, _ = agent_with(StaticMockTool(name="fix the wifi"))
        p1, d1, r1 = a.execute_projection_with_tool_dispatch("fix the wifi")
        p2, d2, r2 = a.execute_projection_with_tool_dispatch("fix the wifi")
        assert p1.pipeline_id != p2.pipeline_id
        assert d1 == d2 and r1 == r2 and r1 is not r2
        assert a.pipeline_engine.count() == 2

    def test_no_pipeline_run_no_writeback(self) -> None:
        a, _ = agent_with(StaticMockTool(name="fix the wifi"))
        a.execute_projection_with_tool_dispatch("fix the wifi")
        assert a.pipeline_run_manager.count() == 0
        assert a.memory_engine.count() == 0
        assert a.reflection_engine.count() == 0
        assert a.snapshot()["learning"] == []

    def test_registry_not_modified(self) -> None:
        a, _ = agent_with(StaticMockTool(name="fix the wifi"))
        before = a.tool_registry.names()
        a.execute_projection_with_tool_dispatch("fix the wifi")
        assert a.tool_registry.names() == before

    def test_injected_router_only_gate_is_agent_registry(self) -> None:
        own = ToolRegistry()
        own.register(StaticMockTool(name="fix the wifi"))
        router = SpyRouter(own)
        a = Agent(tool_router=router)
        _, decisions, results = a.execute_projection_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "skip" and results == () and router.requests == []

    def test_incompatible_injected_wiring_fails_loudly(self) -> None:
        a = Agent(execution_planner=ExecutionPlanner(goal_manager=GoalManager()))
        with pytest.raises(ValueError):
            a.execute_projection_with_tool_dispatch("fix the wifi")


class TestLegacyIsolation:
    def test_no_legacy_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or False)
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(agent_module, "gather_context", lambda **k: called.append("gather") or {})
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        a, _ = agent_with(StaticMockTool(name="fix the wifi"))
        monkeypatch.setattr(a, "coordinate_execution", lambda s: called.append("coordinate"))
        monkeypatch.setattr(a, "create_execution_session", lambda *x, **k: called.append("session"))
        a.execute_projection_with_tool_dispatch("fix the wifi")
        assert called == []

    def test_legacy_chains_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a, router = agent_with()
        a.execute_request_with_skill_execution("fix the wifi")
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert router.requests == []
        assert a.pipeline_engine.count() == 0  # legacy paths never project

    def test_skill_globals_untouched(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        a, _ = agent_with()
        a.execute_projection_with_tool_dispatch("fix the wifi")
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001


class TestArchitecture:
    def test_all_exact(self) -> None:
        assert stage_module.__all__ == ["build_stage_dispatch_decisions"]

    def test_import_allowlist(self) -> None:
        allowed_roots = {"__future__", "typing", "dataclasses", "types"}
        allowed_full = {"core.pipeline_engine", "core.task_graph", "core.tool_dispatch", "core.tool_registry"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] in allowed_roots or node.module in allowed_full, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_forbidden_imports(self) -> None:
        forbidden = {
            "core.agent", "core.tool_router", "core.tool_interface", "core.skill_registry",
            "core.skill_dispatch", "core.skill_tool_adapter", "core.pipeline_run",
            "core.plan_projection", "core.planner", "core.execution_pipeline",
            "core.execution_orchestrator", "core.ai_service", "core.memory_engine",
            "os", "sys", "asyncio", "threading", "subprocess", "logging", "json",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden and node.module.split(".")[0] not in forbidden, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] not in forbidden, n.name

    def test_no_routing_or_mutation_calls(self) -> None:
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(_tree()) if isinstance(c, ast.Call)}
        for forbidden in ("route", "invoke", "register", "create_node", "connect", "build_pipeline",
                          "create_run", "update_run", "dispatch", "is_registered"):
            assert forbidden not in calls, forbidden
        assert {"build_tool_dispatch_decision", "get_node"} <= calls
        for n in ast.walk(_tree()):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler, ast.AsyncFunctionDef, ast.Await))

    def test_no_module_level_state(self) -> None:
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                           if isinstance(node, ast.Assign)
                           else [node.target.id] if isinstance(node.target, ast.Name) else [])
                assert targets == ["__all__"], targets

    def test_no_core_module_imports_stage_dispatch_except_agent(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "stage_dispatch.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "stage_dispatch" not in f.read(), name

    def test_agent_method_is_thin_glue(self) -> None:
        node = _agent_method()
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"project_request", "get_pipeline", "KeyError",
                         "build_stage_dispatch_decisions", "ToolRequest", "route", "append", "tuple"}
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        for forbidden in ("skill_dispatch", "is_registered", "build_dispatch_decision", "gather_context",
                          "record_problem_outcome", "build_result_from_session"):
            assert forbidden not in names, forbidden
        for n in ast.walk(node):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))

    def test_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "PlanProjection" not in agent_module.__all__
