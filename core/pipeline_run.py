"""MARK L v8.9 — Pipeline Run Status Records (Foundation Layer).

A deterministic, in-process store of immutable ``PipelineRun``
records: the **representation** of a pipeline run's status. It
performs no execution, no scheduling, no retries, no cancellation
mechanics, no event dispatch, no progress tracking, no persistence,
no networking, no AI/provider calls, and no I/O. Status only changes
when a caller explicitly asks for a transition; nothing here ever
transitions a run on its own.

This module is **independent** of the legacy v3.x execution stack
(``core.execution_orchestrator.TaskState`` et al.): the two coexist.

Dependency direction:

    Future callers / Agent  →  PipelineRunManager   (allowed)
    PipelineRunManager  →  PipelineEngine           (allowed, read-only)
    PipelineRunManager  →  anything else in core.*  (forbidden)

Only standard library imports are allowed, plus ``core.pipeline_engine``.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from core.pipeline_engine import PipelineEngine


class PipelineRunStatus(str, Enum):
    """Allowed pipeline-run lifecycle statuses."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Explicit (from -> to) transitions. Anything not listed is rejected by
# ``PipelineRunManager.update_run`` with ``ValueError``. Terminal
# statuses (COMPLETED / FAILED / CANCELLED) have no outgoing edges.
ALLOWED_TRANSITIONS: frozenset[tuple[PipelineRunStatus, PipelineRunStatus]] = frozenset(
    {
        (PipelineRunStatus.CREATED, PipelineRunStatus.RUNNING),
        (PipelineRunStatus.CREATED, PipelineRunStatus.CANCELLED),
        (PipelineRunStatus.RUNNING, PipelineRunStatus.COMPLETED),
        (PipelineRunStatus.RUNNING, PipelineRunStatus.FAILED),
        (PipelineRunStatus.RUNNING, PipelineRunStatus.CANCELLED),
    }
)


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """An immutable record of one pipeline run's status.

    Stores **only opaque identifiers and immutable data** — no
    ``PipelineRecord``, ``PipelineEngine``, node, goal, plan, agent or
    executable object is embedded. ``metadata`` is a read-only mapping
    view; the manager never hands out a mutable reference to it.
    """

    id: str
    pipeline_reference: str
    status: PipelineRunStatus
    created_at: float
    updated_at: float
    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )


