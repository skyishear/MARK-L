"""MARK L v3.3 — Execution Orchestration Foundation.

``ExecutionOrchestrator`` is a standalone state-tracking module: given
an ordered sequence of tasks (id + dependency ids), it tracks each
task's execution state (``PENDING`` / ``RUNNING`` / ``COMPLETED`` /
``FAILED`` / ``SKIPPED``) and can report which task is next ready to
run, given already-recorded state. It performs NO execution of any
kind — no tool invocation, no AI calls, no MemoryEngine access, no
SkillRegistry access, no ProblemSolver calls. It is pure, in-memory
bookkeeping plus deterministic ordering logic.

This module has no dependency on ``core.planner`` or any other MARK L
module — it is constructed from plain ``OrchestratedTask`` records
supplied by the caller (see
``core/planner_execution_orchestrator_adapter.py`` for the translation
from an ``ExecutionPlan``), keeping it fully decoupled and reusable
outside the Planning Engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Sequence

__all__ = [
    "ExecutionOrchestrator",
    "InvalidTransitionError",
    "OrchestratedTask",
    "OrchestrationError",
    "TaskExecutionRecord",
    "TaskState",
    "UnknownTaskError",
]


class TaskState(str, Enum):
    """The execution state of a single orchestrated task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


_TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.SKIPPED})

# Allowed (from -> to) state transitions. Anything not listed here is
# rejected by _transition() with InvalidTransitionError.
_ALLOWED_TRANSITIONS: frozenset[tuple[TaskState, TaskState]] = frozenset(
    {
        (TaskState.PENDING, TaskState.RUNNING),
        (TaskState.PENDING, TaskState.SKIPPED),
        (TaskState.RUNNING, TaskState.COMPLETED),
        (TaskState.RUNNING, TaskState.FAILED),
    }
)


class OrchestrationError(Exception):
    """Base exception for the Execution Orchestration Foundation."""


class InvalidTransitionError(OrchestrationError, ValueError):
    """Raised when a requested state transition is not permitted."""


class UnknownTaskError(OrchestrationError, KeyError):
    """Raised when a task id is not part of the orchestrated set."""


@dataclass(frozen=True, slots=True)
class OrchestratedTask:
    """A single task handed to ``ExecutionOrchestrator``: id + dependency ids.

    Plain data — no description, no execution logic. Carries only
    what deterministic ordering needs.
    """

    task_id: str
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskExecutionRecord:
    """An immutable point-in-time view of one task's execution state."""

    task_id: str
    state: TaskState
    depends_on: tuple[str, ...]
    updated_at: datetime


class ExecutionOrchestrator:
    """Tracks execution state for an ordered, dependency-linked task set.

    Constructed with the full set of tasks up front (dependency
    injection — the caller supplies the tasks; nothing is discovered
    or fetched internally). Never executes a task: callers are
    expected to perform the actual work elsewhere and report the
    outcome back via ``mark_running`` / ``mark_completed`` /
    ``mark_failed`` / ``mark_skipped``.
    """

    def __init__(self, tasks: Sequence[OrchestratedTask]) -> None:
        ids = [task.task_id for task in tasks]
        if len(set(ids)) != len(ids):
            raise OrchestrationError("orchestrator received duplicate task ids")

        self._order: tuple[str, ...] = tuple(ids)
        self._tasks: dict[str, OrchestratedTask] = {task.task_id: task for task in tasks}
        self._states: dict[str, TaskState] = {tid: TaskState.PENDING for tid in ids}
        self._updated_at: dict[str, datetime] = {
            tid: datetime.now(timezone.utc) for tid in ids
        }

    @property
    def order(self) -> tuple[str, ...]:
        """Task ids in the deterministic order supplied at construction."""
        return self._order

    def get_state(self, task_id: str) -> TaskState:
        """Return the current state of ``task_id``."""
        self._require_known(task_id)
        return self._states[task_id]

    def snapshot(self) -> tuple[TaskExecutionRecord, ...]:
        """Return a read-only view of every task's current state, in order."""
        return tuple(
            TaskExecutionRecord(
                task_id=tid,
                state=self._states[tid],
                depends_on=self._tasks[tid].depends_on,
                updated_at=self._updated_at[tid],
            )
            for tid in self._order
        )

    def is_finished(self) -> bool:
        """True once every task has reached a terminal state."""
        return all(state in _TERMINAL_STATES for state in self._states.values())

    def next_ready_task(self) -> str | None:
        """Return the id of the next task ready to run, or ``None``.

        A task is ready when it is still ``PENDING`` and every task it
        depends on has reached ``COMPLETED``. Among ready tasks, the
        first one in ``self.order`` is returned — deterministic given
        the current recorded states. Does not execute or mark
        anything; purely a read.
        """
        for tid in self._order:
            if self._states[tid] != TaskState.PENDING:
                continue
            depends_on = self._tasks[tid].depends_on
            if all(self._states[dep] == TaskState.COMPLETED for dep in depends_on):
                return tid
        return None

    def mark_running(self, task_id: str) -> TaskExecutionRecord:
        """Transition ``task_id`` from ``PENDING`` to ``RUNNING``."""
        return self._transition(task_id, TaskState.RUNNING)

    def mark_completed(self, task_id: str) -> TaskExecutionRecord:
        """Transition ``task_id`` from ``RUNNING`` to ``COMPLETED``."""
        return self._transition(task_id, TaskState.COMPLETED)

    def mark_failed(self, task_id: str) -> TaskExecutionRecord:
        """Transition ``task_id`` from ``RUNNING`` to ``FAILED``."""
        return self._transition(task_id, TaskState.FAILED)

    def mark_skipped(self, task_id: str) -> TaskExecutionRecord:
        """Transition ``task_id`` from ``PENDING`` to ``SKIPPED``."""
        return self._transition(task_id, TaskState.SKIPPED)

    def _require_known(self, task_id: str) -> None:
        if task_id not in self._states:
            raise UnknownTaskError(task_id)

    def _transition(self, task_id: str, to_state: TaskState) -> TaskExecutionRecord:
        self._require_known(task_id)
        from_state = self._states[task_id]
        if (from_state, to_state) not in _ALLOWED_TRANSITIONS:
            raise InvalidTransitionError(
                f"task {task_id!r} cannot move from {from_state.value!r} "
                f"to {to_state.value!r}"
            )
        self._states[task_id] = to_state
        self._updated_at[task_id] = datetime.now(timezone.utc)
        return TaskExecutionRecord(
            task_id=task_id,
            state=to_state,
            depends_on=self._tasks[task_id].depends_on,
            updated_at=self._updated_at[task_id],
        )
