"""Runtime knowledge reference tracking for MARK L V3 Foundation.

KnowledgeManager owns only runtime knowledge references and their
metadata. It is NOT a long-term memory system, has no persistence, and
does not integrate with MemoryEngine, HistoryManager, ContextManager,
or any other module.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class KnowledgeReferenceNotFoundError(KeyError):
    """Raised when a requested knowledge reference does not exist."""


@dataclass(frozen=True, slots=True)
class KnowledgeReference:
    """A single immutable runtime knowledge reference."""

    id: str
    topic: str
    content: str
    source: str | None
    tags: frozenset[str]
    metadata: dict[str, Any]
    created_at: datetime


class KnowledgeManager:
    """Thread-safe, in-memory registry of runtime knowledge references.

    Standalone infrastructure component: no persistence, does not
    replace MemoryEngine, no cross-module communication.
    """

    def __init__(self) -> None:
        """Initialize an empty knowledge registry."""
        self._references: dict[str, KnowledgeReference] = {}
        self._lock = threading.RLock()

    def add(
        self,
        topic: str,
        content: str,
        source: str | None = None,
        tags: set[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeReference:
        """Register a new runtime knowledge reference.

        Args:
            topic: Short label identifying what the reference is about.
            content: The knowledge content itself.
            source: Optional origin of the knowledge (e.g. tool name).
            tags: Optional set of tags for categorization/lookup.
            metadata: Optional additional metadata.

        Returns:
            The newly created, immutable KnowledgeReference.
        """
        reference = KnowledgeReference(
            id=uuid.uuid4().hex,
            topic=topic,
            content=content,
            source=source,
            tags=frozenset(tags) if tags else frozenset(),
            metadata=dict(metadata) if metadata else {},
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._references[reference.id] = reference
        return reference

    def get(self, reference_id: str) -> KnowledgeReference | None:
        """Return the reference for ``reference_id``, or ``None``."""
        with self._lock:
            return self._references.get(reference_id)

    def require(self, reference_id: str) -> KnowledgeReference:
        """Return the reference for ``reference_id``.

        Raises:
            KnowledgeReferenceNotFoundError: If not present.
        """
        with self._lock:
            reference = self._references.get(reference_id)
            if reference is None:
                raise KnowledgeReferenceNotFoundError(reference_id)
            return reference

    def get_by_topic(self, topic: str) -> list[KnowledgeReference]:
        """Return all references matching ``topic``, in insertion order."""
        with self._lock:
            return [r for r in self._references.values() if r.topic == topic]

    def get_by_tag(self, tag: str) -> list[KnowledgeReference]:
        """Return all references containing ``tag``, in insertion order."""
        with self._lock:
            return [r for r in self._references.values() if tag in r.tags]

    def get_all(self) -> list[KnowledgeReference]:
        """Return all knowledge references in insertion order."""
        with self._lock:
            return list(self._references.values())

    def remove(self, reference_id: str) -> None:
        """Remove the reference with ``reference_id`` if present. No-op otherwise."""
        with self._lock:
            self._references.pop(reference_id, None)

    def clear(self) -> None:
        """Remove all knowledge references."""
        with self._lock:
            self._references.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._references)

    def __contains__(self, reference_id: object) -> bool:
        with self._lock:
            return reference_id in self._references