class PipelineRunManager:
    """Deterministic, thread-safe, in-process pipeline-run store.

    Public API:
        ``create_run(pipeline_id, *, metadata=None, run_id=None)``,
        ``update_run(run_id, *, status=None, metadata=None)``,
        ``get_run(run_id)``, ``list_runs(status=None)``,
        ``remove_run(run_id)``, ``count()``, ``clear()``.

    Insertion order is preserved. Snapshots are immutable
    (``PipelineRun`` is a frozen dataclass; ``list_runs`` returns a
    tuple; ``metadata`` is a ``MappingProxyType``). Every run starts
    in ``CREATED``; the manager never advances a status by itself —
    only ``update_run`` does, and only along ``ALLOWED_TRANSITIONS``.
    """

    def __init__(self, pipeline_engine: PipelineEngine | None = None) -> None:
        if pipeline_engine is not None and not isinstance(pipeline_engine, PipelineEngine):
            raise TypeError("pipeline_engine must be a PipelineEngine or None")
        self._runs: dict[str, PipelineRun] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        # Read-only collaborator. None means "no validation" — the
        # pipeline reference is stored verbatim as an opaque string.
        self._engine = pipeline_engine

    # ── Read-only collaborator accessor ─────────────────────────────────

    @property
    def pipeline_engine(self) -> Optional[PipelineEngine]:
        return self._engine

    # ── Write ────────────────────────────────────────────────────────────

    def create_run(
        self,
        pipeline_id: str,
        *,
        metadata: Optional[Mapping[str, object]] = None,
        run_id: Optional[str] = None,
    ) -> PipelineRun:
        """Create and store a new ``PipelineRun`` in ``CREATED``.

        Raises:
            ValueError: ``pipeline_id`` / ``run_id`` blank or not a
                string, ``run_id`` already exists, or (when a
                ``PipelineEngine`` is wired) ``pipeline_id`` is not a
                known pipeline.
        """
        self._validate_id("pipeline_id", pipeline_id)
        if self._engine is not None and self._engine.get_pipeline(pipeline_id) is None:
            raise ValueError(f"pipeline_id {pipeline_id!r} not found in wired PipelineEngine")
        rid = run_id or uuid.uuid4().hex
        self._validate_id("run_id", rid)
        now = time.monotonic()
        record = PipelineRun(
            id=rid,
            pipeline_reference=pipeline_id,
            status=PipelineRunStatus.CREATED,
            created_at=now,
            updated_at=now,
            metadata=self._freeze_metadata(metadata),
        )
        with self._lock:
            if rid in self._runs:
                raise ValueError(f"run_id already exists: {rid}")
            self._runs[rid] = record
            self._order.append(rid)
        return record

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[PipelineRunStatus | str] = None,
        metadata: Optional[Mapping[str, object]] = None,
    ) -> PipelineRun:
        """Replace the stored run with a new record. ``None`` means
        "leave unchanged". A ``status`` change must be listed in
        ``ALLOWED_TRANSITIONS``; ``metadata`` replaces the whole
        mapping. The pipeline reference is immutable.

        Raises:
            KeyError: unknown ``run_id``.
            ValueError: invalid status value or disallowed transition.
        """
        with self._lock:
            existing = self._runs.get(run_id)
            if existing is None:
                raise KeyError(run_id)
            if status is None:
                new_status = existing.status
            else:
                new_status = self._normalize_status(status)
                if (existing.status, new_status) not in ALLOWED_TRANSITIONS:
                    raise ValueError(
                        f"invalid transition: {existing.status.value} -> {new_status.value}"
                    )
            new_metadata = (
                existing.metadata if metadata is None else self._freeze_metadata(metadata)
            )
            new_record = PipelineRun(
                id=existing.id,
                pipeline_reference=existing.pipeline_reference,
                status=new_status,
                created_at=existing.created_at,
                updated_at=time.monotonic(),
                metadata=new_metadata,
            )
            self._runs[run_id] = new_record
        return new_record

    # ── Read ─────────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> PipelineRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(
        self, status: Optional[PipelineRunStatus | str] = None
    ) -> tuple[PipelineRun, ...]:
        """Return an immutable snapshot of stored runs, in insertion
        order, optionally filtered by ``status``."""
        if status is None:
            with self._lock:
                return tuple(self._runs[rid] for rid in self._order)
        target = self._normalize_status(status)
        with self._lock:
            return tuple(
                self._runs[rid] for rid in self._order
                if self._runs[rid].status == target
            )

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove_run(self, run_id: str) -> bool:
        with self._lock:
            if run_id not in self._runs:
                return False
            del self._runs[run_id]
            self._order.remove(run_id)
            return True

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._order.clear()

    def count(self) -> int:
        with self._lock:
            return len(self._runs)

    def __len__(self) -> int:
        return self.count()

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _validate_id(name: str, value: object) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    @staticmethod
    def _normalize_status(status: object) -> PipelineRunStatus:
        if isinstance(status, PipelineRunStatus):
            return status
        if isinstance(status, str):
            try:
                return PipelineRunStatus(status)
            except ValueError as exc:
                raise ValueError(f"invalid status: {status!r}") from exc
        raise ValueError(f"invalid status: {status!r}")

    @staticmethod
    def _freeze_metadata(
        metadata: Optional[Mapping[str, object]],
    ) -> Mapping[str, object]:
        if metadata is None:
            return MappingProxyType({})
        if not isinstance(metadata, Mapping):
            raise ValueError("metadata must be a mapping or None")
        # Defensive copy behind a read-only view: the caller's mapping
        # and the stored one never alias each other.
        return MappingProxyType(dict(metadata))


__all__ = [
    "ALLOWED_TRANSITIONS",
    "PipelineRun",
    "PipelineRunManager",
    "PipelineRunStatus",
]
