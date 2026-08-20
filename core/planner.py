"""MARK L V3.1.0 Planning Engine — Phase 1.

PlanningEngine converts a user goal into a deterministic, ordered
``ExecutionPlan`` made of dependent ``Task`` records. This is planning
only: the planner performs no execution, no AI/provider calls, and no
persistence, and has no dependency on any other MARK L module —
Foundation (``core.agent.*``), ``MemoryEngine``, ``ProblemSolver``,
``SkillRegistry``, ``IdentityEngine``, ``core.llm_client``, or the
Phase 2 integration adapters.

Given the same goal string, ``PlanningEngine.plan`` always produces a
plan with the same goal id, task ids, task descriptions, and task
dependency structure — goal/task ids and the dependency graph are
derived deterministically from the goal text itself, never randomly
generated. ``created_at`` on ``Goal`` and ``ExecutionPlan`` is the one
intentional exception: it records actual wall-clock creation time and
is expected to differ between calls, even for an identical goal.
``ExecutionPlan`` and ``Task`` are immutable (frozen dataclasses) once
created.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

__all__ = [
    "ExecutionPlan",
    "Goal",
    "InvalidGoalError",
    "PlanningEngine",
    "PlanningError",
    "PlanValidationError",
    "Task",
]

_STEP_JOIN_DELIMITERS: tuple[str, ...] = (" and then ", " then ")


class PlanningError(Exception):
    """Base exception for the Planning Engine."""


class InvalidGoalError(PlanningError, ValueError):
    """Raised when a goal cannot be planned (empty, blank, or non-string)."""


class PlanValidationError(PlanningError, ValueError):
    """Raised when an ``ExecutionPlan``'s task graph is invalid.

    Covers duplicate task ids, a dependency referencing an unknown
    task id, and cyclic dependencies.
    """


@dataclass(frozen=True, slots=True)
class Goal:
    """An immutable record of the user goal a plan was built from.

    ``id`` and ``description`` are deterministic functions of the
    goal text. ``created_at`` is not deterministic — it reflects the
    actual time this record was created.
    """

    id: str
    description: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Task:
    """A single immutable, ordered step within an ``ExecutionPlan``.

    ``depends_on`` holds the ids of tasks that must precede this one.
    Task carries no execution logic of its own — it is a plain data
    record describing what should happen, not code that performs it.
    ``metadata`` is stored as a read-only mapping — any dict passed in
    is copied and wrapped, so the field cannot be mutated in place
    while still supporting normal read-only mapping access (``[]``,
    ``.get()``, ``.items()``, etc.).
    """

    id: str
    description: str
    depends_on: tuple[str, ...]
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """An immutable, deterministically ordered plan for achieving a ``Goal``.

    Validated on creation: every ``depends_on`` id must reference a
    task present in the plan, task ids must be unique, and the
    dependency graph must be acyclic. ``ExecutionPlan`` performs no
    execution, persistence, or side effects of its own — it is a pure
    data structure. ``id``, ``goal``, and ``tasks`` (including the
    dependency graph) are deterministic for a given goal; ``created_at``
    is not — it reflects the actual time this plan was created.
    """

    id: str
    goal: Goal
    tasks: tuple[Task, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        _validate_tasks(self.tasks)

    def get_task(self, task_id: str) -> Task | None:
        """Return the task with ``task_id``, or ``None`` if absent."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def execution_order(self) -> tuple[Task, ...]:
        """Return tasks in a valid, deterministic dependency-respecting order.

        Uses Kahn's algorithm over ``self.tasks``: among tasks that
        become ready at the same time, order is preserved from the
        original ``self.tasks`` sequence, so the result is stable and
        deterministic for a given plan.
        """
        return _topological_sort(self.tasks)

    def __len__(self) -> int:
        return len(self.tasks)


