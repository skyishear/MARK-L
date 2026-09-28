"""Tests for v8.26 Step Lifecycle Reflection
(``core.step_lifecycle`` and the ``reflect_steps`` path of
``Agent.execute_projection_with_lifecycle``).

Contract (``ROADMAP.md``, resolved before v8.26): projected DRAFT; reached
dispatched stage ACTIVE; success COMPLETED; reached skipped stage ARCHIVED
directly from DRAFT (4a); failing step stays ACTIVE; unreached steps after a
failure stay DRAFT even when unregistered (6a); COMPLETED never downgraded
(invariant only); lifecycle path only (2a); existing PlanStatus vocabulary.
"""

from __future__ import annotations

import ast
import inspect
import os
from datetime import datetime, timezone

import pytest

import core.agent as agent_module
import core.step_lifecycle as step_module
from core import problem_solver
from core.agent import Agent
from core.goal_manager import GoalStatus
from core.pipeline_run import PipelineRunStatus
from core.planner import ExecutionPlan, Goal, InvalidGoalError, Task
from core.planning_engine import PlanningEngine, PlanStatus, Step
from core.step_lifecycle import reflect_step_completed, reflect_step_reached, reflect_step_skipped
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "step_lifecycle.py")
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")
G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
THREE = "step one then step two then step three"


def _tree(path: str = MODULE_PATH) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())


