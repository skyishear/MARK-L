"""MARK L v8.25 — Goal/Plan Lifecycle Reflection.

Reflects the outcome of a Foundation-native execution attempt onto the
projected ``GoalRecord`` and Foundation ``Plan`` through the existing
replacement-style ``GoalManager.update_goal`` / ``PlanningEngine.update_plan``
APIs. Locked semantics (project decision after the v8.24 audit):

    Goal / Plan  = "what are we trying to accomplish?"
    PipelineRun  = "what happened during this execution attempt?"

* execution starts     → Goal ACTIVE, Plan ACTIVE
* run COMPLETED        → Plan COMPLETED, then Goal COMPLETED
* run FAILED           → Goal and Plan **remain ACTIVE** (a failed attempt
                         is not a failed goal; it may be retried/replanned)

No new status values, no transition state machine, no meaning assigned to
``PAUSED`` / ``CANCELLED`` / ``READY`` / ``ARCHIVED``. Exceptions raised
by the stores propagate unchanged.

Dependency direction:

    Agent  →  lifecycle_reflection  →  goal_manager, planning_engine
    lifecycle_reflection  →  anything else in core.*   (forbidden)
"""

from __future__ import annotations

from core.goal_manager import GoalManager, GoalStatus
from core.planning_engine import PlanStatus, PlanningEngine

__all__ = ["reflect_execution_started", "reflect_execution_completed"]


def reflect_execution_started(
    goal_id: str,
    plan_id: str,
    *,
    goal_manager: GoalManager,
    planning_engine: PlanningEngine,
) -> None:
    """Mark the projected goal and plan ``ACTIVE`` (goal first, then plan).

    Raises ``TypeError`` for wrong store types; ``KeyError`` from the
    stores for an unknown id.
    """
    _check(goal_manager, planning_engine)
    goal_manager.update_goal(goal_id, status=GoalStatus.ACTIVE)
    planning_engine.update_plan(plan_id, status=PlanStatus.ACTIVE)


def reflect_execution_completed(
    goal_id: str,
    plan_id: str,
    *,
    goal_manager: GoalManager,
    planning_engine: PlanningEngine,
) -> None:
    """Mark the plan ``COMPLETED``, then the goal ``COMPLETED``.

    Called only after the ``PipelineRun`` reached ``COMPLETED``; a
    ``FAILED`` run performs no reflection (goal/plan stay ``ACTIVE``).
    """
    _check(goal_manager, planning_engine)
    planning_engine.update_plan(plan_id, status=PlanStatus.COMPLETED)
    goal_manager.update_goal(goal_id, status=GoalStatus.COMPLETED)


def _check(goal_manager: object, planning_engine: object) -> None:
    if not isinstance(goal_manager, GoalManager):
        raise TypeError("goal_manager must be a GoalManager")
    if not isinstance(planning_engine, PlanningEngine):
        raise TypeError("planning_engine must be a PlanningEngine")
