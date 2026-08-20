"""MARK L v3.5 — ExecutionEvent: immutable lifecycle event records.

Plain, immutable event objects for execution lifecycle moments
(session created, task became ready, task completed, task failed,
task skipped). This module is deliberately just data + constructor
helpers — there is no event bus, no dispatcher, no subscriber list,
and nothing here fires automatically. A caller who observes a
lifecycle moment elsewhere may build a matching event record to keep,
log, or pass along; this module never decides when that moment
happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

__all__ = [
    "ExecutionEvent",
    "ExecutionEventType",
    "session_created_event",
    "task_completed_event",
    "task_failed_event",
    "task_ready_event",
    "task_skipped_event",
]


class ExecutionEventType(str, Enum):
    """The kind of lifecycle moment an ``ExecutionEvent`` records."""

    SESSION_CREATED = "session_created"
    TASK_READY = "task_ready"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_SKIPPED = "task_skipped"


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """An immutable record of a single execution lifecycle moment.

    ``task_id`` is ``None`` for session-level events (e.g.
    ``SESSION_CREATED``) and set for task-level events. ``metadata``
    is stored as a read-only mapping. ``occurred_at`` reflects actual
    creation time and is not deterministic.
    """

    event_type: ExecutionEventType
    session_id: str
    task_id: str | None
    metadata: Mapping[str, Any]
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def _build(
    event_type: ExecutionEventType,
    session_id: str,
    task_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        event_type=event_type,
        session_id=session_id,
        task_id=task_id,
        metadata=metadata or {},
        occurred_at=datetime.now(timezone.utc),
    )


def session_created_event(
    session_id: str, *, metadata: Mapping[str, Any] | None = None
) -> ExecutionEvent:
    """Build a ``SESSION_CREATED`` event."""
    return _build(ExecutionEventType.SESSION_CREATED, session_id, metadata=metadata)


def task_ready_event(
    session_id: str, task_id: str, *, metadata: Mapping[str, Any] | None = None
) -> ExecutionEvent:
    """Build a ``TASK_READY`` event."""
    return _build(ExecutionEventType.TASK_READY, session_id, task_id, metadata)


def task_completed_event(
    session_id: str, task_id: str, *, metadata: Mapping[str, Any] | None = None
) -> ExecutionEvent:
    """Build a ``TASK_COMPLETED`` event."""
    return _build(ExecutionEventType.TASK_COMPLETED, session_id, task_id, metadata)


def task_failed_event(
    session_id: str, task_id: str, *, metadata: Mapping[str, Any] | None = None
) -> ExecutionEvent:
    """Build a ``TASK_FAILED`` event."""
    return _build(ExecutionEventType.TASK_FAILED, session_id, task_id, metadata)


def task_skipped_event(
    session_id: str, task_id: str, *, metadata: Mapping[str, Any] | None = None
) -> ExecutionEvent:
    """Build a ``TASK_SKIPPED`` event."""
    return _build(ExecutionEventType.TASK_SKIPPED, session_id, task_id, metadata)
