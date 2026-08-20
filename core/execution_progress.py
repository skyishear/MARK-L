"""MARK L v3.5 — ExecutionProgress: pure execution progress calculations.

``ExecutionProgress`` is an immutable tally of task states. It performs
no execution, no state mutation, and no I/O — it only counts an
already-taken ``ExecutionOrchestrator.snapshot()`` (or any sequence of
``TaskExecutionRecord``) and reports totals. Given the same input,
``from_snapshot`` always returns the same result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.execution_orchestrator import (
    ExecutionOrchestrator,
    TaskExecutionRecord,
    TaskState,
)

__all__ = ["ExecutionProgress"]


@dataclass(frozen=True, slots=True)
class ExecutionProgress:
    """An immutable, point-in-time tally of task execution states."""

    total: int
    pending: int
    running: int
    completed: int
    failed: int
    skipped: int

    @property
    def percentage_complete(self) -> float:
        """Percentage of tasks that reached ``COMPLETED`` (0.0 if there are none).

        Deliberately counts only ``COMPLETED`` — ``FAILED`` and
        ``SKIPPED`` tasks are finished but not *complete*.
        """
        if self.total == 0:
            return 0.0
        return (self.completed / self.total) * 100.0

    @classmethod
    def from_snapshot(cls, snapshot: Sequence[TaskExecutionRecord]) -> "ExecutionProgress":
        """Build progress from a sequence of ``TaskExecutionRecord``.

        Pure calculation — reads ``snapshot`` only, mutates nothing.
        """
        pending = running = completed = failed = skipped = 0
        for record in snapshot:
            if record.state is TaskState.PENDING:
                pending += 1
            elif record.state is TaskState.RUNNING:
                running += 1
            elif record.state is TaskState.COMPLETED:
                completed += 1
            elif record.state is TaskState.FAILED:
                failed += 1
            elif record.state is TaskState.SKIPPED:
                skipped += 1
        return cls(
            total=len(snapshot),
            pending=pending,
            running=running,
            completed=completed,
            failed=failed,
            skipped=skipped,
        )

    @classmethod
    def from_orchestrator(cls, orchestrator: ExecutionOrchestrator) -> "ExecutionProgress":
        """Build progress from an orchestrator's current ``snapshot()``.

        Read-only: calls ``orchestrator.snapshot()`` only, never a
        ``mark_*`` method — orchestrator state is never touched.
        """
        return cls.from_snapshot(orchestrator.snapshot())
