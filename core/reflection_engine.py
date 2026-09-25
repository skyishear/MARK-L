"""MARK L v8.2 — Reflection Engine (Foundation Layer).

A deterministic, in-process reflection store. Holds immutable
``Reflection`` records in insertion order and exposes them through
snapshot-only views. Performs no AI reasoning, no I/O, no
persistence, no summarization, no automatic reflection generation.

This module is intentionally minimal: its only responsibility is
to record, expose, count, and clear reflection data. Future
versions will let Learning, Planning, and the Agent consume these
reflections — but that integration is a separate milestone.

Dependency direction:

    Agent / Learning / Planning  →  ReflectionEngine  (allowed)
    ReflectionEngine  →  anything in core.*           (forbidden)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True, slots=True)
class Reflection:
    """A single immutable reflection record.

    Every field is supplied by the caller; this engine does not
    infer or compute any value. The ``timestamp`` is the canonical
    monotonic creation time, set once at construction.
    """

    id: str
    timestamp: float
    category: str
    summary: str
    details: str
    source: str
    project: Optional[str]
    confidence: float
    importance: int


class ReflectionEngine:
    """Deterministic, thread-safe, in-process reflection store.

    Records preserve insertion order. ``recent_reflections`` returns
    an immutable tuple snapshot of the filtered records; callers
    can never mutate the engine's internal state through the
    returned collection. ``clear`` empties the store.
    """

    _ALLOWED_FIELDS = (
        "category", "summary", "details", "source", "project",
        "confidence", "importance",
    )

    def __init__(self) -> None:
        self._records: list[Reflection] = []
        self._lock = threading.RLock()

    # ── Write ────────────────────────────────────────────────────────────

    def record_reflection(
        self,
        *,
        category: str,
        summary: str,
        details: str = "",
        source: str = "engine",
        project: Optional[str] = None,
        confidence: float = 1.0,
        importance: int = 3,
    ) -> Reflection:
        """Create and store one ``Reflection`` record.

        Returns the newly created ``Reflection``. Raises ``ValueError``
        for invalid inputs. The caller may store the returned record
        for later inspection; it is an immutable value.
        """
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must be a non-empty string")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary must be a non-empty string")
        if not isinstance(details, str):
            raise ValueError("details must be a string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        if not isinstance(confidence, (int, float)) or not (
            0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError("confidence must be a number in [0.0, 1.0]")
        if not isinstance(importance, int) or not (1 <= importance <= 5):
            raise ValueError("importance must be an int in [1, 5]")

        record = Reflection(
            id=uuid.uuid4().hex,
            timestamp=time.monotonic(),
            category=category,
            summary=summary,
            details=details,
            source=source,
            project=project,
            confidence=float(confidence),
            importance=importance,
        )
        with self._lock:
            self._records.append(record)
        return record

    # ── Read ─────────────────────────────────────────────────────────────

    def recent_reflections(
        self,
        *,
        category: Optional[str] = None,
        project: Optional[str] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> tuple[Reflection, ...]:
        """Return an immutable snapshot of stored reflections, in
        insertion order, optionally filtered by ``category``,
        ``project``, and/or ``source``. ``limit`` (when supplied)
        caps the number of returned records.
        """
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise ValueError("limit must be a positive int or None")
        with self._lock:
            snapshot = list(self._records)
        out: list[Reflection] = []
        for r in snapshot:
            if category is not None and r.category != category:
                continue
            if project is not None and r.project != project:
                continue
            if source is not None and r.source != source:
                continue
            out.append(r)
            if limit is not None and len(out) >= limit:
                break
        return tuple(out)

    # ── Introspection ────────────────────────────────────────────────────

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        return self.count()

    # ── Reserved for future parity (no behavior yet) ─────────────────────

    @staticmethod
    def from_mapping(payload: Mapping[str, object]) -> Reflection:
        """Build a ``Reflection`` from a mapping (reserved helper).

        Does not store the record; only constructs the value. No
        AI / persistence behavior.
        """
        if "category" not in payload or "summary" not in payload:
            raise ValueError("payload must include at least category and summary")
        return Reflection(
            id=str(payload.get("id", uuid.uuid4().hex)),
            timestamp=float(payload.get("timestamp", time.monotonic())),  # type: ignore[arg-type]
            category=str(payload["category"]),
            summary=str(payload["summary"]),
            details=str(payload.get("details", "")),
            source=str(payload.get("source", "engine")),
            project=(None if payload.get("project") is None
                     else str(payload["project"])),
            confidence=float(payload.get("confidence", 1.0)),  # type: ignore[arg-type]
            importance=int(payload.get("importance", 3)),  # type: ignore[arg-type]
        )


__all__ = ["Reflection", "ReflectionEngine"]