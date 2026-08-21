"""Tests for core.execution_coordinator (v3.9)."""

from __future__ import annotations

from core.execution_coordinator import CoordinationSnapshot, ExecutionCoordinator
from core.execution_pipeline import ExecutionPipeline
from core.execution_session import create_session
from core.planner import PlanningEngine
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan


def _session_for(goal: str):
    plan = PlanningEngine().plan(goal)
    orchestrator = build_orchestrator_for_plan(plan)
    pipeline = ExecutionPipeline(orchestrator, plan)
    return create_session(plan, orchestrator, pipeline), plan, orchestrator


class TestCoordinate:
    def test_returns_snapshot_with_ready_first_task(self) -> None:
        session, plan, _ = _session_for("step one then step two")
        snapshot = ExecutionCoordinator(session).coordinate()
        assert isinstance(snapshot, CoordinationSnapshot)
        assert snapshot.ready_task_ids == (plan.tasks[0].id,)
        assert snapshot.session_id == session.id
        assert snapshot.plan_id == plan.id

    def test_matches_pipeline_ready_descriptors(self) -> None:
        session, _, _ = _session_for("fix the wifi")
        snapshot = ExecutionCoordinator(session).coordinate()
        assert snapshot.ready_descriptors == session.pipeline.ready_descriptors()

    def test_progress_reflects_orchestrator_state(self) -> None:
        session, plan, orchestrator = _session_for("fix the wifi")
        snapshot = ExecutionCoordinator(session).coordinate()
        assert snapshot.progress.total == 1
        assert snapshot.progress.pending == 1

    def test_no_state_mutation(self) -> None:
        session, _, orchestrator = _session_for("fix the wifi")
        before = orchestrator.snapshot()
        ExecutionCoordinator(session).coordinate()
        assert orchestrator.snapshot() == before

    def test_deterministic_across_calls(self) -> None:
        session, _, _ = _session_for("step one then step two")
        coordinator = ExecutionCoordinator(session)
        assert coordinator.coordinate() == coordinator.coordinate()

    def test_session_property_returns_injected_session(self) -> None:
        session, _, _ = _session_for("fix the wifi")
        assert ExecutionCoordinator(session).session is session
