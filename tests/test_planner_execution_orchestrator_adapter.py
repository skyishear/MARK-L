"""Tests for core.planner_execution_orchestrator_adapter (v3.3)."""

from __future__ import annotations

from core.execution_orchestrator import ExecutionOrchestrator, TaskState
from core.planner import PlanningEngine
from core.planner_execution_orchestrator_adapter import (
    build_orchestrator_for_plan,
    plan_to_orchestrated_tasks,
)


class TestPlanToOrchestratedTasks:
    def test_matches_plan_execution_order(self) -> None:
        plan = PlanningEngine().plan("open the file then edit it then save it")
        tasks = plan_to_orchestrated_tasks(plan)
        assert [t.task_id for t in tasks] == [t.id for t in plan.execution_order()]

    def test_dependencies_are_preserved(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        tasks = plan_to_orchestrated_tasks(plan)
        assert tasks[0].depends_on == ()
        assert tasks[1].depends_on == (tasks[0].task_id,)


class TestBuildOrchestratorForPlan:
    def test_returns_orchestrator_with_all_tasks_pending(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        orch = build_orchestrator_for_plan(plan)
        assert isinstance(orch, ExecutionOrchestrator)
        assert all(orch.get_state(tid) == TaskState.PENDING for tid in orch.order)

    def test_next_ready_task_starts_at_first_step(self) -> None:
        plan = PlanningEngine().plan("step one then step two then step three")
        orch = build_orchestrator_for_plan(plan)
        first_task_id = plan.tasks[0].id
        assert orch.next_ready_task() == first_task_id

    def test_no_task_is_executed(self) -> None:
        plan = PlanningEngine().plan("delete the system32 folder")
        orch = build_orchestrator_for_plan(plan)
        # Building the orchestrator must not run anything; every task
        # remains PENDING until the caller explicitly transitions it.
        assert all(orch.get_state(tid) == TaskState.PENDING for tid in orch.order)
