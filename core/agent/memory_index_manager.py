"""Runtime indexing infrastructure for MARK L V3 Foundation.

MemoryIndexManager provides generic indexing and lookup infrastructure
only. It does NOT store memories or their content, and does NOT
replace MemoryEngine. It has no persistence and no dependency on any
other module. Higher-level systems may use it during the Integration
phase to index identifiers (e.g. from KnowledgeManager or
LearningManager) by arbitrary keys, without this module knowing
anything about what those identifiers represent.
"""

from __future__ import annotations

import threading


class MemoryIndexManager:
    """Thread-safe, in-memory bidirectional index of item ids to keys.

    Standalone infrastructure component: stores no memory content, only
    the association between opaque item ids and lookup keys. No
    persistence, no cross-module communication.
    """

    def __init__(self) -> None:
        """Initialize an empty index."""
        self._item_to_keys: dict[str, set[str]] = {}
        self._key_to_items: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    def index(self, item_id: str, keys: set[str]) -> None:
        """Associate ``item_id`` with each key in ``keys``.

        Existing associations for ``item_id`` are preserved; new keys
        are added alongside them. Calling with an empty ``keys`` set is
        a no-op.
        """
        if not keys:
            return
        with self._lock:
            existing = self._item_to_keys.setdefault(item_id, set())
            existing.update(keys)
            for key in keys:
                self._key_to_items.setdefault(key, set()).add(item_id)

    def unindex(self, item_id: str, keys: set[str] | None = None) -> None:
        """Remove ``item_id`` from the given ``keys``.

        Args:
            item_id: The item to remove associations for.
            keys: Specific keys to remove ``item_id`` from. If ``None``,
                ``item_id`` is removed from all of its current keys.
        """
        with self._lock:
            current_keys = self._item_to_keys.get(item_id)
            if current_keys is None:
                return
            target_keys = current_keys if keys is None else keys & current_keys
            for key in list(target_keys):
                current_keys.discard(key)
                items = self._key_to_items.get(key)
                if items is not None:
                    items.discard(item_id)
                    if not items:
                        del self._key_to_items[key]
            if not current_keys:
                del self._item_to_keys[item_id]

    def lookup(self, key: str) -> set[str]:
        """Return the set of item ids associated with ``key``."""
        with self._lock:
            return set(self._key_to_items.get(key, set()))

    def lookup_any(self, keys: set[str]) -> set[str]:
        """Return item ids associated with at least one key in ``keys``."""
        with self._lock:
            result: set[str] = set()
            for key in keys:
                result |= self._key_to_items.get(key, set())
            return result

    def lookup_all(self, keys: set[str]) -> set[str]:
        """Return item ids associated with every key in ``keys``.

        Returns an empty set if ``keys`` is empty.
        """
        if not keys:
            return set()
        with self._lock:
            sets = [self._key_to_items.get(key, set()) for key in keys]
            result = sets[0].copy()
            for s in sets[1:]:
                result &= s
            return result

    def keys_for(self, item_id: str) -> set[str]:
        """Return the set of keys currently associated with ``item_id``."""
        with self._lock:
            return set(self._item_to_keys.get(item_id, set()))

    def remove_item(self, item_id: str) -> None:
        """Remove ``item_id`` entirely from the index. No-op if absent."""
        self.unindex(item_id, keys=None)

    def clear(self) -> None:
        """Remove all index entries."""
        with self._lock:
            self._item_to_keys.clear()
            self._key_to_items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._item_to_keys)

    def __contains__(self, item_id: object) -> bool:
        with self._lock:
            return item_id in self._item_to_keys
