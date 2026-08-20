"""Runtime reasoning trace tracking for MARK L V3 Foundation.

ReasoningManager owns only immutable runtime reasoning trace records
representing reasoning that has already occurred elsewhere. It does
NOT perform reasoning, generate decisions, evaluate options, or call
AI models. It does NOT replace ProblemSolver or MemoryEngine, and has
no dependency on any other module.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class ReasoningRecordNotFoundError(KeyError):
    """Raised when a requested reasoning record does not exist."""


class InvalidReasoningRecordError(ValueError):
    """Raised when reasoning record data fails validation."""


@dataclass(frozen=True, slots=True)
class ReasoningRecord:
    """A single immutable runtime reasoning trace record."""

    id: str
    problem_statement: str
    assumptions: tuple[str, ...]
    constraints: tuple[str, ...]
    considered_options: tuple[str, ...]
    selected_option: str
    rationale: str
    confidence_level: float
    outcome: str | None
    metadata: dict[str, Any]
    created_at: datetime


class ReasoningManager:
    """Thread-safe, in-memory container for runtime reasoning traces.

    Standalone infrastructure component: stores reasoning traces only —
    it performs no reasoning itself. No persistence, no planning, no
    reference resolution, no background processing, no cross-module
    communication.
    """

    def __init__(self) -> None:
        """Initialize an empty reasoning trace registry."""
        self._records: dict[str, ReasoningRecord] = {}
        self._lock = threading.RLock()

    def add_reasoning(
        self,
        problem_statement: str,
        assumptions: list[str] | None = None,
        constraints: list[str] | None = None,
        considered_options: list[str] | None = None,
        selected_option: str = "",
        rationale: str = "",
        confidence_level: float = 0.0,
        outcome: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReasoningRecord:
        """Record a trace of reasoning that has already occurred elsewhere.

        Args:
            problem_statement: The problem being reasoned about.
            assumptions: Assumptions made during reasoning.
            constraints: Constraints considered during reasoning.
            considered_options: Options that were considered.
            selected_option: The option that was selected.
            rationale: The rationale behind the selection.
            confidence_level: Self-assessed confidence, in ``[0.0, 1.0]``.
            outcome: Optional known outcome of the selected option.
            metadata: Optional additional metadata.

        Returns:
            The newly created, immutable ReasoningRecord.

        Raises:
            InvalidReasoningRecordError: If ``confidence_level`` is
                outside the inclusive range ``[0.0, 1.0]``.
        """
        if not 0.0 <= confidence_level <= 1.0:
            raise InvalidReasoningRecordError(
                f"confidence_level must be within [0.0, 1.0], got {confidence_level}"
            )

        record = ReasoningRecord(
            id=uuid.uuid4().hex,
            problem_statement=problem_statement,
            assumptions=tuple(assumptions or ()),
            constraints=tuple(constraints or ()),
            considered_options=tuple(considered_options or ()),
            selected_option=selected_option,
            rationale=rationale,
            confidence_level=confidence_level,
            outcome=outcome,
            metadata=dict(metadata) if metadata else {},
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._records[record.id] = record
        return record

    def record_outcome(self, record_id: str, outcome: str) -> ReasoningRecord:
        """Attach a known outcome to an existing reasoning record.

        Since records are immutable, this replaces the stored record
        (same id and all other fields) with a copy carrying the new
        outcome.

        Raises:
            ReasoningRecordNotFoundError: If ``record_id`` is not present.
        """
        with self._lock:
            existing = self._records.get(record_id)
            if existing is None:
                raise ReasoningRecordNotFoundError(record_id)
            updated = ReasoningRecord(
                id=existing.id,
                problem_statement=existing.problem_statement,
                assumptions=existing.assumptions,
                constraints=existing.constraints,
                considered_options=existing.considered_options,
                selected_option=existing.selected_option,
                rationale=existing.rationale,
                confidence_level=existing.confidence_level,
                outcome=outcome,
                metadata=existing.metadata,
                created_at=existing.created_at,
            )
            self._records[record_id] = updated
            return updated

    def get(self, record_id: str) -> ReasoningRecord | None:
        """Return the record for ``record_id``, or ``None``."""
        with self._lock:
            return self._records.get(record_id)

    def require(self, record_id: str) -> ReasoningRecord:
        """Return the record for ``record_id``.

        Raises:
            ReasoningRecordNotFoundError: If not present.
        """
        with self._lock:
            record = self._records.get(record_id)
            if record is None:
                raise ReasoningRecordNotFoundError(record_id)
            return record

    def get_all(self) -> list[ReasoningRecord]:
        """Return all reasoning records in insertion order."""
        with self._lock:
            return list(self._records.values())

    def remove(self, record_id: str) -> None:
        """Remove the record with ``record_id`` if present. No-op otherwise."""
        with self._lock:
            self._records.pop(record_id, None)

    def clear(self) -> None:
        """Remove all reasoning records."""
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        with self._lock:
            return record_id in self._records
