"""MARK L v3.5 — ExecutionResult: immutable completed-execution summary.

``ExecutionResult`` is a plain, immutable snapshot summarizing an
execution session — it contains no execution logic. It is built from
data that already exists: an ``ExecutionOrchestrator.snapshot()`` (or
an ``ExecutionSession`` wrapping one) and the ``ExecutionProgress``
tally computed from it. Building a result never calls a state-changing
method on the orchestrator and never runs anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from core.execution_orchestrator import TaskExecutionRecord
from core.execution_progress import ExecutionProgress
from core.execution_session import ExecutionSession

__all__ = ["ExecutionResult", "build_result", "build_result_from_session"]


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """An immutable summary of one session's execution state.

    ``success`` is true only when every task reached a terminal state
    and none ``FAILED`` (``PENDING``/``RUNNING`` tasks or any
    ``FAILED`` task make it false). ``task_states`` is the exact
    snapshot the result was built from, preserved for inspection.
    """

    session_id: str
    plan_id: str
    progress: ExecutionProgress
    task_states: tuple[TaskExecutionRecord, ...]
    success: bool
    created_at: datetime


def build_result(
    session_id: str,
    plan_id: str,
    snapshot: Sequence[TaskExecutionRecord],
    *,
    progress: ExecutionProgress | None = None,
) -> ExecutionResult:
    """Build an ``ExecutionResult`` from a session id, plan id, and snapshot.

    ``progress`` is computed from ``snapshot`` via
    ``ExecutionProgress.from_snapshot`` when not supplied. Pure data
    assembly only — no execution, no state mutation, no I/O.
    """
    if progress is None:
        progress = ExecutionProgress.from_snapshot(snapshot)

    success = (
        progress.pending == 0
        and progress.running == 0
        and progress.failed == 0
        and progress.total > 0
    )

    return ExecutionResult(
        session_id=session_id,
        plan_id=plan_id,
        progress=progress,
        task_states=tuple(snapshot),
        success=success,
        created_at=datetime.now(timezone.utc),
    )


def build_result_from_session(session: ExecutionSession) -> ExecutionResult:
    """Build an ``ExecutionResult`` for ``session``'s current state.

    Reads ``session.orchestrator.snapshot()`` only (never a ``mark_*``
    method), then delegates to ``build_result``.
    """
    return build_result(session.id, session.plan.id, session.orchestrator.snapshot())