def _agent_method(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree(AGENT_FILE)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise self.exc


@pytest.fixture(autouse=True)
def stub_remember(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    writes: list[tuple] = []
    monkeypatch.setattr(problem_solver, "remember", lambda *a, **k: writes.append((a, k)) or "id")
    return writes


def agent_with(*tools: object) -> Agent:
    a = Agent()
    for t in tools:
        a.tool_registry.register(t)
    return a


def step_statuses(a: Agent, plan_id: str) -> list[PlanStatus]:
    return [s.status for s in a.planning_engine.get_plan(plan_id).steps]


def only_plan(a: Agent):
    (plan,) = a.planning_engine.list_plans()
    return plan


class StepWrites:
    """Records every whole-tuple step replacement as a status tuple."""

    def __init__(self, a: Agent, monkeypatch: pytest.MonkeyPatch) -> None:
        self.writes: list[tuple[PlanStatus, ...]] = []
        original = a.planning_engine.update_plan

        def spy(plan_id, **k):
            if "steps" in k:
                self.writes.append(tuple(s.status for s in k["steps"]))
            return original(plan_id, **k)

        monkeypatch.setattr(a.planning_engine, "update_plan", spy)


def reversed_plan() -> ExecutionPlan:
    """Legacy plan whose execution order (t2, t1) is the reverse of its task
    order (t1, t2), so ``Step.index`` and stage order disagree."""
    now = datetime.now(timezone.utc)
    return ExecutionPlan(
        id="legacy-plan",
        goal=Goal(id="legacy-goal", description="reversed", created_at=now),
        tasks=(
            Task(id="t1", description="do t1", depends_on=("t2",), metadata={}),
            Task(id="t2", description="do t2", depends_on=(), metadata={}),
        ),
        created_at=now,
    )


def engine_with_steps(n: int = 3) -> tuple[PlanningEngine, str]:
    e = PlanningEngine()
    steps = [Step(id=f"s{i}", index=i, title=f"t{i}", description=f"d{i}", status=P.DRAFT) for i in range(n)]
    return e, e.create_plan(goal="g", steps=steps).id


# ── leaf module ─────────────────────────────────────────────────────────


class TestLeafFunctions:
    @pytest.mark.parametrize("fn, expected", [
        (reflect_step_reached, P.ACTIVE),
        (reflect_step_completed, P.COMPLETED),
        (reflect_step_skipped, P.ARCHIVED),
    ])
    def test_sets_only_the_targeted_step(self, fn, expected: PlanStatus) -> None:
        e, pid = engine_with_steps()
        before = e.get_plan(pid)
        fn(pid, "s1", planning_engine=e)
        after = e.get_plan(pid)
        assert [s.status for s in after.steps] == [P.DRAFT, expected, P.DRAFT]
        assert after.steps[0] is before.steps[0] and after.steps[2] is before.steps[2]
        s = after.steps[1]
        assert (s.id, s.index, s.title, s.description) == ("s1", 1, "t1", "d1")

    def test_plan_fields_preserved(self) -> None:
        e, pid = engine_with_steps()
        e.update_plan(pid, status=P.ACTIVE)
        before = e.get_plan(pid)
        reflect_step_completed(pid, "s0", planning_engine=e)
        after = e.get_plan(pid)
        assert (after.id, after.goal, after.description, after.status, after.created_at) == (
            before.id, before.goal, before.description, P.ACTIVE, before.created_at)

    def test_unknown_plan_and_step_raise_key_error(self) -> None:
        e, pid = engine_with_steps()
        with pytest.raises(KeyError):
            reflect_step_reached("missing", "s0", planning_engine=e)
        with pytest.raises(KeyError):
            reflect_step_reached(pid, "missing", planning_engine=e)
        assert [s.status for s in e.get_plan(pid).steps] == [P.DRAFT] * 3

    def test_type_check(self) -> None:
        with pytest.raises(TypeError):
            reflect_step_reached("p", "s", planning_engine=object())  # type: ignore[arg-type]

    def test_same_step_id_in_other_plan_untouched(self) -> None:
        e, p1 = engine_with_steps()
        p2 = e.create_plan(goal="g2", steps=[Step(id="s0", index=0, title="t", description="d", status=P.DRAFT)]).id
        reflect_step_completed(p1, "s0", planning_engine=e)
        assert e.get_plan(p2).steps[0].status is P.DRAFT


# ── contract rules on the lifecycle path ────────────────────────────────


class TestContractRules:
    def test_rule1_projected_steps_draft(self) -> None:
        a = Agent()
        _, projection = a.project_request(THREE)
        assert step_statuses(a, projection.plan_id) == [P.DRAFT] * 3

    def test_rule2_reached_step_active_while_executing(self) -> None:
        a = Agent()
        seen: list[list[PlanStatus]] = []

        class Peek:
            description = "d"

            def __init__(self, name: str) -> None:
                self.name = name

            def invoke(self, request: ToolRequest) -> ToolResult:
                seen.append([s.status for s in only_plan(a).steps])
                return ToolResult(request.tool_name, "ok")

        for n in ("step one", "step two", "step three"):
            a.tool_registry.register(Peek(n))
        a.execute_projection_with_lifecycle(THREE)
        assert seen == [
            [P.ACTIVE, P.DRAFT, P.DRAFT],
            [P.COMPLETED, P.ACTIVE, P.DRAFT],
            [P.COMPLETED, P.COMPLETED, P.ACTIVE],
        ]

    def test_rule3_success_all_completed(self) -> None:
        a = agent_with(*(StaticMockTool(name=n) for n in ("step one", "step two", "step three")))
        projection, run, _, _ = a.execute_projection_with_lifecycle(THREE)
        assert step_statuses(a, projection.plan_id) == [P.COMPLETED] * 3
        assert run.status is R.COMPLETED

    def test_rule4_skipped_archived(self) -> None:
        a = agent_with(StaticMockTool(name="step one"), StaticMockTool(name="step three"))
        projection, _, decisions, _ = a.execute_projection_with_lifecycle(THREE)
        assert [d.action for d in decisions][1] == "skip"
        assert step_statuses(a, projection.plan_id) == [P.COMPLETED, P.ARCHIVED, P.COMPLETED]

    def test_rule4a_skipped_never_passes_through_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        w = StepWrites(a, monkeypatch)
        a.execute_projection_with_lifecycle("step one then step two")
        assert w.writes == [
            (P.ACTIVE, P.DRAFT),
            (P.COMPLETED, P.DRAFT),
            (P.COMPLETED, P.ARCHIVED),  # DRAFT -> ARCHIVED directly
        ]

    def test_all_skipped_plan_completed_with_all_steps_archived(self) -> None:
        a = Agent()
        projection, run, _, results = a.execute_projection_with_lifecycle(THREE)
        assert results == () and run.status is R.COMPLETED
        assert only_plan(a).status is P.COMPLETED
        assert a.goal_manager.get_goal(projection.goal_id).status is G.COMPLETED
        assert step_statuses(a, projection.plan_id) == [P.ARCHIVED] * 3

    def test_rule5_failing_step_stays_active(self) -> None:
        exc = ToolError("tool failed")
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", exc),
                       StaticMockTool(name="step three"))
        with pytest.raises(ToolError) as info:
            a.execute_projection_with_lifecycle(THREE)
        assert info.value is exc
        assert [s.status for s in only_plan(a).steps] == [P.COMPLETED, P.ACTIVE, P.DRAFT]
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED
        assert only_plan(a).status is P.ACTIVE
        assert a.goal_manager.list_goals()[0].status is G.ACTIVE

    def test_rule6a_unreached_unregistered_stays_draft(self) -> None:
        # step three's tool is unregistered, but the stage is never reached.
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", RuntimeError("x")))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle(THREE)
        assert [s.status for s in only_plan(a).steps] == [P.COMPLETED, P.ACTIVE, P.DRAFT]

    def test_skip_before_failure_archived(self) -> None:
        a = agent_with(Failing("step two", RuntimeError("x")), StaticMockTool(name="step three"))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle(THREE)
        assert [s.status for s in only_plan(a).steps] == [P.ARCHIVED, P.ACTIVE, P.DRAFT]

    def test_first_stage_failure_rest_draft(self) -> None:
        a = agent_with(Failing("step one", KeyError("k")), StaticMockTool(name="step two"))
        with pytest.raises(KeyError):
            a.execute_projection_with_lifecycle(THREE)
        assert [s.status for s in only_plan(a).steps] == [P.ACTIVE, P.DRAFT, P.DRAFT]

    def test_rule7_completed_never_downgraded_by_reexecution(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        p1, _, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        a.tool_registry.unregister("fix the wifi")
        a.tool_registry.register(Failing("fix the wifi", RuntimeError("x")))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle("fix the wifi")
        plans = a.planning_engine.list_plans()
        assert len(plans) == 2 and plans[0].id == p1.plan_id
        assert plans[0].steps[0].id == plans[1].steps[0].id  # same legacy task id
        assert step_statuses(a, p1.plan_id) == [P.COMPLETED]
        assert [s.status for s in plans[1].steps] == [P.ACTIVE]

    def test_each_step_written_once_per_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="step one"), StaticMockTool(name="step two"))
        w = StepWrites(a, monkeypatch)
        a.execute_projection_with_lifecycle("step one then step two")
        assert w.writes == [
            (P.ACTIVE, P.DRAFT), (P.COMPLETED, P.DRAFT),
            (P.COMPLETED, P.ACTIVE), (P.COMPLETED, P.COMPLETED),
        ]


