"""Tests for v8.25 Goal/Plan Lifecycle Reflection
(``core.lifecycle_reflection`` and ``Agent.execute_projection_with_lifecycle``)."""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.agent as agent_module
import core.lifecycle_reflection as lifecycle_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
from core import problem_solver
from core.agent import Agent
from core.goal_manager import GoalManager, GoalStatus
from core.lifecycle_reflection import reflect_execution_completed, reflect_execution_started
from core.pipeline_run import PipelineRun, PipelineRunStatus
from core.plan_projection import PlanProjection
from core.planner import InvalidGoalError
from core.planning_engine import PlanningEngine, PlanStatus
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "lifecycle_reflection.py")
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")
METHOD = "execute_projection_with_lifecycle"
G, P, R = GoalStatus, PlanStatus, PipelineRunStatus


def _tree(path: str = MODULE_PATH) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def _agent_method(name: str = METHOD) -> ast.FunctionDef:
    for node in ast.walk(_tree(AGENT_FILE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("method not found")


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise self.exc


@pytest.fixture
def stub_remember(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    writes: list[tuple] = []
    monkeypatch.setattr(problem_solver, "remember", lambda *a, **k: writes.append((a, k)) or "id")
    return writes


def agent_with(*tools: object) -> Agent:
    a = Agent()
    for t in tools:
        a.tool_registry.register(t)
    return a


def statuses(a: Agent, projection: PlanProjection) -> tuple[GoalStatus, PlanStatus]:
    return (a.goal_manager.get_goal(projection.goal_id).status,
            a.planning_engine.get_plan(projection.plan_id).status)


class Trace:
    """Records the ordered sequence of goal/plan/run status changes."""

    def __init__(self, a: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[tuple[str, object]] = []
        og, op, orun = a.goal_manager.update_goal, a.planning_engine.update_plan, a.pipeline_run_manager.update_run

        def g(goal_id, **k):
            self.events.append(("goal", k.get("status")))
            return og(goal_id, **k)

        def p(plan_id, **k):
            if "steps" in k:  # v8.26 step reflection (whole-tuple replacement)
                self.events.append(("steps", tuple(s.status for s in k["steps"])))
            else:
                self.events.append(("plan", k.get("status")))
            return op(plan_id, **k)

        def r(run_id, **k):
            self.events.append(("run", k.get("status")))
            return orun(run_id, **k)

        monkeypatch.setattr(a.goal_manager, "update_goal", g)
        monkeypatch.setattr(a.planning_engine, "update_plan", p)
        monkeypatch.setattr(a.pipeline_run_manager, "update_run", r)


# ── leaf module ─────────────────────────────────────────────────────────


class TestReflectionFunctions:
    def test_started_marks_active(self) -> None:
        gm, pe = GoalManager(), PlanningEngine()
        g = gm.create_goal(title="t")
        p = pe.create_plan(goal="g")
        reflect_execution_started(g.id, p.id, goal_manager=gm, planning_engine=pe)
        assert gm.get_goal(g.id).status is G.ACTIVE
        assert pe.get_plan(p.id).status is P.ACTIVE

    def test_completed_marks_completed(self) -> None:
        gm, pe = GoalManager(), PlanningEngine()
        g = gm.create_goal(title="t", status=G.ACTIVE)
        p = pe.create_plan(goal="g", status=P.ACTIVE)
        reflect_execution_completed(g.id, p.id, goal_manager=gm, planning_engine=pe)
        assert gm.get_goal(g.id).status is G.COMPLETED
        assert pe.get_plan(p.id).status is P.COMPLETED

    def test_order_goal_then_plan_on_start_plan_then_goal_on_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gm, pe = GoalManager(), PlanningEngine()
        g, p = gm.create_goal(title="t"), pe.create_plan(goal="g")
        order: list[str] = []
        og, op = gm.update_goal, pe.update_plan
        monkeypatch.setattr(gm, "update_goal", lambda i, **k: order.append("goal") or og(i, **k))
        monkeypatch.setattr(pe, "update_plan", lambda i, **k: order.append("plan") or op(i, **k))
        reflect_execution_started(g.id, p.id, goal_manager=gm, planning_engine=pe)
        reflect_execution_completed(g.id, p.id, goal_manager=gm, planning_engine=pe)
        assert order == ["goal", "plan", "plan", "goal"]

    def test_unknown_ids_raise_from_stores(self) -> None:
        gm, pe = GoalManager(), PlanningEngine()
        with pytest.raises(KeyError):
            reflect_execution_started("nope", "nope", goal_manager=gm, planning_engine=pe)

    def test_type_checks(self) -> None:
        with pytest.raises(TypeError):
            reflect_execution_started("g", "p", goal_manager=object(), planning_engine=PlanningEngine())  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            reflect_execution_completed("g", "p", goal_manager=GoalManager(), planning_engine=object())  # type: ignore[arg-type]

    def test_uses_only_public_update_apis(self) -> None:
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(_tree()) if isinstance(c, ast.Call)}
        assert calls == {"update_goal", "update_plan", "_check", "isinstance", "TypeError"}
        for n in ast.walk(_tree()):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler, ast.AsyncFunctionDef))

    def test_only_active_and_completed_used(self) -> None:
        used = {(n.value.id, n.attr) for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name) and n.value.id in {"GoalStatus", "PlanStatus"}}
        assert used == {("GoalStatus", "ACTIVE"), ("GoalStatus", "COMPLETED"),
                        ("PlanStatus", "ACTIVE"), ("PlanStatus", "COMPLETED")}

    def test_import_isolation(self) -> None:
        allowed_full = {"core.goal_manager", "core.planning_engine"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module == "__future__" or node.module in allowed_full, node.module
            elif isinstance(node, ast.Import):
                raise AssertionError(node.names[0].name)
        assert lifecycle_module.__all__ == ["reflect_execution_started", "reflect_execution_completed"]

    def test_no_core_module_imports_it_except_agent(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "lifecycle_reflection.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "lifecycle_reflection" not in f.read(), name


# ── status vocabularies unchanged ───────────────────────────────────────


class TestStatusVocabulariesUnchanged:
    def test_goal_status_values(self) -> None:
        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]

    def test_plan_status_values(self) -> None:
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]

    def test_run_status_values_and_transitions(self) -> None:
        from core.pipeline_run import ALLOWED_TRANSITIONS

        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert ALLOWED_TRANSITIONS == frozenset({
            (R.CREATED, R.RUNNING), (R.CREATED, R.CANCELLED), (R.RUNNING, R.COMPLETED),
            (R.RUNNING, R.FAILED), (R.RUNNING, R.CANCELLED),
        })

    def test_no_transition_machine_added_to_stores(self) -> None:
        for rel in ("goal_manager.py", "planning_engine.py"):
            with open(os.path.join(CORE_DIR, rel), encoding="utf-8") as f:
                assert "ALLOWED_TRANSITIONS" not in f.read(), rel


