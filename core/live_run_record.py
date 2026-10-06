"""MARK L v8.43 — Production Run Recording (P5).

Records the production tool calls through the v8.x lifecycle, from the O9
outcome record only (a ``ToolCallOutcome``: call id, tool name, outcome, exception
type name — never arguments, outputs or exception text). For every outcome:

* the call is projected into the Foundation stores exactly like a one-task plan
  (``project_request(tool_name)`` — the legacy planner turns the tool name into a
  one-task plan);
* Goal and Plan go ACTIVE, a ``PipelineRun`` is created and set RUNNING (the
  v8.25 order);
* **executed** — the step goes ACTIVE then COMPLETED, the run COMPLETED, Plan and
  Goal COMPLETED, then the success writeback (Memory → Reflection → Learning);
* **failed** — the step stays ACTIVE, the run is FAILED, Goal and Plan stay
  ACTIVE, then exactly one failure writeback (type name only, confidence 0);
* **refused** — nothing ran: the step is ARCHIVED ("skipped, not executed, no
  success implied", v8.26), the run COMPLETES (an all-skipped run completes,
  v8.23), Plan and Goal COMPLETE, and nothing is written back (v8.24).

Only existing statuses and the existing reflection functions (injected through
``LifecycleHooks`` by the Agent) are used; no new meaning is
assigned to any status. The Memory layer is the in-process ``MemoryEngine``: the
production SQLite store is never written (OD-5). Every outcome is recorded on its
own — one that cannot be recorded is counted and never stops the others — and the
caller (the live tool session) additionally guarantees recording can never break
a tool call.

Dependency direction:

    Agent  →  live_run_record  →  pipeline_run
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from core.pipeline_run import PipelineRun, PipelineRunStatus

__all__ = ["LifecycleHooks", "LiveRunRecord", "record_tool_outcomes"]

_CAUSE = "production_tool_run"


@dataclass(frozen=True, slots=True)
class LifecycleHooks:
    """The reflection callables the recorder drives (supplied by the Agent):
    ``execution_started / execution_completed (goal_id, plan_id)`` and
    ``step_reached / step_completed / step_skipped (plan_id, task_id)``."""

    execution_started: Callable[[str, str], Any]
    execution_completed: Callable[[str, str], Any]
    step_reached: Callable[[str, str], Any]
    step_completed: Callable[[str, str], Any]
    step_skipped: Callable[[str, str], Any]


@dataclass(frozen=True, slots=True)
class LiveRunRecord:
    """The runs recorded for a batch of outcomes, and how many could not be."""

    runs: tuple[PipelineRun, ...]
    errors: int


def _record_one(
    outcome: Any,
    *,
    hooks: LifecycleHooks,
    project_request: Callable[[str], tuple[Any, Any]],
    pipeline_run_manager: Any,
    reflection: Any,
    learning: Any,
    memory_engine: Any,
    project: Optional[str],
) -> PipelineRun:
    plan, projection = project_request(outcome.tool_name)
    task_id = plan.tasks[0].id
    plan_id, goal_id = projection.plan_id, projection.goal_id
    hooks.execution_started(goal_id, plan_id)
    run = pipeline_run_manager.create_run(
        projection.pipeline_id,
        metadata={
            "project": project,
            "goal_id": goal_id,
            "mapping_id": projection.mapping_id,
            "call_id": outcome.call_id,
            "source": "production_tool_session",
        },
    )
    pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.RUNNING)
    tool = outcome.tool_name
    metadata = {
        "run_id": run.id, "goal_id": goal_id, "plan_id": plan_id, "task_id": task_id,
        "call_id": outcome.call_id, "project": project, "outcome": outcome.outcome,
    }
    if outcome.outcome == "refused":
        hooks.step_skipped(plan_id, task_id)
        final = pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.COMPLETED)
        hooks.execution_completed(goal_id, plan_id)
        return final
    hooks.step_reached(plan_id, task_id)
    if outcome.outcome == "failed":
        final = pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.FAILED)
        metadata["exception_type"] = outcome.exception_type
        memory_engine.remember(
            "tool_outcome", f"{tool}:{outcome.call_id}", f"failed:{outcome.exception_type}",
            source="live_tool_run", project=project, memory_type="session", sensitive=False,
        )
        reflection.add_reflection(
            subject=task_id,
            what_failed=f"{_CAUSE}:{tool}",
            completion_summary=f"Execution attempt failed ({outcome.exception_type}) under the production tool run.",
            confidence_level=0.0,
            metadata=dict(metadata),
        )
        learning.record_failed_pattern(
            subject=tool,
            detail=f"Execution attempt failed ({outcome.exception_type}) under the production tool run.",
            metadata=dict(metadata),
        )
        return final
    hooks.step_completed(plan_id, task_id)
    final = pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.COMPLETED)
    hooks.execution_completed(goal_id, plan_id)
    memory_engine.remember(
        "tool_outcome", f"{tool}:{outcome.call_id}", "success",
        source="live_tool_run", project=project, memory_type="session", sensitive=False,
    )
    reflection.add_reflection(
        subject=task_id,
        what_worked=f"{_CAUSE}:{tool}",
        completion_summary=f"Tool '{tool}' executed successfully under the production tool run.",
        confidence_level=1.0,
        metadata=dict(metadata),
    )
    learning.record_successful_pattern(
        subject=tool,
        detail=f"Tool '{tool}' executed successfully under the production tool run.",
        metadata=dict(metadata),
    )
    return final


def record_tool_outcomes(
    outcomes: Sequence[Any],
    *,
    hooks: LifecycleHooks,
    project_request: Callable[[str], tuple[Any, Any]],
    pipeline_run_manager: Any,
    reflection: Any,
    learning: Any,
    memory_engine: Any,
    project: Optional[str] = None,
) -> LiveRunRecord:
    """Record ``outcomes`` through the v8.x lifecycle, one ``PipelineRun`` each.

    Returns the runs that were recorded and the number of outcomes that could not
    be (each failure is isolated; the exception text is dropped).
    """
    runs: list[PipelineRun] = []
    errors = 0
    for outcome in outcomes:
        try:
            runs.append(
                _record_one(
                    outcome,
                    hooks=hooks,
                    project_request=project_request,
                    pipeline_run_manager=pipeline_run_manager,
                    reflection=reflection,
                    learning=learning,
                    memory_engine=memory_engine,
                    project=project,
                )
            )
        except Exception:  # noqa: BLE001 - one unrecordable outcome never stops the others
            errors += 1
    return LiveRunRecord(tuple(runs), errors)
