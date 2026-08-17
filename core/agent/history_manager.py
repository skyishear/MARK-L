"""
core.agent.history_manager
==============================
History Manager for MARK L V3.

In-memory store of immutable history records (a chronological log of
actions/events, metadata only). No replay, no execution. Never
executes Runtime, RuntimeEngine, Executor, Planner, ToolManager,
browser, terminal, plugins, AI providers, or actions. No
persistence, no background threads, no polling, no dependency
injection.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class HistoryRecord:
    """One immutable history record."""

    category: str
    description: str
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


class HistoryManagerError(Exception):
    """Base exception for history manager errors."""


class InvalidHistoryRecordError(HistoryManagerError):
    """Raised when record() receives invalid arguments."""


@dataclass
class HistoryManager:
    """Thread-safe in-memory store of immutable history records."""

    _records: list[HistoryRecord] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def record(
        self,
        category: str,
        description: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> HistoryRecord:
        """Append a new immutable history record."""
        with self._lock:
            if not category or not category.strip():
                raise InvalidHistoryRecordError("category must be a non-empty string")
            if not description or not description.strip():
                raise InvalidHistoryRecordError(
                    "description must be a non-empty string"
                )
            entry = HistoryRecord(
                category=category,
                description=description,
                timestamp=self._now_iso(),
                metadata=metadata or {},
            )
            self._records.append(entry)
            return entry

    def get_history(
        self,
        category: Optional[str] = None,
    ) -> list[HistoryRecord]:
        """Return history records in chronological order, optionally filtered by category."""
        with self._lock:
            records = list(self._records)
            if category is not None:
                records = [r for r in records if r.category == category]
            return records

    def latest(self, category: Optional[str] = None) -> HistoryRecord:
        """Return the most recently recorded entry, optionally filtered by category."""
        with self._lock:
            records = self._records
            if category is not None:
                records = [r for r in records if r.category == category]
            if not records:
                raise HistoryManagerError(
                    f"No history records found"
                    + (f" for category: {category}" if category else "")
                )
            return records[-1]

    def clear(self) -> None:
        """Remove all stored history records."""
        with self._lock:
            self._records.clear()

    def summary(self) -> dict[str, Any]:
        """Compact snapshot of stored history record counts per category."""
        with self._lock:
            counts: dict[str, int] = {}
            for record in self._records:
                counts[record.category] = counts.get(record.category, 0) + 1
            return {"total": len(self._records), "counts": counts}

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
