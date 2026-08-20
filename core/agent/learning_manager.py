"""Runtime learning observation tracking for MARK L V3 Foundation.

LearningManager owns only lightweight runtime learning observations
(corrections, successful patterns, failed patterns, preferences,
general observations). It is NOT long-term memory, does not replace
MemoryEngine, does not update KnowledgeManager, performs no AI
reasoning, no reference resolution, no background processing, and has
no dependency on any other module.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class LearningCategory(StrEnum):
    """Classification of a learning observation."""

    CORRECTION = "correction"
    SUCCESSFUL_PATTERN = "successful_pattern"
    FAILED_PATTERN = "failed_pattern"
    PREFERENCE = "preference"
    OBSERVATION = "observation"


class LearningRecordNotFoundError(KeyError):
    """Raised when a requested learning record does not exist."""


@dataclass(frozen=True, slots=True)
class LearningRecord:
    """A single immutable runtime learning observation."""

    id: str
    category: LearningCategory
    subject: str
    detail: str
    occurrence_count: int
    metadata: dict[str, Any]
    created_at: datetime
    last_observed_at: datetime


class LearningManager:
    """Thread-safe, in-memory container for runtime learning observations.

    Standalone infrastructure component: no persistence, no long-term
    memory, no KnowledgeManager updates, no cross-module communication.
    Repeated observations of the same (category, subject) pair are
    merged into a single record with an incrementing occurrence count.
    """

    def __init__(self) -> None:
        """Initialize an empty learning observation registry."""
        self._records: dict[str, LearningRecord] = {}
        self._index: dict[tuple[LearningCategory, str], str] = {}
        self._lock = threading.RLock()

    def observe(
        self,
        category: LearningCategory,
        subject: str,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> LearningRecord:
        """Record an observation, merging with any existing match.

        If a record already exists for the same ``(category, subject)``
        pair, its occurrence count is incremented and its detail and
        metadata are updated in place (same id preserved). Otherwise a
        new record is created with an occurrence count of 1.

        Args:
            category: The kind of observation.
            subject: What the observation is about.
            detail: Free-form description of the observation.
            metadata: Optional additional metadata.

        Returns:
            The resulting, immutable LearningRecord.
        """
        now = datetime.now(timezone.utc)
        key = (category, subject)
        with self._lock:
            existing_id = self._index.get(key)
            if existing_id is not None:
                existing = self._records[existing_id]
                updated = LearningRecord(
                    id=existing.id,
                    category=existing.category,
                    subject=existing.subject,
                    detail=detail if detail else existing.detail,
                    occurrence_count=existing.occurrence_count + 1,
                    metadata=dict(metadata) if metadata else existing.metadata,
                    created_at=existing.created_at,
                    last_observed_at=now,
                )
                self._records[existing.id] = updated
                return updated

            record = LearningRecord(
                id=uuid.uuid4().hex,
                category=category,
                subject=subject,
                detail=detail,
                occurrence_count=1,
                metadata=dict(metadata) if metadata else {},
                created_at=now,
                last_observed_at=now,
            )
            self._records[record.id] = record
            self._index[key] = record.id
            return record

    def record_correction(
        self, subject: str, detail: str = "", metadata: dict[str, Any] | None = None
    ) -> LearningRecord:
        """Record a user correction observation."""
        return self.observe(LearningCategory.CORRECTION, subject, detail, metadata)

    def record_successful_pattern(
        self, subject: str, detail: str = "", metadata: dict[str, Any] | None = None
    ) -> LearningRecord:
        """Record a successful pattern observation."""
        return self.observe(
            LearningCategory.SUCCESSFUL_PATTERN, subject, detail, metadata
        )

    def record_failed_pattern(
        self, subject: str, detail: str = "", metadata: dict[str, Any] | None = None
    ) -> LearningRecord:
        """Record a failed pattern observation."""
        return self.observe(LearningCategory.FAILED_PATTERN, subject, detail, metadata)

    def record_preference(
        self, subject: str, detail: str = "", metadata: dict[str, Any] | None = None
    ) -> LearningRecord:
        """Record a preference observation."""
        return self.observe(LearningCategory.PREFERENCE, subject, detail, metadata)

    def record_observation(
        self, subject: str, detail: str = "", metadata: dict[str, Any] | None = None
    ) -> LearningRecord:
        """Record a general observation."""
        return self.observe(LearningCategory.OBSERVATION, subject, detail, metadata)

    def get(self, record_id: str) -> LearningRecord | None:
        """Return the record for ``record_id``, or ``None``."""
        with self._lock:
            return self._records.get(record_id)

    def require(self, record_id: str) -> LearningRecord:
        """Return the record for ``record_id``.

        Raises:
            LearningRecordNotFoundError: If not present.
        """
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                raise LearningRecordNotFoundError(record_id)
            return record

    def get_by_category(self, category: LearningCategory) -> list[LearningRecord]:
        """Return all records matching ``category``, in insertion order."""
        with self._lock:
            return [r for r in self._records.values() if r.category == category]

    def get_by_subject(self, subject: str) -> list[LearningRecord]:
        """Return all records matching ``subject``, in insertion order."""
        with self._lock:
            return [r for r in self._records.values() if r.subject == subject]

    def get_all(self) -> list[LearningRecord]:
        """Return all learning records in insertion order."""
        with self._lock:
            return list(self._records.values())

    def remove(self, record_id: str) -> None:
        """Remove the record with ``record_id`` if present. No-op otherwise."""
        with self._lock:
            record = self._records.pop(record_id, None)
            if record is not None:
                self._index.pop((record.category, record.subject), None)

    def clear(self) -> None:
        """Remove all learning records."""
        with self._lock:
            self._records.clear()
            self._index.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        with self._lock:
            return record_id in self._records
