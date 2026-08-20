"""MARK L v3.5 — ExecutionSession: the current execution lifecycle grouping.

``ExecutionSession`` is a plain, immutable container binding together
an already-built ``ExecutionPlan``, ``ExecutionOrchestrator``, and
``ExecutionPipeline`` (all supplied by the caller — none is
constructed here), plus read-only session metadata. It performs no
execution, no state mutation, and no I/O of its own; it only groups
three existing objects so a caller has one handle to pass around.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from core.execution_orchestrator import ExecutionOrchestrator
from core.execution_pipeline import ExecutionPipeline
from core.planner import ExecutionPlan

__all__ = ["ExecutionSession", "create_session"]


@dataclass(frozen=True, slots=True)
class ExecutionSession:
    """An immutable grouping of one plan's live execution objects.

    ``orchestrator`` and ``pipeline`` are references to the live
    objects the caller constructed and continues to drive — this
    session does not copy or wrap their behavior, and never calls a
    state-changing method on either. ``metadata`` is stored as a
    read-only mapping (copied and wrapped on construction), and
    ``id``/``created_at`` are set once and never change.
    """

    id: str
    plan: ExecutionPlan
    orchestrator: ExecutionOrchestrator
    pipeline: ExecutionPipeline
    metadata: Mapping[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


def create_session(
    plan: ExecutionPlan,
    orchestrator: ExecutionOrchestrator,
    pipeline: ExecutionPipeline,
    *,
    session_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ExecutionSession:
    """Build an ``ExecutionSession`` from already-constructed objects.

    ``plan``, ``orchestrator``, and ``pipeline`` must already exist —
    this function builds none of them. ``session_id`` defaults to a
    deterministic id derived from ``plan.id`` (``f"session-{plan.id}"``)
    when omitted, so the same plan always yields the same default
    session id; ``created_at`` reflects actual creation time and is
    not deterministic (consistent with ``core.planner``'s own
    ``created_at`` fields).
    """
    return ExecutionSession(
        id=session_id if session_id is not None else f"session-{plan.id}",
        plan=plan,
        orchestrator=orchestrator,
        pipeline=pipeline,
        metadata=metadata or {},
        created_at=datetime.now(timezone.utc),
    )