def _validate_tasks(tasks: tuple[Task, ...]) -> None:
    ids = [task.id for task in tasks]
    if len(set(ids)) != len(ids):
        raise PlanValidationError("execution plan contains duplicate task ids")

    id_set = set(ids)
    for task in tasks:
        for dependency_id in task.depends_on:
            if dependency_id not in id_set:
                raise PlanValidationError(
                    f"task {task.id!r} depends on unknown task {dependency_id!r}"
                )

    _topological_sort(tasks)  # raises PlanValidationError on a cycle


def _topological_sort(tasks: tuple[Task, ...]) -> tuple[Task, ...]:
    by_id = {task.id: task for task in tasks}
    in_degree = {task.id: len(task.depends_on) for task in tasks}
    dependents: dict[str, list[str]] = {task.id: [] for task in tasks}
    for task in tasks:
        for dependency_id in task.depends_on:
            if dependency_id in dependents:
                dependents[dependency_id].append(task.id)

    ready = [task.id for task in tasks if in_degree[task.id] == 0]
    ordered_ids: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered_ids.append(current)
        for child_id in dependents[current]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                ready.append(child_id)

    if len(ordered_ids) != len(tasks):
        raise PlanValidationError("execution plan contains a cyclic dependency")

    return tuple(by_id[task_id] for task_id in ordered_ids)


def _make_goal_id(description: str) -> str:
    digest = hashlib.sha256(description.encode("utf-8")).hexdigest()[:16]
    return f"goal-{digest}"


def _split_into_steps(description: str) -> list[str]:
    """Deterministically split a goal into ordered step strings.

    Recognizes explicit sequencing delimiters (`` then ``,
    `` and then ``, ``;``, and newlines) so a multi-step goal becomes
    multiple ordered tasks. A goal with no such delimiter becomes a
    single-step plan. Purely textual — no inference, no AI call.
    """
    normalized = description
    for delimiter in _STEP_JOIN_DELIMITERS:
        normalized = normalized.replace(delimiter, ";")
    normalized = normalized.replace("\n", ";")

    steps = [step.strip() for step in normalized.split(";")]
    steps = [step for step in steps if step]
    return steps or [description.strip()]


class PlanningEngine:
    """Converts a user goal into a deterministic ``ExecutionPlan``.

    Stateless and standalone: ``plan`` is a pure function of its input
    string. It never executes tools, calls AI providers, accesses
    MemoryEngine or any Foundation module, invokes ProblemSolver,
    SkillRegistry, IdentityEngine, or the integration adapters, writes
    files, or performs browser actions.
    """

    def plan(self, goal: str) -> ExecutionPlan:
        """Convert ``goal`` into an ordered, dependency-linked ``ExecutionPlan``.

        Args:
            goal: A non-empty description of what the user wants
                accomplished. Steps within the goal may be separated
                with "then", "and then", ";", or newlines to produce
                multiple ordered, sequentially dependent tasks.

        Returns:
            An immutable ``ExecutionPlan`` for ``goal``. Its id, goal
            id, task ids, and dependency graph are deterministic
            functions of ``goal``; its ``created_at`` (and the
            nested ``Goal.created_at``) reflect actual creation time
            and are not deterministic.

        Raises:
            InvalidGoalError: If ``goal`` is not a string, or is empty
                or blank after stripping whitespace.
        """
        if not isinstance(goal, str) or not goal.strip():
            raise InvalidGoalError("goal must be a non-empty string")

        description = goal.strip()
        goal_id = _make_goal_id(description)
        goal_record = Goal(
            id=goal_id,
            description=description,
            created_at=datetime.now(timezone.utc),
        )

        tasks: list[Task] = []
        previous_task_id: str | None = None
        for index, step in enumerate(_split_into_steps(description), start=1):
            task_id = f"{goal_id}-task-{index}"
            depends_on = (previous_task_id,) if previous_task_id else ()
            tasks.append(
                Task(
                    id=task_id,
                    description=step,
                    depends_on=depends_on,
                    metadata={},
                )
            )
            previous_task_id = task_id

        return ExecutionPlan(
            id=f"{goal_id}-plan",
            goal=goal_record,
            tasks=tuple(tasks),
            created_at=datetime.now(timezone.utc),
        )
