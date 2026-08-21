"""MARK L v3.9 — ExecutionCoordinator: coordination-only over an ExecutionSession.

Reads an already-built ``ExecutionSession`` (constructor-injected, never
constructed here) and reports ready work + progress by delegating to
existing, unmodified modules: ``session.pipeline.ready_descriptors()``
and ``ExecutionProgress.from_orchestrator(session.orchestrator)``. No
task execution, no state mutation, no ProblemSolver/Skill/Memory/AI
calls, no threads, no async, no file I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.execution_pipeline import PipelineExecutionDescriptor
from core.execution_progress import ExecutionProgress
from core.execution_session import ExecutionSession

__all__ = ["CoordinationSnapshot", "ExecutionCoordinator"]


@dataclass(frozen=True, slots=True)
class CoordinationSnapshot:
    """Immutable, read-only view of one session's current ready work."""

    session_id: str
    plan_id: str
    ready_task_ids: tuple[str, ...]
    ready_descriptors: tuple[PipelineExecutionDescriptor, ...]
    progress: ExecutionProgress


class ExecutionCoordinator:
    """Coordinates an existing ExecutionSession. Reads only; never executes."""

    def __init__(self, session: ExecutionSession) -> None:
        self._session = session

    @property
    def session(self) -> ExecutionSession:
        """The injected ExecutionSession."""
        return self._session

    def coordinate(self) -> CoordinationSnapshot:
        """Build a deterministic ``CoordinationSnapshot`` for the current session state.

        Delegates entirely to existing modules: ready task ids/
        descriptors come from ``session.pipeline.ready_descriptors()``
        (no reimplementation of readiness logic), progress from
        ``ExecutionProgress.from_orchestrator(session.orchestrator)``.
        Read-only: no ``mark_*`` call, no execution.
        """
        descriptors = self._session.pipeline.ready_descriptors()
        return CoordinationSnapshot(
            session_id=self._session.id,
            plan_id=self._session.plan.id,
            ready_task_ids=tuple(d.task_id for d in descriptors),
            ready_descriptors=descriptors,
            progress=ExecutionProgress.from_orchestrator(self._session.orchestrator),
        )
