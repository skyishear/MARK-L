"""MARK L v3.3 — Planner -> ExecutionOrchestrator integration adapter.

Translates an ``ExecutionPlan`` (``core.planner``) into the plain
``OrchestratedTask`` records ``core.execution_orchestrator`` expects,
using only the plan's existing public ``execution_order()`` API — no
scheduling or dependency resolution happens here; that already
happened inside ``ExecutionPlan``. This module performs no execution:
it only builds data / constructs an ``ExecutionOrchestrator`` instance
for the caller to drive.
"""

from __future__ import annotations

from core.execution_orchestrator import ExecutionOrchestrator, OrchestratedTask
from core.planner import ExecutionPlan

__all__ = ["build_orchestrator_for_plan", "plan_to_orchestrated_tasks"]


def plan_to_orchestrated_tasks(plan: ExecutionPlan) -> tuple[OrchestratedTask, ...]:
    """Translate a plan's tasks into ``OrchestratedTask`` records.

    Order and dependency ids come straight from
    ``plan.execution_order()`` (PlanningEngine's own public API) — a
    1:1 field mapping, nothing recomputed.
    """
    return tuple(
        OrchestratedTask(task_id=task.id, depends_on=task.depends_on)
        for task in plan.execution_order()
    )


def build_orchestrator_for_plan(plan: ExecutionPlan) -> ExecutionOrchestrator:
    """Construct an ``ExecutionOrchestrator`` for ``plan``.

    Every task starts ``PENDING``; nothing is run. The caller is
    responsible for driving execution and reporting state back via
    the returned orchestrator's ``mark_*`` methods.
    """
    return ExecutionOrchestrator(plan_to_orchestrated_tasks(plan))
