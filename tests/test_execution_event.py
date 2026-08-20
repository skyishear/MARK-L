"""Tests for core.execution_event (v3.5)."""

from __future__ import annotations

from core.execution_event import (
    ExecutionEvent,
    ExecutionEventType,
    session_created_event,
    task_completed_event,
    task_failed_event,
    task_ready_event,
    task_skipped_event,
)


class TestEventConstructors:
    def test_session_created_event_has_no_task_id(self) -> None:
        event = session_created_event("session-1")
        assert isinstance(event, ExecutionEvent)
        assert event.event_type == ExecutionEventType.SESSION_CREATED
        assert event.session_id == "session-1"
        assert event.task_id is None

    def test_task_ready_event_shape(self) -> None:
        event = task_ready_event("session-1", "task-1")
        assert event.event_type == ExecutionEventType.TASK_READY
        assert event.task_id == "task-1"

    def test_task_completed_event_shape(self) -> None:
        event = task_completed_event("session-1", "task-1")
        assert event.event_type == ExecutionEventType.TASK_COMPLETED

    def test_task_failed_event_shape(self) -> None:
        event = task_failed_event("session-1", "task-1")
        assert event.event_type == ExecutionEventType.TASK_FAILED

    def test_task_skipped_event_shape(self) -> None:
        event = task_skipped_event("session-1", "task-1")
        assert event.event_type == ExecutionEventType.TASK_SKIPPED

    def test_metadata_defaults_empty_and_is_read_only(self) -> None:
        event = task_ready_event("session-1", "task-1", metadata={"note": "x"})
        assert dict(event.metadata) == {"note": "x"}
        try:
            event.metadata["note"] = "changed"  # type: ignore[index]
            raised = False
        except TypeError:
            raised = True
        assert raised

    def test_event_is_immutable(self) -> None:
        event = session_created_event("session-1")
        try:
            event.session_id = "changed"  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised
