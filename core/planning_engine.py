"""MARK L v8.4 — Planning Engine (Foundation Layer).

A deterministic, in-process plan store. Holds immutable ``Plan`` and
``Step`` value objects and exposes a small CRUD-style API for
creating, updating, listing, and removing plans. Performs no
execution, no AI reasoning, no provider calls, no persistence, no
networking, no scheduling, no event emission.

This module is **independent** of the pre-existing
``core.planner.PlanningEngine``: the two coexist. Future versions
may bridge them through an adapter; this milestone establishes the
Foundation-layer engine only.

Dependency direction:

    Agent / PlanningManager  →  PlanningEngine  (allowed)
    PlanningEngine  →  anything in core.*       (forbidden)

Only standard library imports are allowed.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence


class PlanStatus(str, Enum):
    """Allowed plan lifecycle statuses."""

    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Step:
    """A single immutable ordered step inside a ``Plan``.

    No execution semantics. ``status`` mirrors the same vocabulary
    as ``PlanStatus`` so plans and steps share a coherent lifecycle
    vocabulary, but this engine never transitions them.
    """

    id: str
    index: int
    title: str
    description: str
    status: PlanStatus


@dataclass(frozen=True, slots=True)
class Plan:
    """A single immutable plan record.

    The internal ``_steps`` tuple is exposed only through the
    ``steps`` property and is never mutated after construction.
    """

    id: str
    goal: str
    description: str
    status: PlanStatus
    created_at: float
    updated_at: float
    _steps: tuple[Step, ...] = field(default_factory=tuple)

    @property
    def steps(self) -> tuple[Step, ...]:
        return self._steps


class PlanningEngine:
    """Deterministic, thread-safe, in-process plan store.

    Public API:
        ``create_plan(...)``,
        ``update_plan(...)``,
        ``get_plan(plan_id)``,
        ``list_plans(...)``,
        ``remove_plan(plan_id)``,
        ``count()``,
        ``clear()``.

    Insertion order is preserved. Snapshots are immutable
    (``Plan`` / ``Step`` are frozen dataclasses). No I/O, no
    concurrency primitives beyond a lock.
    """

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    # ── Write ────────────────────────────────────────────────────────────

    def create_plan(
        self,
        *,
        goal: str,
        description: str = "",
        status: PlanStatus | str = PlanStatus.DRAFT,
        steps: Sequence[Step] | None = None,
        plan_id: Optional[str] = None,
    ) -> Plan:
        """Create and store a new plan. Returns the new ``Plan``.

        The caller may supply ``plan_id``; otherwise a uuid4 hex is
        generated. Duplicate ``plan_id`` values raise ``ValueError``.
        """
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        normalized_status = self._normalize_status(status)
        normalized_steps = self._normalize_steps(steps)
        now = time.monotonic()
        rid = plan_id or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("plan_id must be a non-empty string")
        with self._lock:
            if rid in self._plans:
                raise ValueError(f"plan_id already exists: {rid}")
            plan = Plan(
                id=rid,
                goal=goal,
                description=description,
                status=normalized_status,
                created_at=now,
                updated_at=now,
                _steps=normalized_steps,
            )
            self._plans[rid] = plan
            self._order.append(rid)
        return plan

    def update_plan(
        self,
        plan_id: str,
        *,
        goal: Optional[str] = None,
        description: Optional[str] = None,
        status: PlanStatus | str | None = None,
        steps: Sequence[Step] | None = None,
    ) -> Plan:
        """Create a new ``Plan`` value that replaces the stored one.

        Only the supplied fields are changed. The plan's
        ``updated_at`` is refreshed. Returns the new plan. Raises
        ``KeyError`` if ``plan_id`` is unknown.
        """
        with self._lock:
            existing = self._plans.get(plan_id)
            if existing is None:
                raise KeyError(plan_id)
            new_goal = existing.goal if goal is None else self._validate_goal(goal)
            new_description = (
                existing.description if description is None
                else self._validate_description(description)
            )
            new_status = (
                existing.status if status is None else self._normalize_status(status)
            )
            new_steps = (
                existing._steps if steps is None else self._normalize_steps(steps)
            )
            new_plan = Plan(
                id=existing.id,
                goal=new_goal,
                description=new_description,
                status=new_status,
                created_at=existing.created_at,
                updated_at=time.monotonic(),
                _steps=new_steps,
            )
            self._plans[plan_id] = new_plan
        return new_plan

    # ── Read ─────────────────────────────────────────────────────────────

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._lock:
            return self._plans.get(plan_id)

    def list_plans(
        self,
        *,
        status: PlanStatus | str | None = None,
    ) -> tuple[Plan, ...]:
        """Return an immutable snapshot of stored plans, in insertion
        order, optionally filtered by ``status``."""
        if status is None:
            with self._lock:
                return tuple(self._plans[pid] for pid in self._order)
        target = self._normalize_status(status)
        with self._lock:
            return tuple(
                self._plans[pid] for pid in self._order
                if self._plans[pid].status == target
            )

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove_plan(self, plan_id: str) -> bool:
        """Remove the plan with ``plan_id``. Returns ``True`` if a
        plan was removed, ``False`` if it was already absent."""
        with self._lock:
            if plan_id not in self._plans:
                return False
            del self._plans[plan_id]
            self._order.remove(plan_id)
            return True

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()
            self._order.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._plans)

    def __len__(self) -> int:
        return self.count()

    # ── Validation helpers ───────────────────────────────────────────────

    @staticmethod
    def _validate_goal(goal: object) -> str:
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal must be a non-empty string")
        return goal

    @staticmethod
    def _validate_description(description: object) -> str:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        return description

    @staticmethod
    def _normalize_status(status: object) -> PlanStatus:
        if isinstance(status, PlanStatus):
            return status
        if isinstance(status, str):
            try:
                return PlanStatus(status)
            except ValueError as exc:
                raise ValueError(f"invalid status: {status!r}") from exc
        raise ValueError(f"invalid status: {status!r}")

    @staticmethod
    def _normalize_steps(steps: Optional[Iterable[Step]]) -> tuple[Step, ...]:
        if steps is None:
            return ()
        if isinstance(steps, (str, bytes)):
            raise ValueError("steps must be a sequence of Step objects")
        materialized = tuple(steps)
        for i, s in enumerate(materialized):
            if not isinstance(s, Step):
                raise ValueError(f"step at index {i} is not a Step: {type(s).__name__}")
            if s.index != i:
                raise ValueError(
                    f"step at index {i} has index={s.index}; expected {i}"
                )
        return materialized


__all__ = ["Plan", "PlanStatus", "PlanningEngine", "Step"]