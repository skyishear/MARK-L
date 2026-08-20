"""Runtime context tracking for MARK L V3 Foundation.

ContextManager owns only the current runtime context. It has no
persistence, performs no long-term memory lookup, does no reference
resolution, and has no dependency on MemoryEngine, HistoryManager, or
any other module.
"""

from __future__ import annotations

import threading
from typing import Any


class ContextKeyNotFoundError(KeyError):
    """Raised when a required context key is missing."""


class ContextManager:
    """Thread-safe, in-memory store of current runtime context.

    Standalone infrastructure component: no persistence, no long-term
    memory, no reference resolution, no cross-module communication.
    """

    def __init__(self) -> None:
        """Initialize an empty context store."""
        self._context: dict[str, Any] = {}
        self._lock = threading.RLock()

    def set(self, key: str, value: Any) -> None:
        """Set a context value for the given key."""
        with self._lock:
            self._context[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key``, or ``default`` if not present."""
        with self._lock:
            return self._context.get(key, default)

    def require(self, key: str) -> Any:
        """Return the value for ``key``.

        Raises:
            ContextKeyNotFoundError: If ``key`` is not present.
        """
        with self._lock:
            if key not in self._context:
                raise ContextKeyNotFoundError(key)
            return self._context[key]

    def has(self, key: str) -> bool:
        """Return whether ``key`` is present in the current context."""
        with self._lock:
            return key in self._context

    def remove(self, key: str) -> None:
        """Remove ``key`` from the context if present. No-op otherwise."""
        with self._lock:
            self._context.pop(key, None)

    def update(self, mapping: dict[str, Any]) -> None:
        """Merge ``mapping`` into the current context, overwriting keys."""
        with self._lock:
            self._context.update(mapping)

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the current context state."""
        with self._lock:
            return dict(self._context)

    def clear(self) -> None:
        """Remove all context entries."""
        with self._lock:
            self._context.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._context)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._context
