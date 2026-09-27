"""MARK L v8.26 — Step Lifecycle Reflection.

Reflects per-stage outcomes of a Foundation-native execution attempt onto
the projected Foundation ``Step.status`` through the existing
replacement-style ``PlanningEngine.get_plan`` / ``update_plan(steps=...)``
APIs. Locked contract (project decision recorded in ``ROADMAP.md`` before
v8.26):

* newly projected step                    → DRAFT (set by the projection)
* execution reaches a dispatched stage    → ACTIVE
* dispatched stage succeeds               → COMPLETED
* reached stage skipped (tool unregistered) → ARCHIVED, directly from DRAFT
                                            ("skipped, not executed, no
                                            success implied")
* stage/tool failure                      → the step **remains ACTIVE**
* steps never reached after a failure     → remain DRAFT

Only the existing ``PlanStatus`` vocabulary is used. No ``StepStatus`` type,
no new values, no transition state machine, no legacy ``TaskState``, no
re-execution / idempotency handling ("COMPLETED is never downgraded" is an
invariant of the projection model: every execution re-projects into fresh
DRAFT steps). Steps are targeted by ``plan_id`` + ``Step.id`` (the legacy
``Task.id`` carried as ``ToolDispatchDecision.task_id``), never by position.
Each call is one read followed by one whole-tuple replacement (not atomic
across the two store calls). Exceptions raised by the store propagate
unchanged.

Dependency direction:

    Agent  →  step_lifecycle  →  planning_engine
    step_lifecycle  →  anything else in core.*   (forbidden)
"""

from __future__ import annotations

from core.planning_engine import PlanStatus, PlanningEngine, Step

__all__ = ["reflect_step_reached", "reflect_step_completed", "reflect_step_skipped"]


def reflect_step_reached(
    plan_id: str,
    step_id: str,
    *,
    planning_engine: PlanningEngine,
) -> None:
    """Mark the step ``ACTIVE`` just before its stage is dispatched."""
    _set_step_status(planning_engine, plan_id, step_id, PlanStatus.ACTIVE)


def reflect_step_completed(
    plan_id: str,
    step_id: str,
    *,
    planning_engine: PlanningEngine,
) -> None:
    """Mark the step ``COMPLETED`` after its dispatched stage succeeded."""
    _set_step_status(planning_engine, plan_id, step_id, PlanStatus.COMPLETED)


def reflect_step_skipped(
    plan_id: str,
    step_id: str,
    *,
    planning_engine: PlanningEngine,
) -> None:
    """Mark the step ``ARCHIVED`` when its reached stage was skipped."""
    _set_step_status(planning_engine, plan_id, step_id, PlanStatus.ARCHIVED)


def _set_step_status(
    planning_engine: object,
    plan_id: str,
    step_id: str,
    status: PlanStatus,
) -> None:
    """Replace the one step whose ``id`` is ``step_id`` with a copy carrying
    ``status``; every other step is kept as-is.

    Raises ``TypeError`` for a wrong store type, ``KeyError`` for an unknown
    plan or a step id not present in that plan.
    """
    if not isinstance(planning_engine, PlanningEngine):
        raise TypeError("planning_engine must be a PlanningEngine")
    plan = planning_engine.get_plan(plan_id)
    if plan is None:
        raise KeyError(plan_id)
    if step_id not in {s.id for s in plan.steps}:
        raise KeyError(step_id)
    steps = tuple(
        Step(
            id=s.id,
            index=s.index,
            title=s.title,
            description=s.description,
            status=status,
        )
        if s.id == step_id
        else s
        for s in plan.steps
    )
    planning_engine.update_plan(plan_id, steps=steps)