# ── Agent.execute_projection_with_lifecycle ─────────────────────────────


class TestSuccessPath:
    def test_signature_and_shape(self) -> None:
        params = inspect.signature(getattr(Agent, METHOD)).parameters
        assert list(params) == ["self", "goal", "project"]
        a = agent_with(StaticMockTool(name="fix the wifi", output="ok"))
        projection, run, decisions, results = a.execute_projection_with_lifecycle("fix the wifi")
        assert isinstance(projection, PlanProjection) and isinstance(run, PipelineRun)
        assert run.status is R.COMPLETED
        assert results == (ToolResult("fix the wifi", "ok"),)

    def test_projection_starts_draft(self) -> None:
        a = Agent()
        _, projection = a.project_request("fix the wifi")
        assert statuses(a, projection) == (G.DRAFT, P.DRAFT)

    def test_success_end_state(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        projection, run, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        assert run.status is R.COMPLETED
        assert statuses(a, projection) == (G.COMPLETED, P.COMPLETED)

    def test_success_ordering(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        t = Trace(a, monkeypatch)
        a.execute_projection_with_lifecycle("fix the wifi")
        assert t.events == [
            ("goal", G.ACTIVE), ("plan", P.ACTIVE),
            ("run", R.RUNNING),
            ("steps", (P.ACTIVE,)), ("steps", (P.COMPLETED,)),  # v8.26
            ("run", R.COMPLETED),
            ("plan", P.COMPLETED), ("goal", G.COMPLETED),
        ]

    def test_active_before_execution_observed_by_tool(self) -> None:
        a = Agent()
        seen: list[tuple] = []
        holder: dict = {}

        class Peek:
            name = "fix the wifi"
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                goal = a.goal_manager.list_goals()[0]
                plan = a.planning_engine.list_plans()[0]
                seen.append((goal.status, plan.status, a.pipeline_run_manager.list_runs()[0].status))
                return ToolResult(request.tool_name, "ok")

        a.tool_registry.register(Peek())
        a.execute_projection_with_lifecycle("fix the wifi")
        assert seen == [(G.ACTIVE, P.ACTIVE, R.RUNNING)]

    def test_writeback_after_lifecycle_completion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        seen: list[tuple] = []

        def remember(*x, **k):
            proj_goal = a.goal_manager.list_goals()[0]
            seen.append((proj_goal.status, a.planning_engine.list_plans()[0].status))
            return "id"

        monkeypatch.setattr(problem_solver, "remember", remember)
        a.execute_projection_with_lifecycle("fix the wifi")
        assert seen == [(G.COMPLETED, P.COMPLETED)]

    def test_writeback_intact(self, stub_remember: list) -> None:
        a = agent_with(StaticMockTool(name="step one"), StaticMockTool(name="step two"))
        _, run, _, _ = a.execute_projection_with_lifecycle("step one then step two")
        assert len(stub_remember) == 2
        assert a.reflection_engine.count() == 2
        recs = a.learning.get_all()
        assert len(recs) == 2 and all(r.metadata["run_id"] == run.id for r in recs)

    def test_same_decisions_and_results_as_v8_24(self) -> None:
        a, b = agent_with(StaticMockTool(name="fix the wifi")), agent_with(StaticMockTool(name="fix the wifi"))
        _, r1, d1, t1 = a.execute_projection_with_lifecycle("fix the wifi")
        _, r2, d2, t2 = b.execute_projection_with_writeback("fix the wifi")
        assert (d1, t1, r1.status) == (d2, t2, r2.status)

    def test_all_skipped_completes_and_reflects(self, stub_remember: list) -> None:
        a = Agent()
        projection, run, decisions, results = a.execute_projection_with_lifecycle("step one then step two")
        assert all(d.action == "skip" for d in decisions) and results == ()
        assert run.status is R.COMPLETED
        assert statuses(a, projection) == (G.COMPLETED, P.COMPLETED)
        assert stub_remember == []

    def test_repeated_goal_each_projection_completes_independently(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        p1, _, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        p2, _, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        assert statuses(a, p1) == statuses(a, p2) == (G.COMPLETED, P.COMPLETED)
        assert a.goal_manager.count() == 2


class TestFailurePath:
    def test_failure_leaves_active_and_reraises(self) -> None:
        exc = RuntimeError("boom")
        a = agent_with(Failing("fix the wifi", exc))
        with pytest.raises(RuntimeError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc
        projection_goal = a.goal_manager.list_goals()[0]
        plan = a.planning_engine.list_plans()[0]
        assert projection_goal.status is G.ACTIVE and plan.status is P.ACTIVE
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED

    def test_failure_ordering(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", RuntimeError("x")))
        t = Trace(a, monkeypatch)
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert t.events == [("goal", G.ACTIVE), ("plan", P.ACTIVE), ("run", R.RUNNING),
                            ("steps", (P.ACTIVE,)),  # v8.26: failing step stays ACTIVE
                            ("run", R.FAILED)]

    def test_failure_no_writeback(self, stub_remember: list) -> None:
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", ToolError("tool failed")))
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_projection_with_lifecycle("step one then step two")
        assert stub_remember == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_failure_not_converted_to_goal_failure(self) -> None:
        a = agent_with(Failing("fix the wifi", KeyError("k")))
        with pytest.raises(KeyError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert a.goal_manager.list_goals()[0].status not in (G.CANCELLED, G.PAUSED, G.COMPLETED)
        assert a.planning_engine.list_plans()[0].status not in (P.ARCHIVED, P.COMPLETED, P.READY)

    def test_failed_goal_can_be_retried_by_new_projection(self) -> None:
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi", RuntimeError("x")))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle("fix the wifi")
        a.tool_registry.unregister("fix the wifi")
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        p2, run2, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        assert run2.status is R.COMPLETED and statuses(a, p2) == (G.COMPLETED, P.COMPLETED)
        # The earlier attempt's goal/plan remain ACTIVE (separate projection).
        first_goal = a.goal_manager.list_goals()[0]
        assert first_goal.status is G.ACTIVE


class TestProjectionFailure:
    def test_blank_goal_no_lifecycle_records(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_lifecycle("   ")
        assert a.goal_manager.count() == 0 and a.planning_engine.count() == 0
        assert a.pipeline_run_manager.count() == 0

    def test_preflight_failure_no_reflection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.execution_planner import ExecutionPlanner
        from core.goal_manager import GoalManager as GM

        a = Agent(execution_planner=ExecutionPlanner(goal_manager=GM()))
        called: list[str] = []
        monkeypatch.setattr(agent_module, "reflect_execution_started", lambda *x, **k: called.append("started"))
        with pytest.raises(ValueError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert called == []
        assert a.goal_manager.count() == 0


class TestExistingPathsUnchanged:
    def test_v8_23_and_v8_24_do_not_reflect(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        p1, _, _, _ = a.execute_projection_with_run_status("fix the wifi")
        p2, _, _, _ = a.execute_projection_with_writeback("fix the wifi")
        assert statuses(a, p1) == statuses(a, p2) == (G.DRAFT, P.DRAFT)

    def test_v8_22_does_not_reflect(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        p, _, _ = a.execute_projection_with_tool_dispatch("fix the wifi")
        assert statuses(a, p) == (G.DRAFT, P.DRAFT)

    def test_legacy_and_tool_chains_unchanged(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: n == "fix the wifi")
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a = agent_with(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_learning("fix the wifi")
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(stub_remember) == 2
        assert a.goal_manager.count() == 0 and a.pipeline_run_manager.count() == 0

    def test_lifecycle_does_not_touch_skill_globals(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        agent_with(StaticMockTool(name="fix the wifi")).execute_projection_with_lifecycle("fix the wifi")
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001


class TestArchitecture:
    def test_method_is_thin_glue(self) -> None:
        node = _agent_method()
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"project_request", "reflect_execution_started", "_run_projected_pipeline",
                         "reflect_execution_completed", "_record_tool_outcomes"}
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert not attrs & {"update_goal", "update_plan", "update_run", "route", "_tool_router"}
        for n in ast.walk(node):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))

    def test_shared_helpers_used_by_v8_23_and_v8_24(self) -> None:
        for name, helper in (("execute_projection_with_run_status", "_run_projected_pipeline"),
                             ("execute_projection_with_writeback", "_record_tool_outcomes")):
            node = _agent_method(name)
            calls = {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in ast.walk(node) if isinstance(c, ast.Call)}
            assert helper in calls, name

    def test_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "GoalStatus" not in agent_module.__all__

    def test_no_todos(self) -> None:
        for path in (MODULE_PATH, AGENT_FILE):
            with open(path, encoding="utf-8") as f:
                src = f.read()
            assert "TODO" not in src and "FIXME" not in src, path
