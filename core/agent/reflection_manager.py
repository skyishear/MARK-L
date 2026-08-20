"""Runtime reflection record tracking for MARK L V3 Foundation.

ReflectionManager owns only deliberate runtime self-assessment records
produced after completed work (what worked, what failed, identified
mistakes, uncertainties, improvement suggestions, confidence level,
completion summaries). It is distinct from LearningManager: reflection
is an explicit review process, not observed runtime learning. It is
NOT long-term memory, does not replace MemoryEngine, and has no
dependency on LearningManager, KnowledgeManager, HistoryManager,
ContextManager, or any other module.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


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
    """

    def __init__(self) -> None:
        """Initialize an empty reflection registry."""
        self._records: dict[str, ReflectionRecord] = {}
        self._lock = threading.RLock()

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
            The newly created, immutable ReflectionRecord.

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
        return record

    def get(self, record_id: str) -> ReflectionRecord | None:
        """Return the record for ``record_id``, or ``None``."""
        with self._lock:
            return self._records.get(record_id)

    def require(self, record_id: str) -> ReflectionRecord:
        """Return the record for ``record_id``.

        Raises:
            ReflectionRecordNotFoundError: If not present.
        """
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                raise ReflectionRecordNotFoundError(record_id)
            return record

    def get_by_subject(self, subject: str) -> list[ReflectionRecord]:
        """Return all records matching ``subject``, in insertion order."""
        with self._lock:
            return [r for r in self._records.values() if r.subject == subject]

    def get_all(self) -> list[ReflectionRecord]:
        """Return all reflection records in insertion order."""
        with self._lock:
            return list(self._records.values())

    def remove(self, record_id: str) -> None:
        """Remove the record with ``record_id`` if present. No-op otherwise."""
        with self._lock:
            self._records.pop(record_id, None)

    def clear(self) -> None:
        """Remove all reflection records."""
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        with self._lock:
            return record_id in self._records
