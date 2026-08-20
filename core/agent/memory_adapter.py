"""Integration adapter bridging Foundation-module records to MemoryEngine.

Part of MARK L V3 Phase 2 (Integration), Step 3.

This adapter is fully decoupled from both the Foundation modules
(HistoryManager, ContextManager, KnowledgeManager, LearningManager,
MemoryIndexManager, ReflectionManager, ReasoningManager, Agent) and
MemoryEngine (core_memory.py):

- It never imports ``memory.core_memory`` or any ``core.*`` Foundation
  module. MemoryEngine's ``remember`` / ``recall`` / ``forget``
  functions are supplied by the caller as plain callables (dependency
  injection), so this module has zero import-time coupling to either
  side.
- It performs no category inference or mapping. The destination
  MemoryEngine category is a required, caller-supplied argument on
  every call — this module never guesses or defaults it.
- It performs no automatic or background persistence. Every write is
  a single, explicit call initiated by the caller; this module does
  not read from, poll, or subscribe to any Foundation module on its
  own.
- It is pure passthrough plus light validation: arguments in, the
  injected function's return value out, unchanged.

The caller is responsible for deciding whether a given Foundation
record should be persisted, which MemoryEngine category it belongs
to, extracting the key/value/metadata to persist from that record,
and when persistence should occur.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

RememberFn = Callable[..., str]
RecallFn = Callable[..., list[dict[str, Any]]]
ForgetFn = Callable[..., int]


class MemoryAdapterError(RuntimeError):
    """Raised when a call made through the adapter is invalid or fails."""


def persist_to_memory_engine(
    remember_fn: RememberFn,
    category: str,
    key: str,
    value: str,
    *,
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "adapter",
    project: str | None = None,
    memory_type: str = "permanent",
    sensitive: bool = False,
    ttl_days: int | None = None,
) -> str:
    """Persist a single (category, key, value) entry via ``remember_fn``.

    This function makes no decision about what to persist, which
    category to use, or when to persist — that is entirely the
    caller's responsibility. It only validates presence of the
    required fields and forwards the call.

    Args:
        remember_fn: MemoryEngine's ``remember`` function, or any
            compatible callable, injected by the caller. Never
            imported directly by this module.
        category: Destination MemoryEngine category. Required,
            caller-supplied. This adapter performs no inference or
            default mapping of categories — MemoryEngine itself
            remains the source of truth for valid category names.
        key: Destination MemoryEngine key.
        value: Destination MemoryEngine value.
        importance: Forwarded to ``remember_fn`` unchanged.
        confidence: Forwarded to ``remember_fn`` unchanged.
        source: Forwarded to ``remember_fn`` unchanged.
        project: Forwarded to ``remember_fn`` unchanged.
        memory_type: Forwarded to ``remember_fn`` unchanged.
        sensitive: Forwarded to ``remember_fn`` unchanged.
        ttl_days: Forwarded to ``remember_fn`` unchanged.

    Returns:
        Whatever ``remember_fn`` returns, unchanged.

    Raises:
        MemoryAdapterError: If ``category``, ``key``, or ``value`` is
            empty/blank, or if ``remember_fn`` raises.
    """
    if not category or not category.strip():
        raise MemoryAdapterError("category must be a non-empty string")
    if not key or not key.strip():
        raise MemoryAdapterError("key must be a non-empty string")
    if not value or not str(value).strip():
        raise MemoryAdapterError("value must be a non-empty string")

    try:
        return remember_fn(
            category,
            key,
            value,
            importance=importance,
            confidence=confidence,
            source=source,
            project=project,
            memory_type=memory_type,
            sensitive=sensitive,
            ttl_days=ttl_days,
        )
    except Exception as exc:
        raise MemoryAdapterError(f"remember_fn failed: {exc}") from exc


def query_memory_engine(
    recall_fn: RecallFn,
    *,
    query: str | None = None,
    category: str | None = None,
    project: str | None = None,
    memory_type: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Query MemoryEngine via the injected ``recall_fn``.

    Pure passthrough — this adapter applies no filtering, category
    inference, or transformation of the result.

    Args:
        recall_fn: MemoryEngine's ``recall`` function, or any
            compatible callable, injected by the caller. Never
            imported directly by this module.
        query: Forwarded to ``recall_fn`` unchanged.
        category: Forwarded to ``recall_fn`` unchanged.
        project: Forwarded to ``recall_fn`` unchanged.
        memory_type: Forwarded to ``recall_fn`` unchanged.
        limit: Forwarded to ``recall_fn`` unchanged.

    Returns:
        Whatever ``recall_fn`` returns, unchanged.

    Raises:
        MemoryAdapterError: If ``recall_fn`` raises.
    """
    try:
        return recall_fn(
            query=query,
            category=category,
            project=project,
            memory_type=memory_type,
            limit=limit,
        )
    except Exception as exc:
        raise MemoryAdapterError(f"recall_fn failed: {exc}") from exc


def remove_from_memory_engine(
    forget_fn: ForgetFn,
    *,
    key: str | None = None,
    category: str | None = None,
    project: str | None = None,
) -> int:
    """Delete matching entries from MemoryEngine via the injected ``forget_fn``.

    Pure passthrough. At least one filter is required, matching
    MemoryEngine's own ``forget`` contract — this adapter does not
    alter that contract, only enforces it before forwarding the call.

    Args:
        forget_fn: MemoryEngine's ``forget`` function, or any
            compatible callable, injected by the caller. Never
            imported directly by this module.
        key: Forwarded to ``forget_fn`` unchanged.
        category: Forwarded to ``forget_fn`` unchanged.
        project: Forwarded to ``forget_fn`` unchanged.

    Returns:
        Whatever ``forget_fn`` returns, unchanged.

    Raises:
        MemoryAdapterError: If no filter is supplied, or if
            ``forget_fn`` raises.
    """
    if not any([key, category, project]):
        raise MemoryAdapterError("at least one of key/category/project is required")
    try:
        return forget_fn(key=key, category=category, project=project)
    except Exception as exc:
        raise MemoryAdapterError(f"forget_fn failed: {exc}") from exc
