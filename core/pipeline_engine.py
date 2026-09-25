"""MARK L v8.8 — Pipeline Engine (Foundation Layer).

A deterministic, in-process, **read-only** coordination/storage layer.
It transforms an existing v8.7 ``ExecutionMapping`` (resolved through
the wired ``ExecutionPlanner``) into an immutable ``PipelineRecord``:
an ordered tuple of ``PipelineStage`` value objects. It never
executes anything, never tracks runtime task state, never evaluates
readiness, and never performs I/O, AI reasoning, or provider calls.

This module is **independent** of the pre-existing
``core.execution_pipeline.ExecutionPipeline`` (legacy v3.x stack):
the two coexist. To avoid shadowing the legacy type, the
Foundation-layer coordinator is named ``PipelineEngine``.

Dependency direction:

    Future callers / Agent  →  PipelineEngine          (allowed)
    PipelineEngine  →  ExecutionPlanner / TaskGraph    (allowed)
    PipelineEngine  →  anything else in core.*         (forbidden)

Only standard library imports are allowed, plus the two Foundation
modules explicitly listed above.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from core.execution_planner import ExecutionPlanner
from core.task_graph import TaskGraph


@dataclass(frozen=True, slots=True)
class PipelineStage:
    """One immutable stage of a pipeline.

    ``depends_on`` is **descriptive** dependency metadata only (the
    parent ids reported by the wired ``TaskGraph`` at build time, or
    ``()`` when no graph is wired). Nothing here evaluates readiness.
    """

    index: int
    node_id: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PipelineRecord:
    """An immutable pipeline built from one ``ExecutionMapping``.

    Stores **only opaque identifiers and immutable tuples** — no
    ``ExecutionMapping``, ``Node``, ``GoalRecord`` or ``Plan`` object
    is embedded. ``stages`` preserves the exact order returned by
    ``ExecutionPlanner.execution_order(mapping_id)`` at build time.
    """

    id: str
    execution_mapping_reference: str
    stages: tuple[PipelineStage, ...]
    created_at: float
    updated_at: float


class PipelineEngine:
    """Deterministic, thread-safe, read-only pipeline store.

    Public API:
        ``build_pipeline(mapping_id, *, pipeline_id=None)``,
        ``get_pipeline(pipeline_id)``,
        ``list_pipelines()``,
        ``remove_pipeline(pipeline_id)``,
        ``count()``, ``clear()``.

    Insertion order is preserved. Snapshots are immutable
    (``PipelineRecord`` / ``PipelineStage`` are frozen dataclasses;
    all collection accessors return tuples). The engine does not
    modify ``ExecutionPlanner`` or ``TaskGraph``; it only reads from
    them while building. There is deliberately no update operation:
    a pipeline is a pure function of a mapping at build time, so a
    changed mapping is reflected by removing and rebuilding.
    """

    def __init__(
        self,
        execution_planner: ExecutionPlanner,
        task_graph: TaskGraph | None = None,
    ) -> None:
        if not isinstance(execution_planner, ExecutionPlanner):
            raise TypeError("execution_planner must be an ExecutionPlanner")
        if task_graph is not None and not isinstance(task_graph, TaskGraph):
            raise TypeError("task_graph must be a TaskGraph or None")
        self._pipelines: dict[str, PipelineRecord] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        # Read-only collaborators. A ``None`` graph means stages carry
        # ``depends_on == ()``; the engine never dereferences nodes.
        self._planner = execution_planner
        self._graph = task_graph

    # ── Read-only collaborator accessors ────────────────────────────────

    @property
    def execution_planner(self) -> ExecutionPlanner:
        return self._planner

    @property
    def task_graph(self) -> Optional[TaskGraph]:
        return self._graph

    # ── Build ────────────────────────────────────────────────────────────

    def build_pipeline(
        self,
        mapping_id: str,
        *,
        pipeline_id: Optional[str] = None,
    ) -> PipelineRecord:
        """Build and store a ``PipelineRecord`` for ``mapping_id``.

        Raises:
            ValueError: ``mapping_id`` / ``pipeline_id`` blank or not a
                string, or ``pipeline_id`` already exists.
            KeyError: ``mapping_id`` unknown to the wired
                ``ExecutionPlanner``, or a node id in the mapping's
                execution order unknown to the wired ``TaskGraph``.
        """
        if not isinstance(mapping_id, str) or not mapping_id.strip():
            raise ValueError("mapping_id must be a non-empty string")
        rid = pipeline_id or uuid.uuid4().hex
        if not isinstance(rid, str) or not rid.strip():
            raise ValueError("pipeline_id must be a non-empty string")
        # ExecutionPlanner.execution_order raises KeyError for an
        # unknown mapping — propagated unchanged (v8.x convention).
        ordered_node_ids = self._planner.execution_order(mapping_id)
        stages = self._build_stages(ordered_node_ids)
        now = time.monotonic()
        record = PipelineRecord(
            id=rid,
            execution_mapping_reference=mapping_id,
            stages=stages,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            if rid in self._pipelines:
                raise ValueError(f"pipeline_id already exists: {rid}")
            self._pipelines[rid] = record
            self._order.append(rid)
        return record

    # ── Read ─────────────────────────────────────────────────────────────

    def get_pipeline(self, pipeline_id: str) -> PipelineRecord | None:
        with self._lock:
            return self._pipelines.get(pipeline_id)

    def list_pipelines(self) -> tuple[PipelineRecord, ...]:
        with self._lock:
            return tuple(self._pipelines[pid] for pid in self._order)

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove_pipeline(self, pipeline_id: str) -> bool:
        with self._lock:
            if pipeline_id not in self._pipelines:
                return False
            del self._pipelines[pipeline_id]
            self._order.remove(pipeline_id)
            return True

    def clear(self) -> None:
        with self._lock:
            self._pipelines.clear()
            self._order.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._pipelines)

    def __len__(self) -> int:
        return self.count()

    # ── Internals ────────────────────────────────────────────────────────

    def _build_stages(
        self, ordered_node_ids: tuple[str, ...]
    ) -> tuple[PipelineStage, ...]:
        stages: list[PipelineStage] = []
        for index, node_id in enumerate(ordered_node_ids):
            # TaskGraph.parents raises KeyError for an unknown node —
            # propagated unchanged. Result is already a tuple; copy
            # defensively so the record never aliases graph state.
            depends_on = (
                tuple(self._graph.parents(node_id))
                if self._graph is not None
                else ()
            )
            stages.append(
                PipelineStage(index=index, node_id=node_id, depends_on=depends_on)
            )
        return tuple(stages)


__all__ = ["PipelineEngine", "PipelineRecord", "PipelineStage"]
