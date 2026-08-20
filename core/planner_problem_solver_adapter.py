"""MARK L v3.2 — Planner → Problem Solver integration layer.

Bridges ``core.planner`` (``ExecutionPlan`` / ``Task``) and
``core.problem_solver`` without modifying either module. This layer
performs pure, one-way data translation only:

- It reads an ``ExecutionPlan``'s tasks (via the planner's own
  ``execution_order()``) and turns each ``Task`` into a
  ``ProblemSolverWorkItem`` — a plain, immutable data record.
- It turns each work item into keyword-argument dicts shaped to match
  ``core.problem_solver``'s existing public function signatures
  (``gather_context``, ``format_context_for_solver``,
  ``record_outcome``), so a caller can invoke those functions with
  ``problem_solver.gather_context(**kwargs)``.

This module deliberately does NOT import ``core.problem_solver`` and
never calls any of its functions itself — the caller decides if/when
to do that. As a direct consequence this layer never touches
MemoryEngine (which ``core.problem_solver`` reads/writes internally),
never calls an AI provider, never invokes SkillRegistry or
IdentityEngine, and never executes a task. It composes no Foundation
module and is not wired into ``Agent`` — it is a standalone,
caller-invoked translation step, matching the existing integration
adapters in ``core/agent/*_adapter.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.planner import ExecutionPlan, Task

__all__ = [
    "ProblemSolverWorkItem",
    "gather_context_kwargs",
    "format_context_kwargs",
    "plan_to_work_items",
    "record_outcome_kwargs",
]


@dataclass(frozen=True, slots=True)
class ProblemSolverWorkItem:
    """One ``Task`` translated into ProblemSolver-consumable shape.

    Plain, immutable data — no execution logic. ``problem`` is the
    exact text ``core.problem_solver`` expects as its ``problem``
    argument; ``depends_on`` and ``task_id`` are carried through
    unchanged from the source ``Task`` so a caller can still honor the
    plan's dependency order while working through problems one at a
    time.
    """

    task_id: str
    problem: str
    depends_on: tuple[str, ...]
    project: str | None


def plan_to_work_items(
    plan: ExecutionPlan, project: str | None = None
) -> tuple[ProblemSolverWorkItem, ...]:
    """Translate an ``ExecutionPlan`` into an ordered tuple of work items.

    Uses the plan's own ``execution_order()`` (PlanningEngine's
    existing public API) — this function performs no scheduling or
    dependency resolution of its own, only a 1:1 field mapping from
    each ``Task`` to a ``ProblemSolverWorkItem``. No task is executed;
    nothing here calls ``core.problem_solver`` or any other module.

    Args:
        plan: The ``ExecutionPlan`` produced by
            ``core.planner.PlanningEngine.plan()``.
        project: Optional project name, attached to every work item
            unchanged (forwarded, not interpreted).

    Returns:
        A tuple of ``ProblemSolverWorkItem``, one per task, in the
        plan's dependency-respecting execution order.
    """
    return tuple(
        _task_to_work_item(task, project=project) for task in plan.execution_order()
    )


def _task_to_work_item(task: Task, *, project: str | None) -> ProblemSolverWorkItem:
    return ProblemSolverWorkItem(
        task_id=task.id,
        problem=task.description,
        depends_on=task.depends_on,
        project=project,
    )


def gather_context_kwargs(item: ProblemSolverWorkItem) -> dict[str, Any]:
    """Build kwargs for ``core.problem_solver.gather_context(**kwargs)``.

    Pure mapping: ``{"problem": item.problem, "project": item.project}``.
    Does not call ``gather_context`` itself.
    """
    return {"problem": item.problem, "project": item.project}


def format_context_kwargs(item: ProblemSolverWorkItem) -> dict[str, Any]:
    """Build kwargs for ``core.problem_solver.format_context_for_solver(**kwargs)``.

    Pure mapping: ``{"problem": item.problem, "project": item.project}``.
    Does not call ``format_context_for_solver`` itself.
    """
    return {"problem": item.problem, "project": item.project}


def record_outcome_kwargs(
    item: ProblemSolverWorkItem,
    *,
    cause: str,
    solution: str,
    outcome: str,
) -> dict[str, Any]:
    """Build kwargs for ``core.problem_solver.record_outcome(**kwargs)``.

    Pure mapping of ``item.problem`` / ``item.project`` plus the
    caller-supplied ``cause``, ``solution``, and ``outcome`` (this
    layer has no way to know those — they come from whatever actually
    solved the problem, outside this module's scope). Does not call
    ``record_outcome`` itself, so nothing is written to MemoryEngine
    by this function.
    """
    return {
        "problem": item.problem,
        "cause": cause,
        "solution": solution,
        "outcome": outcome,
        "project": item.project,
    }
