"""MARK L v8.42 — Production Memory Bridge (read-only, one-way).

Copies the production long-term memory (the SQLite store behind
``memory.core_memory``) into the Agent's in-process ``MemoryEngine`` so the v8.x
memory injection can see it (owner decisions OD-4, OD-5; contract P4). The two
memories otherwise stay separate: nothing is ever written back to the production
store and nothing here is persisted.

* **O3 is honoured at the door.** Only a row whose ``sensitive`` flag is
  explicitly non-sensitive (``False`` or the integer ``0``) is copied; a row that
  is sensitive, or whose flag is missing, ``None`` or anything else, is treated as
  sensitive and is never copied, so it can never reach a request.
* **Idempotent.** An entry that is already in the engine with the same category,
  key, project and value (``source="production_memory"``) is left alone, so a
  second import adds nothing. A value that changed in production is added as a
  new entry; the engine has no update or per-source delete, and the older entry
  stays until the process ends (the import is a snapshot, not a mirror).
* **Rows come from the caller** (the Agent passes the production reader), so this
  leaf performs no database access and imports no ``core`` module.

Dependency direction:

    Agent  →  production_memory  →  stdlib
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["ProductionMemoryImport", "SOURCE", "import_production_memory"]

SOURCE = "production_memory"


@dataclass(frozen=True, slots=True)
class ProductionMemoryImport:
    """What one import did (counts only; no memory content)."""

    imported: int
    unchanged: int
    skipped_sensitive: int
    skipped_invalid: int


def _explicitly_non_sensitive(flag: object) -> bool:
    return flag is False or (isinstance(flag, int) and not isinstance(flag, bool) and flag == 0)


def import_production_memory(engine: Any, rows: Iterable[Mapping[str, Any]]) -> ProductionMemoryImport:
    """Copy the explicitly non-sensitive ``rows`` into ``engine`` and report counts.

    ``rows`` are mappings with the production columns (``category``, ``key``,
    ``value``, ``importance``, ``confidence``, ``project``, ``memory_type``,
    ``sensitive``). A row the engine rejects is counted as invalid and skipped.
    """
    imported = unchanged = skipped_sensitive = skipped_invalid = 0
    for row in rows:
        if not _explicitly_non_sensitive(row.get("sensitive")):
            skipped_sensitive += 1
            continue
        category, key, value = row.get("category"), row.get("key"), row.get("value")
        project = row.get("project") or None
        if (
            isinstance(category, str) and isinstance(key, str) and isinstance(value, str)
            and any(
                entry["key"] == key and entry["value"] == value and entry["project"] == project
                and entry["source"] == SOURCE
                for entry in engine.recall(category=category, project=project, limit=max(engine.count(), 1))
            )
        ):
            unchanged += 1
            continue
        try:
            engine.remember(
                category,
                key,
                value,
                importance=row.get("importance", 3),
                confidence=row.get("confidence", 1.0),
                source=SOURCE,
                project=project,
                memory_type=row.get("memory_type") or "permanent",
                sensitive=False,
            )
        except (ValueError, TypeError):
            skipped_invalid += 1
            continue
        imported += 1
    return ProductionMemoryImport(imported, unchanged, skipped_sensitive, skipped_invalid)
