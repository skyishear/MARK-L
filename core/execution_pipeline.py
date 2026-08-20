"""MARK L v3.4 — Execution Pipeline Foundation.

``ExecutionPipeline`` coordinates two already-existing, unmodified
layers:

- ``core.execution_orchestrator.ExecutionOrchestrator`` — task state
  (which tasks are ``PENDING`` and ready to run, given already
  recorded state).
- ``core.planner_problem_solver_adapter`` — translation from an
  ``ExecutionPlan``'s tasks into ``ProblemSolverWorkItem`` records and
  ``core.problem_solver.gather_context`` kwargs.

Given both (accepted via constructor injection, never constructed
internally), the pipeline reads which tasks are currently ready, and
for each one builds an immutable ``PipelineExecutionDescriptor``
bundling its work item and its ProblemSolver ``gather_context`` kwargs
— ready for a caller to hand to ``problem_solver.gather_context(**kwargs)``
elsewhere.

The pipeline itself never calls ``core.problem_solver``, never
executes a task, never invokes a Skill, never calls an AI provider,
never touches MemoryEngine, and never changes any orchestrator state —
it only reads state (via the orchestrator's existing ``snapshot()``)
and translates (via the existing planner_problem_solver_adapter). It
imports neither ``core.problem_solver`` nor any Foundation module.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from core.execution_orchestrator import ExecutionOrchestrator, TaskState
from core.planner import ExecutionPlan
from core.planner_problem_solver_adapter import (
    ProblemSolverWorkItem,
    gather_context_kwargs,
    plan_to_work_items,
)

__all__ = ["ExecutionPipeline", "PipelineExecutionDescriptor"]

_WorkItemBuilder = Callable[[ExecutionPlan, "str | None"], "tuple[ProblemSolverWorkItem, ...]"]
_ContextKwargsBuilder = Callable[[ProblemSolverWorkItem], "dict[str, Any]"]


@dataclass(frozen=True, slots=True)
class PipelineExecutionDescriptor:
    """An immutable, ready-to-hand-off description of one ready task.

    Carries no execution logic — ``gather_context_kwargs`` is a
    read-only mapping the caller may pass to
    ``core.problem_solver.gather_context(**kwargs)`` themselves;
    nothing in this module calls it.
    """

    task_id: str
    work_item: ProblemSolverWorkItem
    gather_context_kwargs: Mapping[str, Any]


class ExecutionPipeline:
    """Coordinates an ExecutionOrchestrator and the planner→ProblemSolver adapter.

    Both dependencies are injected, not constructed internally:

    - ``orchestrator``: an existing ``ExecutionOrchestrator`` instance
      whose recorded state determines which tasks are ready.
    - ``plan``: the ``ExecutionPlan`` the orchestrator was built for
      (task descriptions live here; the orchestrator itself only
      tracks ids and dependencies).
    - ``work_item_builder`` / ``context_kwargs_builder``: default to
      the existing ``planner_problem_solver_adapter`` functions, and
      may be swapped for tests — this module never hardcodes a call
      to ``core.problem_solver``.

    Nothing here executes a task or mutates orchestrator state; it is
    a pure, standalone read + translate step.
    """

    def __init__(
        self,
        orchestrator: ExecutionOrchestrator,
        plan: ExecutionPlan,
        *,
        project: str | None = None,
        work_item_builder: _WorkItemBuilder = plan_to_work_items,
        context_kwargs_builder: _ContextKwargsBuilder = gather_context_kwargs,
    ) -> None:
        self._orchestrator = orchestrator
        self._plan = plan
        self._project = project
        self._work_item_builder = work_item_builder
        self._context_kwargs_builder = context_kwargs_builder

    def ready_task_ids(self) -> tuple[str, ...]:
        """Ids of tasks currently ready to run, in deterministic order.

        A task is ready when it is ``PENDING`` and every task it
        depends on is ``COMPLETED``, mirroring
        ``ExecutionOrchestrator.next_ready_task()``'s own readiness
        rule — but computed here purely by reading the orchestrator's
        existing ``snapshot()``, so every currently-ready task is
        returned in one pass instead of only the first. Read-only:
        never calls a ``mark_*`` method.
        """
        snapshot = self._orchestrator.snapshot()
        states = {record.task_id: record.state for record in snapshot}
        ready: list[str] = []
        for record in snapshot:
            if record.state != TaskState.PENDING:
                continue
            if all(states[dep] == TaskState.COMPLETED for dep in record.depends_on):
                ready.append(record.task_id)
        return tuple(ready)

    def ready_descriptors(self) -> tuple[PipelineExecutionDescriptor, ...]:
        """Build immutable execution descriptors for every ready task.

        Steps, all read-only translation — no execution:

        1. Read ready task ids from the orchestrator (``ready_task_ids``).
        2. Build ``ProblemSolverWorkItem`` records for the whole plan
           via the injected ``work_item_builder`` (defaults to
           ``planner_problem_solver_adapter.plan_to_work_items``),
           then keep only the ones matching a ready task id.
        3. Build ``gather_context`` kwargs for each via the injected
           ``context_kwargs_builder`` (defaults to
           ``planner_problem_solver_adapter.gather_context_kwargs``).

        Returns:
            A tuple of ``PipelineExecutionDescriptor``, one per ready
            task, in the orchestrator's deterministic order.
        """
        ready_ids = self.ready_task_ids()
        if not ready_ids:
            return ()

        ready_id_set = set(ready_ids)
        all_work_items = self._work_item_builder(self._plan, self._project)
        work_items_by_id = {
            item.task_id: item for item in all_work_items if item.task_id in ready_id_set
        }

        descriptors: list[PipelineExecutionDescriptor] = []
        for task_id in ready_ids:
            work_item = work_items_by_id[task_id]
            kwargs = MappingProxyType(dict(self._context_kwargs_builder(work_item)))
            descriptors.append(
                PipelineExecutionDescriptor(
                    task_id=task_id,
                    work_item=work_item,
                    gather_context_kwargs=kwargs,
                )
            )
        return tuple(descriptors)
