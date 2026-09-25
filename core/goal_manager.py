"""MARK L v8.6 — Goal Manager (Foundation Layer).

A deterministic, in-process goal store. Holds immutable
``GoalRecord`` value objects and exposes a small CRUD-style API for
creating, updating, listing, and removing goal records. Performs
no execution, no scheduling, no decomposition, no AI reasoning, no
provider calls, no persistence, no networking, no event emission.

This module is **independent** of the pre-existing
``core.planner.Goal`` dataclass: the two coexist. To avoid
shadowing the existing type, the Foundation-layer value object is
named ``GoalRecord`` and the manager is named ``GoalManager``.

Dependency direction:

    Execution Planner / Agent  →  GoalManager  (allowed)
    GoalManager  →  anything in core.*         (forbidden)

Only standard library imports are allowed.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GoalStatus(str, Enum):
    """Allowed goal lifecycle statuses."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GoalPriority(str, Enum):
    """Allowed goal priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class GoalRecord:
    """A single immutable goal record.

    ``plan_reference`` and ``graph_reference`` are optional opaque
    identifiers — pointers to the canonical ``Plan`` / ``TaskGraph``
    records held by their respective managers. This module never
    dereferences them, never inspects them, and never embeds the
    plan or graph inside the goal.
    """

    id: str
    title: str
    description: str
    priority: GoalPriority
    status: GoalStatus
    created_at: float
    updated_at: float
    plan_reference: Optional[str] = None
    graph_reference: Optional[str] = None
    tags: tuple[str, ...] = field(default_factory=tuple)


class GoalManager:
    """Deterministic, thread-safe, in-process goal store.

    Public API:
        ``create_goal(...)``, ``update_goal(...)``,
        ``get_goal(goal_id)``, ``list_goals(...)``,
        ``remove_goal(goal_id)``, ``count()``, ``clear()``.

    Insertion order is preserved. Snapshots are immutable
    (``GoalRecord`` is a frozen dataclass; ``list_goals`` returns a
    tuple). Duplicate ``goal_id`` values are rejected. Invalid
    inputs raise ``ValueError``. No I/O, no concurrency primitives
    beyond a lock.
    """

    def __init__(self) -> None:
        self._goals: dict[str, GoalRecord] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    # ── Write ────────────────────────────────────────────────────────────

    def create_goal(
        self,
        *,
        title: str,
        description: str = "",
        priority: GoalPriority | str = GoalPriority.MEDIUM,
        status: GoalStatus | str = GoalStatus.DRAFT,
        plan_reference: Optional[str] = None,
        graph_reference: Optional[str] = None,
        tags: Optional[list[str] | tuple[str, ...]] = None,
        goal_id: Optional[str] = None,
    ) -> GoalRecord:
        """Create and store a new goal. Returns the new ``GoalRecord``."""
        normalized_title = self._validate_title(title)
        normalized_description = self._validate_description(description)
        normalized_priority = self._normalize_priority(priority)
        normalized_status = self._normalize_status(status)
        normalized_tags = self._normalize_tags(tags)
        self._validate_reference("plan_reference", plan_reference)
        self._validate_reference("graph_reference", graph_reference)
        rid = goal_id or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("goal_id must be a non-empty string")
        now = time.monotonic()
        record = GoalRecord(
            id=rid,
            title=normalized_title,
            description=normalized_description,
            priority=normalized_priority,
            status=normalized_status,
            created_at=now,
            updated_at=now,
            plan_reference=plan_reference,
            graph_reference=graph_reference,
            tags=normalized_tags,
        )
        with self._lock:
            if rid in self._goals:
                raise ValueError(f"goal_id already exists: {rid}")
            self._goals[rid] = record
            self._order.append(rid)
        return record

    def update_goal(
        self,
        goal_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[GoalPriority | str] = None,
        status: Optional[GoalStatus | str] = None,
        plan_reference: Optional[str] = None,
        graph_reference: Optional[str] = None,
        tags: Optional[list[str] | tuple[str, ...]] = None,
    ) -> GoalRecord:
        """Create a new ``GoalRecord`` value that replaces the stored
        one. Returns the new record. ``None`` means "leave
        unchanged"; for optional reference fields, use
        ``update_goal_reference`` semantics:
            - ``plan_reference`` left unchanged if ``None`` is passed.
            - Passing the literal string ``""`` (empty) is rejected.
        """
        with self._lock:
            existing = self._goals.get(goal_id)
            if existing is None:
                raise KeyError(goal_id)
            new_title = (
                existing.title if title is None else self._validate_title(title)
            )
            new_description = (
                existing.description if description is None
                else self._validate_description(description)
            )
            new_priority = (
                existing.priority if priority is None
                else self._normalize_priority(priority)
            )
            new_status = (
                existing.status if status is None
                else self._normalize_status(status)
            )
            new_plan_ref = (
                existing.plan_reference if plan_reference is None
                else self._validate_reference("plan_reference", plan_reference)
            )
            new_graph_ref = (
                existing.graph_reference if graph_reference is None
                else self._validate_reference("graph_reference", graph_reference)
            )
            new_tags = (
                existing.tags if tags is None else self._normalize_tags(tags)
            )
            new_record = GoalRecord(
                id=existing.id,
                title=new_title,
                description=new_description,
                priority=new_priority,
                status=new_status,
                created_at=existing.created_at,
                updated_at=time.monotonic(),
                plan_reference=new_plan_ref,
                graph_reference=new_graph_ref,
                tags=new_tags,
            )
            self._goals[goal_id] = new_record
        return new_record

    # ── Read ─────────────────────────────────────────────────────────────

    def get_goal(self, goal_id: str) -> GoalRecord | None:
        with self._lock:
            return self._goals.get(goal_id)

    def list_goals(
        self,
        *,
        status: Optional[GoalStatus | str] = None,
        priority: Optional[GoalPriority | str] = None,
    ) -> tuple[GoalRecord, ...]:
        """Return an immutable snapshot of stored goals, in insertion
        order, optionally filtered by ``status`` and/or ``priority``."""
        with self._lock:
            snapshot = [self._goals[gid] for gid in self._order]
        target_status = (
            None if status is None else self._normalize_status(status)
        )
        target_priority = (
            None if priority is None else self._normalize_priority(priority)
        )
        out: list[GoalRecord] = []
        for g in snapshot:
            if target_status is not None and g.status != target_status:
                continue
            if target_priority is not None and g.priority != target_priority:
                continue
            out.append(g)
        return tuple(out)

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove_goal(self, goal_id: str) -> bool:
        """Remove the goal with ``goal_id``. Returns ``True`` if a
        goal was removed, ``False`` if it was already absent."""
        with self._lock:
            if goal_id not in self._goals:
                return False
            del self._goals[goal_id]
            self._order.remove(goal_id)
            return True

    def clear(self) -> None:
        with self._lock:
            self._goals.clear()
            self._order.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._goals)

    def __len__(self) -> int:
        return self.count()

    # ── Validation helpers ───────────────────────────────────────────────

    @staticmethod
    def _validate_title(title: object) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        return title

    @staticmethod
    def _validate_description(description: object) -> str:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        return description

    @staticmethod
    def _validate_reference(name: str, value: object) -> str:
        if value is None:
            return None  # type: ignore[return-value]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string or None")
        return value

    @staticmethod
    def _normalize_status(status: object) -> GoalStatus:
        if isinstance(status, GoalStatus):
            return status
        if isinstance(status, str):
            try:
                return GoalStatus(status)
            except ValueError as exc:
                raise ValueError(f"invalid status: {status!r}") from exc
        raise ValueError(f"invalid status: {status!r}")

    @staticmethod
    def _normalize_priority(priority: object) -> GoalPriority:
        if isinstance(priority, GoalPriority):
            return priority
        if isinstance(priority, str):
            try:
                return GoalPriority(priority)
            except ValueError as exc:
                raise ValueError(f"invalid priority: {priority!r}") from exc
        raise ValueError(f"invalid priority: {priority!r}")

    @staticmethod
    def _normalize_tags(
        tags: Optional[list[str] | tuple[str, ...]],
    ) -> tuple[str, ...]:
        if tags is None:
            return ()
        if isinstance(tags, (str, bytes)):
            raise ValueError("tags must be a sequence of strings")
        materialized = tuple(tags)
        for i, t in enumerate(materialized):
            if not isinstance(t, str) or not t.strip():
                raise ValueError(f"tag at index {i} must be a non-empty string")
        return materialized


__all__ = ["GoalManager", "GoalPriority", "GoalRecord", "GoalStatus"]