"""MARK L v8.7 — Execution Planner (Foundation Layer).

A deterministic, in-process, **read-only** coordination layer. It
combines opaque identifiers from the existing
``GoalManager`` / ``PlanningEngine`` / ``TaskGraph`` Foundation
modules into ``ExecutionMapping`` records and a deterministic
execution order. It never mutates those modules, never stores
copies of their records, never executes anything, and never
performs I/O, AI reasoning, or provider calls.

This module is **independent** of the pre-existing
``core.planner.ExecutionPlan`` dataclass: the two coexist. To
avoid shadowing the existing type, the Foundation-layer value
object is named ``ExecutionMapping``.

Dependency direction:

    ExecutionPipeline / Agent  →  ExecutionPlanner  (allowed)
    ExecutionPlanner  →  GoalManager / PlanningEngine / TaskGraph
                                       (allowed)
    ExecutionPlanner  →  anything else in core.*   (forbidden)

Only standard library imports are allowed, plus the three
Foundation modules explicitly listed above.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Sequence

from core.goal_manager import GoalManager, GoalRecord
from core.planning_engine import Plan, PlanningEngine
from core.task_graph import Node, TaskGraph


@dataclass(frozen=True, slots=True)
class ExecutionMapping:
    """An immutable record of an execution mapping.

    Stores **only opaque string identifiers** — pointers to the
    canonical records held by the respective Foundation managers.
    No ``GoalRecord``, ``Plan``, or ``Node`` object is embedded.
    ``ordered_node_ids`` is a deterministic sequence the planner
    computed via topological order over the supplied ``TaskGraph``.
    """

    id: str
    goal_reference: Optional[str]
    plan_reference: Optional[str]
    graph_reference: Optional[str]
    ordered_node_ids: tuple[str, ...]
    created_at: float
    updated_at: float
    metadata: dict[str, object] = field(default_factory=dict)


class ExecutionPlanner:
    """Deterministic, thread-safe, read-only execution-planning store.

    Public API:
        ``create_execution_plan(...)``,
        ``update_execution_plan(...)``,
        ``get_execution_plan(mapping_id)``,
        ``list_execution_plans()``,
        ``remove_execution_plan(mapping_id)``,
        ``steps_for_goal(goal_id)``,
        ``steps_for_plan(plan_id)``,
        ``execution_order(mapping_id)``,
        ``count()``, ``clear()``.

    Insertion order is preserved. Snapshots are immutable
    (``ExecutionMapping`` is a frozen dataclass; all collection
    accessors return tuples). The planner does not modify any
    Foundation module; it only reads from them when validating
    references and computing topological order.
    """

    def __init__(
        self,
        goal_manager: GoalManager | None = None,
        planning_engine: PlanningEngine | None = None,
        task_graph: TaskGraph | None = None,
    ) -> None:
        self._mappings: dict[str, ExecutionMapping] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        # The three Foundation stores are read-only collaborators.
        # None means "no validation against that store" — references
        # are still stored as opaque strings, but the planner will
        # not dereference them.
        self._goals = goal_manager
        self._plans = planning_engine
        self._graph = task_graph

    # ── Read-only collaborator accessors ────────────────────────────────

    @property
    def goal_manager(self) -> Optional[GoalManager]:
        return self._goals

    @property
    def planning_engine(self) -> Optional[PlanningEngine]:
        return self._plans

    @property
    def task_graph(self) -> Optional[TaskGraph]:
        return self._graph

    # ── Write ────────────────────────────────────────────────────────────

    def create_execution_plan(
        self,
        *,
        goal_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        graph_id: Optional[str] = None,
        ordered_node_ids: Optional[Sequence[str]] = None,
        metadata: Optional[dict] = None,
        mapping_id: Optional[str] = None,
    ) -> ExecutionMapping:
        """Create and store a new ``ExecutionMapping``.

        ``goal_id`` / ``plan_id`` / ``graph_id`` are opaque references
        to the canonical records in the three Foundation stores.
        When the corresponding store is wired in, the planner
        validates that the reference exists; otherwise the reference
        is stored verbatim.

        ``ordered_node_ids`` defaults to the topological order of
        the wired ``TaskGraph`` (or ``()`` when no graph is wired).
        """
        self._validate_reference("goal_id", goal_id)
        self._validate_reference("plan_id", plan_id)
        self._validate_reference("graph_id", graph_id)
        self._validate_known("goal_id", goal_id, self._goals)
        self._validate_known("plan_id", plan_id, self._plans)
        normalized_order = self._compute_order(
            graph_id, ordered_node_ids
        )
        rid = mapping_id or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("mapping_id must be a non-empty string")
        now = time.monotonic()
        mapping = ExecutionMapping(
            id=rid,
            goal_reference=goal_id,
            plan_reference=plan_id,
            graph_reference=graph_id,
            ordered_node_ids=normalized_order,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata) if metadata else {},
        )
        with self._lock:
            if rid in self._mappings:
                raise ValueError(f"mapping_id already exists: {rid}")
            self._mappings[rid] = mapping
            self._order.append(rid)
        return mapping

    def update_execution_plan(
        self,
        mapping_id: str,
        *,
        ordered_node_ids: Optional[Sequence[str]] = None,
        metadata: Optional[dict] = None,
    ) -> ExecutionMapping:
        """Replace the stored mapping. ``None`` means "leave
        unchanged". Only the ordered-node sequence and metadata may
        be changed after creation; references are immutable."""
        with self._lock:
            existing = self._mappings.get(mapping_id)
            if existing is None:
                raise KeyError(mapping_id)
            new_order = (
                existing.ordered_node_ids if ordered_node_ids is None
                else tuple(ordered_node_ids)
            )
            for nid in new_order:
                if not isinstance(nid, str) or not nid:
                    raise ValueError("ordered_node_ids must be non-empty strings")
            new_metadata = (
                dict(existing.metadata) if metadata is None else dict(metadata)
            )
            new_mapping = ExecutionMapping(
                id=existing.id,
                goal_reference=existing.goal_reference,
                plan_reference=existing.plan_reference,
                graph_reference=existing.graph_reference,
                ordered_node_ids=new_order,
                created_at=existing.created_at,
                updated_at=time.monotonic(),
                metadata=new_metadata,
            )
            self._mappings[mapping_id] = new_mapping
        return new_mapping

    # ── Read ─────────────────────────────────────────────────────────────

    def get_execution_plan(self, mapping_id: str) -> ExecutionMapping | None:
        with self._lock:
            return self._mappings.get(mapping_id)

    def list_execution_plans(self) -> tuple[ExecutionMapping, ...]:
        with self._lock:
            return tuple(self._mappings[mid] for mid in self._order)

    def steps_for_goal(self, goal_id: str) -> tuple[ExecutionMapping, ...]:
        with self._lock:
            return tuple(
                self._mappings[mid] for mid in self._order
                if self._mappings[mid].goal_reference == goal_id
            )

    def steps_for_plan(self, plan_id: str) -> tuple[ExecutionMapping, ...]:
        with self._lock:
            return tuple(
                self._mappings[mid] for mid in self._order
                if self._mappings[mid].plan_reference == plan_id
            )

    def execution_order(self, mapping_id: str) -> tuple[str, ...]:
        with self._lock:
            mapping = self._mappings.get(mapping_id)
            if mapping is None:
                raise KeyError(mapping_id)
            return mapping.ordered_node_ids

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove_execution_plan(self, mapping_id: str) -> bool:
        with self._lock:
            if mapping_id not in self._mappings:
                return False
            del self._mappings[mapping_id]
            self._order.remove(mapping_id)
            return True

    def clear(self) -> None:
        with self._lock:
            self._mappings.clear()
            self._order.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._mappings)

    def __len__(self) -> int:
        return self.count()

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _validate_reference(name: str, value: Optional[str]) -> None:
        if value is None:
            return
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string or None")

    @staticmethod
    def _validate_known(
        name: str,
        value: Optional[str],
        store,
    ) -> None:
        if value is None or store is None:
            return
        # store exposes get_* — duck-type lookup by convention.
        getter = getattr(store, "get_" + name.split("_")[0], None)
        if getter is None:
            return
        try:
            present = getter(value)
        except Exception:
            present = None
        if present is None:
            raise ValueError(f"{name} {value!r} not found in wired store")

    def _compute_order(
        self,
        graph_id: Optional[str],
        ordered_node_ids: Optional[Sequence[str]],
    ) -> tuple[str, ...]:
        if ordered_node_ids is not None:
            materialized = tuple(ordered_node_ids)
            for nid in materialized:
                if not isinstance(nid, str) or not nid:
                    raise ValueError(
                        "ordered_node_ids must be non-empty strings"
                    )
            return materialized
        # If a graph is wired (regardless of whether graph_id is
        # supplied), compute its topological order.
        if self._graph is not None:
            return self._topological_order(self._graph)
        return ()

    @staticmethod
    def _topological_order(graph: TaskGraph) -> tuple[str, ...]:
        # Kahn's algorithm with stable, insertion-order tiebreaking.
        in_degree: dict[str, int] = {}
        children: dict[str, tuple[str, ...]] = {}
        for node in graph.list_nodes():
            in_degree[node.id] = len(graph.parents(node.id))
            children[node.id] = graph.children(node.id)
        ready: deque[str] = deque(
            sorted(nid for nid, d in in_degree.items() if d == 0)
        )
        order: list[str] = []
        while ready:
            nid = ready.popleft()
            order.append(nid)
            for child in children.get(nid, ()):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    # Insertion-order stable: append then re-sort
                    # is unnecessary because insertion order is
                    # already the secondary key.
                    ready.append(child)
        if len(order) != len(in_degree):
            raise ValueError("cycle detected in wired TaskGraph")
        return tuple(order)


__all__ = ["ExecutionMapping", "ExecutionPlanner"]