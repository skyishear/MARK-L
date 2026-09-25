"""MARK L — Memory Engine (v8.0 — in-process, no persistence).

A small, deterministic, in-process memory engine that satisfies
the ``remember`` / ``recall`` / ``forget`` contract consumed by
``core.agent.memory_adapter`` and ``core.problem_solver``.

This is the **first** Memory Engine milestone: it provides the API
surface, validation, ordering, and filtering that every later
implementation (persistence, embeddings, vector search) will share.
It does not persist across processes, it does not use embeddings,
it does not perform async I/O, and it does not depend on any
external service. It is a pure in-memory store with deterministic
iteration order.

Public API:

- ``MemoryEngine.remember(category, key, value, ...) -> str``
- ``MemoryEngine.recall(query=None, category=None, project=None,
  memory_type=None, limit=25) -> list[dict]``
- ``MemoryEngine.forget(key=None, category=None, project=None) -> int``
- ``MemoryEngine.count() -> int``
- ``MemoryEngine.clear() -> None``
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Optional


class MemoryEngine:
    """Thread-safe, in-process memory engine.

    No persistence, no embeddings, no async, no I/O. Every entry is a
    dict with the following canonical shape:

        {
            "id":          <str, uuid4>,
            "category":    <str>,
            "key":         <str>,
            "value":       <str>,
            "importance":  <int, 1..5>,
            "confidence":  <float, 0..1>,
            "source":      <str>,
            "project":     <str | None>,
            "memory_type": <str>,
            "sensitive":   <bool>,
            "ttl_days":    <int | None>,
            "created_at":  <float, monotonic timestamp>,
        }
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    # ── Write ────────────────────────────────────────────────────────────

    def remember(
        self,
        category: str,
        key: str,
        value: str,
        *,
        importance: int = 3,
        confidence: float = 1.0,
        source: str = "engine",
        project: Optional[str] = None,
        memory_type: str = "permanent",
        sensitive: bool = False,
        ttl_days: Optional[int] = None,
    ) -> str:
        """Store one entry and return its id.

        Raises ``ValueError`` for invalid inputs.
        """
        if not isinstance(category, str) or not category.strip():
            raise ValueError("category must be a non-empty string")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("key must be a non-empty string")
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        if not isinstance(importance, int) or not (1 <= importance <= 5):
            raise ValueError("importance must be an int in [1, 5]")
        if not isinstance(confidence, (int, float)) or not (
            0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError("confidence must be a number in [0.0, 1.0]")

        entry = {
            "id": uuid.uuid4().hex,
            "category": category,
            "key": key,
            "value": value,
            "importance": importance,
            "confidence": float(confidence),
            "source": source,
            "project": project,
            "memory_type": memory_type,
            "sensitive": bool(sensitive),
            "ttl_days": ttl_days,
            "created_at": _now(),
        }
        with self._lock:
            self._entries.append(entry)
        return entry["id"]

    # ── Read ─────────────────────────────────────────────────────────────

    def recall(
        self,
        *,
        query: Optional[str] = None,
        category: Optional[str] = None,
        project: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        """Return entries matching the supplied filters (AND), in
        insertion order. ``query`` does a case-insensitive substring
        match against ``key`` and ``value``.
        """
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive int")
        with self._lock:
            snapshot = list(self._entries)
        out: list[dict[str, Any]] = []
        q = query.lower() if isinstance(query, str) and query else None
        for e in snapshot:
            if category is not None and e["category"] != category:
                continue
            if project is not None and e["project"] != project:
                continue
            if memory_type is not None and e["memory_type"] != memory_type:
                continue
            if q is not None:
                hay = f"{e['key']}\n{e['value']}".lower()
                if q not in hay:
                    continue
            out.append(dict(e))
            if len(out) >= limit:
                break
        return out

    # ── Delete ───────────────────────────────────────────────────────────

    def forget(
        self,
        *,
        key: Optional[str] = None,
        category: Optional[str] = None,
        project: Optional[str] = None,
    ) -> int:
        """Delete entries matching the supplied filters (AND). Returns
        the number of entries removed. At least one filter is
        required.
        """
        if not any([key, category, project]):
            raise ValueError("at least one of key/category/project is required")
        removed = 0
        with self._lock:
            keep: list[dict[str, Any]] = []
            for e in self._entries:
                if key is not None and e["key"] != key:
                    keep.append(e)
                    continue
                if category is not None and e["category"] != category:
                    keep.append(e)
                    continue
                if project is not None and e["project"] != project:
                    keep.append(e)
                    continue
                removed += 1
            self._entries = keep
        return removed

    # ── Introspection ────────────────────────────────────────────────────

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _now() -> float:
    import time
    return time.monotonic()


__all__ = ["MemoryEngine"]