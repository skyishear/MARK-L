"""Tests for v8.21 ``Agent.project_request``."""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.agent as agent_module
import core.skill_registry as skill_registry
from core.agent import Agent
from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager
from core.pipeline_engine import PipelineEngine
from core.plan_projection import PlanProjection
from core.planner import ExecutionPlan, InvalidGoalError, PlanningEngine as LegacyPlanningEngine
from core.planning_engine import PlanningEngine as FoundationPlanningEngine
from core.task_graph import TaskGraph
from core.tool_interface import StaticMockTool
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")


def _method_node() -> ast.FunctionDef:
    with open(AGENT_FILE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "project_request":
            return node
    raise AssertionError("method not found")


class TestProjectRequest:
    def test_signature(self) -> None:
        params = inspect.signature(Agent.project_request).parameters
        assert list(params) == ["self", "goal"]

    def test_returns_plan_and_projection(self) -> None:
        plan, projection = Agent().project_request("step one then step two")
        assert isinstance(plan, ExecutionPlan)
        assert isinstance(projection, PlanProjection)

    def test_uses_legacy_planning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        calls: list[str] = []
        original = a.planning.plan
        produced: list[ExecutionPlan] = []

        def spy(goal: str) -> ExecutionPlan:
            calls.append(goal)
            result = original(goal)
            produced.append(result)
            return result

        monkeypatch.setattr(a.planning, "plan", spy)
        plan, _ = a.project_request("fix the wifi")
        assert calls == ["fix the wifi"]
        assert plan is produced[0]  # the exact legacy plan object is returned
        assert isinstance(a.planning, LegacyPlanningEngine)

    def test_plan_equals_direct_legacy_plan_structure(self) -> None:
        a = Agent()
        plan, _ = a.project_request("step one then step two")
        ref = a.planning.plan("step one then step two")
        assert plan.id == ref.id
        assert [t.id for t in plan.tasks] == [t.id for t in ref.tasks]

    def test_blank_goal_raises_legacy_error_before_projection(self) -> None:
        a = Agent()
        with pytest.raises(InvalidGoalError):
            a.project_request("   ")
        assert a.goal_manager.count() == 0 and a.planning_engine.count() == 0

    def test_uses_agent_owned_stores(self) -> None:
        a = Agent()
        plan, p = a.project_request("step one then step two")
        assert a.goal_manager.get_goal(p.goal_id) is not None
        assert a.planning_engine.get_plan(p.plan_id) is not None
        assert all(a.task_graph.get_node(n) is not None for n in p.node_ids)
        assert a.execution_planner.get_execution_plan(p.mapping_id) is not None
        assert a.pipeline_engine.get_pipeline(p.pipeline_id) is not None
        assert a.goal_manager.get_goal(p.goal_id).tags == (plan.goal.id,)

    def test_projection_content(self) -> None:
        a = Agent()
        plan, p = a.project_request("step one then step two then step three")
        assert p.step_ids == tuple(t.id for t in plan.tasks)
        stages = a.pipeline_engine.get_pipeline(p.pipeline_id).stages
        assert [st.node_id for st in stages] == [p.task_to_node[t.id] for t in plan.execution_order()]
        assert p.graph_reference == p.plan_id

    def test_injected_stores_used_verbatim(self) -> None:
        gm, pe, tg = GoalManager(), FoundationPlanningEngine(), TaskGraph()
        ep = ExecutionPlanner(goal_manager=gm, planning_engine=pe, task_graph=tg)
        pipe = PipelineEngine(ep, task_graph=tg)
        a = Agent(goal_manager=gm, planning_engine=pe, task_graph=tg, execution_planner=ep, pipeline_engine=pipe)
        _, p = a.project_request("fix the wifi")
        assert gm.get_goal(p.goal_id) is not None
        assert pe.get_plan(p.plan_id) is not None
        assert tg.count() == 1
        assert pipe.get_pipeline(p.pipeline_id) is not None

    def test_incompatible_injected_wiring_fails_loudly(self) -> None:
        # v8.10 does not reconcile: planner wired to a foreign goal manager.
        foreign = ExecutionPlanner(goal_manager=GoalManager())
        a = Agent(execution_planner=foreign)
        with pytest.raises(ValueError):
            a.project_request("fix the wifi")
        assert a.goal_manager.count() == 0 and a.planning_engine.count() == 0

    def test_repeated_requests_create_independent_projections(self) -> None:
        a = Agent()
        _, p1 = a.project_request("fix the wifi")
        _, p2 = a.project_request("fix the wifi")
        assert p1.goal_id != p2.goal_id and p1.plan_id != p2.plan_id
        assert not set(p1.node_ids) & set(p2.node_ids)
        assert a.goal_manager.count() == 2

    def test_no_pipeline_run_created(self) -> None:
        a = Agent()
        a.project_request("fix the wifi")
        assert a.pipeline_run_manager.count() == 0

    def test_no_tool_routing_or_writeback(self) -> None:
        class SpyRouter(ToolRouter):
            def __init__(self, r: ToolRegistry) -> None:
                super().__init__(r)
                self.calls = 0

            def route(self, request):  # pragma: no cover - must never run
                self.calls += 1
                return super().route(request)

        reg = ToolRegistry()
        reg.register(StaticMockTool(name="fix the wifi"))
        router = SpyRouter(reg)
        a = Agent(tool_registry=reg, tool_router=router)
        a.project_request("fix the wifi")
        assert router.calls == 0
        assert a.memory_engine.count() == 0
        assert a.reflection_engine.count() == 0
        assert a.snapshot()["learning"] == []

    def test_no_skill_globals_touched(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        Agent().project_request("fix the wifi")
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001


class TestLegacyBehaviourUnchanged:
    def test_existing_execution_methods_unaffected(self) -> None:
        a = Agent()
        a.project_request("fix the wifi")
        ref = Agent()
        assert a.handle_request("fix the wifi").ready_task_ids == ref.handle_request("fix the wifi").ready_task_ids
        assert a.execute_request("fix the wifi").session_id == ref.execute_request("fix the wifi").session_id
        r1, d1, t1 = a.execute_request_with_tool_dispatch("fix the wifi")
        r2, d2, t2 = ref.execute_request_with_tool_dispatch("fix the wifi")
        assert (r1.session_id, d1, t1) == (r2.session_id, d2, t2)

    def test_execution_paths_do_not_project(self) -> None:
        a = Agent()
        a.handle_request("fix the wifi")
        a.execute_request_with_learning("fix the wifi")
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.goal_manager.count() == 0
        assert a.planning_engine.count() == 0
        assert a.task_graph.count() == 0
        assert a.pipeline_engine.count() == 0

    def test_all_unchanged(self) -> None:
        assert set(agent_module.__all__) == {
            "Agent", "CoordinationSnapshot", "ContextManager", "ExecutionCoordinator",
            "ExecutionOrchestrator", "ExecutionPipeline", "ExecutionResult",
            "ExecutionSession", "HistoryManager", "KnowledgeManager", "LearningManager",
            "MemoryIndexManager", "PlanningEngine", "ReasoningManager",
            "ReflectionManager", "SkillDispatchDecision",
        }
        assert "PlanProjection" not in agent_module.__all__

    def test_constructor_unchanged(self) -> None:
        names = list(inspect.signature(Agent.__init__).parameters)
        assert names[-2:] == ["tool_registry", "tool_router"]
        assert len(names) == 23  # self + 22 existing dependencies; no new parameter


class TestArchitecture:
    def test_method_is_thin_glue(self) -> None:
        node = _method_node()
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"plan", "project_execution_plan"}
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert attrs == {"planning", "plan", "_goal_manager", "_planning_engine", "_task_graph",
                         "_execution_planner", "_pipeline_engine"}
        for n in ast.walk(node):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))

    def test_agent_imports_projection_module(self) -> None:
        with open(AGENT_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imported = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module for a in n.names}
        assert ("core.plan_projection", "PlanProjection") in imported
        assert ("core.plan_projection", "project_execution_plan") in imported

    def test_projection_module_does_not_import_agent(self) -> None:
        with open(os.path.join(ROOT, "core", "plan_projection.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                assert not n.module.startswith("core.agent")
