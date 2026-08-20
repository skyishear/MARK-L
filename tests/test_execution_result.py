"""Tests for core.execution_result (v3.5)."""

from __future__ import annotations

from core.execution_pipeline import ExecutionPipeline
from core.execution_progress import ExecutionProgress
from core.execution_result import ExecutionResult, build_result, build_result_from_session
from core.execution_session import create_session
from core.planner import PlanningEngine
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan


class TestBuildResult:
    def test_success_false_while_tasks_pending(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        result = build_result(plan.id, plan.id, orchestrator.snapshot())
        assert isinstance(result, ExecutionResult)
        assert result.success is False

    def test_success_true_when_all_completed(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        orchestrator.mark_running(plan.tasks[0].id)
        orchestrator.mark_completed(plan.tasks[0].id)
        result = build_result(plan.id, plan.id, orchestrator.snapshot())
        assert result.success is True

    def test_success_false_when_any_task_failed(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        orchestrator.mark_running(plan.tasks[0].id)
        orchestrator.mark_failed(plan.tasks[0].id)
        result = build_result(plan.id, plan.id, orchestrator.snapshot())
        assert result.success is False

    def test_progress_matches_snapshot(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        result = build_result(plan.id, plan.id, orchestrator.snapshot())
        assert result.progress == ExecutionProgress.from_orchestrator(orchestrator)

    def test_task_states_preserved(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        snapshot = orchestrator.snapshot()
        result = build_result(plan.id, plan.id, snapshot)
        assert result.task_states == snapshot

    def test_result_is_immutable(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        result = build_result(plan.id, plan.id, orchestrator.snapshot())
        try:
            result.success = True  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised


class TestBuildResultFromSession:
    def test_matches_build_result_from_snapshot(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        session = create_session(plan, orchestrator, pipeline)
        result = build_result_from_session(session)
        expected = build_result(session.id, plan.id, orchestrator.snapshot())
        # created_at is wall-clock time (documented non-deterministic),
        # so compare every other field explicitly instead.
        assert result.session_id == expected.session_id
        assert result.plan_id == expected.plan_id
        assert result.progress == expected.progress
        assert result.task_states == expected.task_states
        assert result.success == expected.success

    def test_does_not_mutate_orchestrator_state(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        session = create_session(plan, orchestrator, pipeline)
        before = orchestrator.snapshot()
        build_result_from_session(session)
        assert orchestrator.snapshot() == before
