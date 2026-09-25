"""MARK L v8.5 — Task Graph (Foundation Layer).

A deterministic, in-process directed acyclic graph of immutable
``Node`` value objects. Stores relationships between tasks; performs
no execution, no scheduling, no AI reasoning, no provider calls, no
persistence, no networking, no event emission.

This module is **independent** of ``core.planning_engine.PlanningEngine``
and the pre-existing ``core.planner``: the three coexist. Future
versions may bridge them through adapters; this milestone establishes
the Foundation-layer graph store only.

Dependency direction:

    PlanningEngine / Agent  →  TaskGraph  (allowed)
    TaskGraph  →  anything in core.*        (forbidden)

Only standard library imports are allowed.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True, slots=True)
class Node:
    """A single immutable graph node.

    No execution status, no runtime state, no scheduling. ``metadata``
    is a free-form mapping of string keys to arbitrary values
    (caller-owned; never inspected by the graph).
    """

    id: str
    title: str
    description: str
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


class TaskGraph:
    """Deterministic, thread-safe, in-process DAG of ``Node`` objects.

    Public API:
        ``create_node(...)``, ``update_node(...)``, ``remove_node(...)``,
        ``connect(parent, child)``, ``disconnect(parent, child)``,
        ``children(node)``, ``parents(node)``, ``roots()``,
        ``leaves()``, ``get_node(...)``, ``list_nodes()``,
        ``clear()``, ``count()``.

    Insertion order is preserved. Snapshots are immutable (``Node``
    is a frozen dataclass; ``children`` / ``parents`` / ``roots`` /
    ``leaves`` / ``list_nodes`` return tuples). Duplicate ids and
    duplicate edges are rejected. Self-links are rejected. Cycles
    are rejected at ``connect`` time.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._order: list[str] = []
        # Adjacency: parent -> ordered list of child ids; reverse map
        # for parents(). Order is preserved per parent.
        self._children: dict[str, list[str]] = {}
        self._parents: dict[str, list[str]] = {}
        self._lock = threading.RLock()

    # ── Write: nodes ────────────────────────────────────────────────────

    def create_node(
        self,
        *,
        title: str,
        description: str = "",
        metadata: Optional[Mapping[str, object]] = None,
        node_id: Optional[str] = None,
    ) -> Node:
        """Create and store a new node. Returns the new ``Node``."""
        self._validate_title(title)
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        rid = node_id or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("node_id must be a non-empty string")
        now = time.monotonic()
        node = Node(
            id=rid,
            title=title,
            description=description or "",
            metadata=dict(metadata) if metadata else {},
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            if rid in self._nodes:
                raise ValueError(f"node_id already exists: {rid}")
            self._nodes[rid] = node
            self._order.append(rid)
            self._children.setdefault(rid, [])
            self._parents.setdefault(rid, [])
        return node

    def update_node(
        self,
        node_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> Node:
        """Replace the stored node. Returns the new ``Node``.

        Only supplied fields are changed. ``updated_at`` is refreshed.
        """
        with self._lock:
            existing = self._nodes.get(node_id)
            if existing is None:
                raise KeyError(node_id)
            new_title = existing.title if title is None else self._validate_title(title)
            new_description = (
                existing.description if description is None else description
            )
            if not isinstance(new_description, str):
                raise ValueError("description must be a string")
            if metadata is None:
                new_metadata: dict[str, object] = dict(existing.metadata)
            else:
                if not isinstance(metadata, Mapping):
                    raise ValueError("metadata must be a mapping")
                new_metadata = dict(metadata)
            new_node = Node(
                id=existing.id,
                title=new_title,
                description=new_description,
                metadata=new_metadata,
                created_at=existing.created_at,
                updated_at=time.monotonic(),
            )
            self._nodes[node_id] = new_node
        return new_node

    def remove_node(self, node_id: str) -> bool:
        """Remove ``node_id`` and all incident edges. Returns
        ``True`` if a node was removed, ``False`` if absent."""
        with self._lock:
            if node_id not in self._nodes:
                return False
            for child in list(self._children.get(node_id, ())):
                self._parents.get(child, []).remove(node_id)
            for parent in list(self._parents.get(node_id, ())):
                self._children.get(parent, []).remove(node_id)
            del self._nodes[node_id]
            self._order.remove(node_id)
            self._children.pop(node_id, None)
            self._parents.pop(node_id, None)
            return True

    # ── Write: edges ────────────────────────────────────────────────────

    def connect(self, parent_id: str, child_id: str) -> None:
        """Add a directed edge ``parent_id -> child_id``.

        Rejects unknown nodes, self-links, duplicate edges, and
        edges that would introduce a cycle.
        """
        with self._lock:
            self._require_known(parent_id)
            self._require_known(child_id)
            if parent_id == child_id:
                raise ValueError("self-links are not allowed")
            if child_id in self._children[parent_id]:
                raise ValueError(
                    f"duplicate edge: {parent_id} -> {child_id}"
                )
            if self._would_create_cycle(parent_id, child_id):
                raise ValueError(
                    f"edge {parent_id} -> {child_id} would create a cycle"
                )
            self._children[parent_id].append(child_id)
            self._parents[child_id].append(parent_id)

    def disconnect(self, parent_id: str, child_id: str) -> bool:
        """Remove a directed edge. Returns ``True`` if removed."""
        with self._lock:
            if parent_id not in self._nodes or child_id not in self._nodes:
                return False
            removed = False
            kids = self._children.get(parent_id)
            if kids is not None and child_id in kids:
                kids.remove(child_id)
                removed = True
            par = self._parents.get(child_id)
            if par is not None and parent_id in par:
                par.remove(parent_id)
                removed = True
            return removed

    # ── Read ─────────────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Node | None:
        with self._lock:
            return self._nodes.get(node_id)

    def list_nodes(self) -> tuple[Node, ...]:
        with self._lock:
            return tuple(self._nodes[nid] for nid in self._order)

    def children(self, node_id: str) -> tuple[str, ...]:
        with self._lock:
            self._require_known(node_id)
            return tuple(self._children.get(node_id, ()))

    def parents(self, node_id: str) -> tuple[str, ...]:
        with self._lock:
            self._require_known(node_id)
            return tuple(self._parents.get(node_id, ()))

    def roots(self) -> tuple[Node, ...]:
        """Return nodes with no parents, in insertion order."""
        with self._lock:
            return tuple(
                self._nodes[nid] for nid in self._order
                if not self._parents.get(nid)
            )

    def leaves(self) -> tuple[Node, ...]:
        """Return nodes with no children, in insertion order."""
        with self._lock:
            return tuple(
                self._nodes[nid] for nid in self._order
                if not self._children.get(nid)
            )

    # ── Delete / Introspection ───────────────────────────────────────────

    def clear(self) -> None:
        with self._lock:
            self._nodes.clear()
            self._order.clear()
            self._children.clear()
            self._parents.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def __len__(self) -> int:
        return self.count()

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _validate_title(title: object) -> str:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        return title

    def _require_known(self, node_id: str) -> None:
        if node_id not in self._nodes:
            raise KeyError(node_id)

    def _would_create_cycle(self, parent_id: str, child_id: str) -> bool:
        """Return ``True`` if adding ``parent_id -> child_id`` would
        create a cycle (i.e. ``parent_id`` is already reachable from
        ``child_id``)."""
        stack = [child_id]
        seen: set[str] = set()
        while stack:
            cur = stack.pop()
            if cur == parent_id:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(self._children.get(cur, ()))
        return False


__all__ = ["Node", "TaskGraph"]