class TestTargeting:
    def test_steps_targeted_by_id_not_position(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="do t2"), Failing("do t1", RuntimeError("x")))
        monkeypatch.setattr(a.planning, "plan", lambda goal: reversed_plan())
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle("reversed")
        steps = only_plan(a).steps
        # Stage order is t2 then t1; Step.index order is t1 then t2.
        assert [(s.id, s.status) for s in steps] == [("t1", P.ACTIVE), ("t2", P.COMPLETED)]

    def test_decision_task_ids_are_step_ids(self) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        projection, _, decisions, _ = a.execute_projection_with_lifecycle(THREE)
        assert sorted(d.task_id for d in decisions) == sorted(projection.step_ids)


class TestSemanticsPreserved:
    def test_success_goal_plan_run_end_state(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        projection, run, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        assert run.status is R.COMPLETED
        assert a.goal_manager.get_goal(projection.goal_id).status is G.COMPLETED
        assert a.planning_engine.get_plan(projection.plan_id).status is P.COMPLETED

    def test_writeback_same_as_v8_24(self, stub_remember: list) -> None:
        tools = ("step one", "step two")
        a = agent_with(*(StaticMockTool(name=n) for n in tools))
        b = agent_with(*(StaticMockTool(name=n) for n in tools))
        _, _, d1, r1 = a.execute_projection_with_lifecycle(THREE)
        n = len(stub_remember)
        _, _, d2, r2 = b.execute_projection_with_writeback(THREE)
        assert (d1, r1) == (d2, r2)
        assert n == len(stub_remember) - n == 2
        assert a.reflection_engine.count() == b.reflection_engine.count() == 2

    def test_step_store_error_fails_run_and_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = RuntimeError("store down")

        def boom(*a, **k):
            raise exc

        monkeypatch.setattr(agent_module, "reflect_step_reached", boom)
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(RuntimeError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED

    def test_projection_failure_no_step_writes(self) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_lifecycle("   ")
        assert a.planning_engine.count() == 0


class TestOtherPathsLeaveStepsDraft:
    """Clarification 2a: v8.22 / v8.23 / v8.24 never touch Step.status."""

    def test_v8_22(self) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        p, _, _ = a.execute_projection_with_tool_dispatch(THREE)
        assert step_statuses(a, p.plan_id) == [P.DRAFT] * 3

    def test_v8_23(self) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        p, _, _, _ = a.execute_projection_with_run_status(THREE)
        assert step_statuses(a, p.plan_id) == [P.DRAFT] * 3

    def test_v8_24(self) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        p, _, _, _ = a.execute_projection_with_writeback(THREE)
        assert step_statuses(a, p.plan_id) == [P.DRAFT] * 3

    def test_v8_23_failure(self) -> None:
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", RuntimeError("x")))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_run_status(THREE)
        assert [s.status for s in only_plan(a).steps] == [P.DRAFT] * 3

    def test_no_step_writes_outside_lifecycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="step one"))
        w = StepWrites(a, monkeypatch)
        a.execute_projection_with_tool_dispatch(THREE)
        a.execute_projection_with_run_status(THREE)
        a.execute_projection_with_writeback(THREE)
        assert w.writes == []


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_import_isolation(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom):
                assert node.module in {"__future__", "core.planning_engine"}, node.module
            elif isinstance(node, ast.Import):
                raise AssertionError(node.names[0].name)
        assert step_module.__all__ == ["reflect_step_reached", "reflect_step_completed", "reflect_step_skipped"]

    def test_only_contract_statuses_used(self) -> None:
        used = {n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Name) and n.value.id == "PlanStatus"}
        assert used == {"ACTIVE", "COMPLETED", "ARCHIVED"}

    def test_no_new_status_type_or_legacy_vocabulary(self) -> None:
        tree = _tree()
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
                  | {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names})
        for forbidden in ("TaskState", "FAILED", "SKIPPED", "Enum", "ALLOWED_TRANSITIONS",
                          "GoalStatus", "PipelineRunStatus"):
            assert forbidden not in idents, forbidden
        assert not [n for n in ast.walk(_tree()) if isinstance(n, ast.ClassDef)]

    def test_no_exception_handling(self) -> None:
        for n in ast.walk(_tree()):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))

    def test_uses_only_public_store_apis(self) -> None:
        attrs = {c.func.attr for c in ast.walk(_tree())
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert attrs == {"get_plan", "update_plan"}

    def test_vocabularies_and_step_model_unchanged(self) -> None:
        import dataclasses

        import core.planning_engine as pe
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [f.name for f in dataclasses.fields(Step)] == ["id", "index", "title", "description", "status"]
        assert "ALLOWED_TRANSITIONS" not in inspect.getsource(pe)
        assert not hasattr(pe, "StepStatus")

    def test_no_core_module_imports_it_except_agent(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "step_lifecycle.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "step_lifecycle" not in f.read(), name

    def test_reflect_steps_off_by_default(self) -> None:
        sig = inspect.signature(Agent._run_projected_pipeline)
        assert sig.parameters["reflect_steps"].default is False

    def test_only_lifecycle_method_enables_step_reflection(self) -> None:
        enabling = set()
        for fn in ast.walk(_tree(AGENT_FILE)):
            if isinstance(fn, ast.FunctionDef):
                for c in ast.walk(fn):
                    if (isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "_run_projected_pipeline"
                            and any(k.arg == "reflect_steps" for k in c.keywords)):
                        enabling.add(fn.name)
        # v8.32: resume_failed_run continues a lifecycle attempt (same step semantics).
        assert enabling == {"execute_projection_with_lifecycle", "resume_failed_run"}

    def test_failure_handler_writes_no_step(self) -> None:
        helper = _agent_method("_run_projected_pipeline")
        (handler,) = [n for n in ast.walk(helper) if isinstance(n, ast.ExceptHandler)]
        names = {getattr(c.func, "attr", getattr(c.func, "id", None))
                 for c in ast.walk(handler) if isinstance(c, ast.Call)}
        assert not {n for n in names if n and n.startswith("reflect_step")}

    def test_agent_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
