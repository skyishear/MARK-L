"""Runtime reflection record tracking for MARK L V3 Foundation.

``ReflectionManager`` is the **integration layer** between the
Agent lifecycle (which records deliberate runtime self-assessments
as ``ReflectionRecord`` values) and the Foundation-level
``ReflectionEngine`` (the canonical reflection store introduced in
v8.2). It is distinct from ``LearningManager``: reflection is an
explicit review process, not observed runtime learning. It is NOT
long-term memory, does not replace ``MemoryEngine``, and has no
dependency on LearningManager, KnowledgeManager, HistoryManager,
ContextManager, or any other module.

Dependency direction (v8.3):

    Agent
        ↓
    ReflectionManager
        ↓
    ReflectionEngine (core.reflection_engine)

The manager is the only module that talks to the engine. The engine
itself never imports the manager, the Agent, the AI stack, or any
other ``core.*`` module — it remains a pure storage layer.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from core.reflection_engine import Reflection, ReflectionEngine


class ReflectionRecordNotFoundError(KeyError):
    """Raised when a requested reflection record does not exist."""


class InvalidReflectionRecordError(ValueError):
    """Raised when reflection record data fails validation."""


@dataclass(frozen=True, slots=True)
class ReflectionRecord:
    """A single immutable deliberate runtime self-assessment record."""

    id: str
    subject: str
    what_worked: str
    what_failed: str
    mistakes_identified: tuple[str, ...]
    uncertainties: tuple[str, ...]
    improvement_suggestions: tuple[str, ...]
    confidence_level: float
    completion_summary: str
    metadata: dict[str, Any]
    created_at: datetime


class ReflectionManager:
    """Thread-safe, in-memory container for runtime reflection records.

    Standalone infrastructure component: no persistence, no AI
    reasoning, no planning, no reference resolution, no background
    processing, no cross-module communication.

    In v8.3 each ``add_reflection`` call is **mirrored** into a
    Foundation-level ``ReflectionEngine``. The engine is the
    canonical store; the manager's own dict is preserved for
    backward compatibility with the v3.x ``ReflectionRecord``
    contract (rich fields, ``get_by_subject`` lookups, etc.).
    """

    def __init__(
        self,
        engine: Optional[ReflectionEngine] = None,
    ) -> None:
        """Initialize an empty reflection registry.

        ``engine`` is the Foundation-level reflection store. When
        ``None``, a fresh ``ReflectionEngine`` is created and owned
        by this manager.
        """
        self._records: dict[str, ReflectionRecord] = {}
        self._lock = threading.RLock()
        self._engine: ReflectionEngine = (
            engine if engine is not None else ReflectionEngine()
        )

    # ── Engine access ────────────────────────────────────────────────────

    @property
    def engine(self) -> ReflectionEngine:
        """The Foundation-level reflection store this manager writes through.

        Always non-``None``. Returned reference is stable for the
        lifetime of the manager.
        """
        return self._engine

    # ── Write ────────────────────────────────────────────────────────────

    def add_reflection(
        self,
        subject: str,
        what_worked: str = "",
        what_failed: str = "",
        mistakes_identified: list[str] | None = None,
        uncertainties: list[str] | None = None,
        improvement_suggestions: list[str] | None = None,
        confidence_level: float = 0.0,
        completion_summary: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ReflectionRecord:
        """Record a deliberate self-assessment for completed work.

        Args:
            subject: What the reflection is about (e.g. a task name).
            what_worked: Description of what worked.
            what_failed: Description of what failed.
            mistakes_identified: Identified mistakes.
            uncertainties: Open uncertainties.
            improvement_suggestions: Suggestions for improvement.
            confidence_level: Self-assessed confidence, in ``[0.0, 1.0]``.
            completion_summary: Summary of the completed work.
            metadata: Optional additional metadata.

        Returns:
            The newly created, immutable ``ReflectionRecord``.

        Raises:
            InvalidReflectionRecordError: If ``confidence_level`` is
                outside the inclusive range ``[0.0, 1.0]``.
        """
        if not 0.0 <= confidence_level <= 1.0:
            raise InvalidReflectionRecordError(
                f"confidence_level must be within [0.0, 1.0], got {confidence_level}"
            )

        record = ReflectionRecord(
            id=uuid.uuid4().hex,
            subject=subject,
            what_worked=what_worked,
            what_failed=what_failed,
            mistakes_identified=tuple(mistakes_identified or ()),
            uncertainties=tuple(uncertainties or ()),
            improvement_suggestions=tuple(improvement_suggestions or ()),
            confidence_level=confidence_level,
            completion_summary=completion_summary,
            metadata=dict(metadata) if metadata else {},
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._records[record.id] = record
        # Mirror into the canonical Foundation-level engine so the
        # engine is the single source of truth across the Agent.
        self._mirror(record)
        return record

    def _mirror(self, record: ReflectionRecord) -> Reflection:
        """Write ``record`` into the engine as a canonical ``Reflection``.

        Maps the rich ``ReflectionRecord`` fields onto the engine's
        flat ``Reflection`` contract: ``subject`` → ``summary``,
        ``completion_summary`` → ``details`` (with structured
        additions), ``metadata`` keys → ``details`` text, derived
        ``category`` from the subject prefix when present.
        """
        details_parts: list[str] = []
        if record.what_worked:
            details_parts.append(f"worked={record.what_worked}")
        if record.what_failed:
            details_parts.append(f"failed={record.what_failed}")
        for m in record.mistakes_identified:
            details_parts.append(f"mistake={m}")
        for u in record.uncertainties:
            details_parts.append(f"uncertain={u}")
        for s in record.improvement_suggestions:
            details_parts.append(f"improve={s}")
        for k, v in sorted(record.metadata.items()):
            details_parts.append(f"meta[{k}]={v}")
        details = " | ".join(details_parts)

        category = "reflection"
        subject = record.subject or ""
        if ":" in subject:
            head, _, _ = subject.partition(":")
            if head.strip():
                category = head.strip()

        return self._engine.record_reflection(
            category=category,
            summary=subject or "(no subject)",
            details=details,
            source="reflection_manager",
            project=None,
            confidence=record.confidence_level,
            importance=3,
        )

    # ── Read ─────────────────────────────────────────────────────────────

    def get(self, record_id: str) -> ReflectionRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def require(self, record_id: str) -> ReflectionRecord:
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                raise ReflectionRecordNotFoundError(record_id)
            return record

    def get_by_subject(self, subject: str) -> list[ReflectionRecord]:
        with self._lock:
            return [r for r in self._records.values() if r.subject == subject]

    def get_all(self) -> list[ReflectionRecord]:
        with self._lock:
            return list(self._records.values())

    # ── Delete / Introspection ───────────────────────────────────────────

    def remove(self, record_id: str) -> None:
        with self._lock:
            self._records.pop(record_id, None)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
        self._engine.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        with self._lock:
            return record_id in self._records


__all__ = [
    "InvalidReflectionRecordError",
    "Reflection",
    "ReflectionEngine",
    "ReflectionManager",
    "ReflectionRecord",
    "ReflectionRecordNotFoundError",
]