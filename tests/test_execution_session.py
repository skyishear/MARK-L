"""Tests for core.execution_session (v3.5)."""

from __future__ import annotations

from core.execution_pipeline import ExecutionPipeline
from core.execution_session import ExecutionSession, create_session
from core.planner import PlanningEngine
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan


def _build_session(**kwargs):
    plan = PlanningEngine().plan("fix the wifi")
    orchestrator = build_orchestrator_for_plan(plan)
    pipeline = ExecutionPipeline(orchestrator, plan)
    return create_session(plan, orchestrator, pipeline, **kwargs), plan, orchestrator, pipeline


class TestCreateSession:
    def test_holds_the_supplied_objects(self) -> None:
        session, plan, orchestrator, pipeline = _build_session()
        assert isinstance(session, ExecutionSession)
        assert session.plan is plan
        assert session.orchestrator is orchestrator
        assert session.pipeline is pipeline

    def test_default_id_is_deterministic_from_plan_id(self) -> None:
        session, plan, _, _ = _build_session()
        assert session.id == f"session-{plan.id}"

    def test_explicit_session_id_is_used(self) -> None:
        session, _, _, _ = _build_session(session_id="custom-id")
        assert session.id == "custom-id"

    def test_metadata_defaults_to_empty(self) -> None:
        session, _, _, _ = _build_session()
        assert dict(session.metadata) == {}

    def test_metadata_is_read_only(self) -> None:
        session, _, _, _ = _build_session(metadata={"source": "test"})
        try:
            session.metadata["source"] = "changed"  # type: ignore[index]
            raised = False
        except TypeError:
            raised = True
        assert raised

    def test_session_is_immutable(self) -> None:
        session, _, _, _ = _build_session()
        try:
            session.id = "changed"  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised

    def test_two_sessions_for_same_plan_share_default_id(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator1 = build_orchestrator_for_plan(plan)
        orchestrator2 = build_orchestrator_for_plan(plan)
        s1 = create_session(plan, orchestrator1, ExecutionPipeline(orchestrator1, plan))
        s2 = create_session(plan, orchestrator2, ExecutionPipeline(orchestrator2, plan))
        assert s1.id == s2.id
