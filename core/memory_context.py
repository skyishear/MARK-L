"""MARK L v8.36 — Memory Context (opt-in selection + rendering).

Provider-neutral helpers used by ``ContextManager`` to turn an explicit
``MemoryRequest`` into a deterministic textual memory block for the request's
system channel. Nothing here is automatic: memory is injected only when a
caller passes a ``MemoryRequest``.

Locked owner policy:

* source — only a ``core.memory_engine.MemoryEngine`` (any object exposing
  its ``recall`` / ``count`` API); never the legacy SQLite memory, the
  memory index, reflection, learning or knowledge stores;
* query — the current user prompt, through the existing
  ``MemoryEngine.recall`` (deterministic, insertion-ordered, case-insensitive
  substring match); optional ``category`` / ``project`` / ``memory_type``
  filters use recall's own semantics; no ranking, no embeddings, no search,
  no TTL handling (recall's behaviour is preserved as-is);
* **O3 — sensitive memory is never injected:** every candidate whose
  ``sensitive`` flag is not exactly ``False`` is dropped before rendering, so
  a sensitive memory can never reach ``AIRequest.system`` or any provider;
* at most ``10`` eligible memories, in recall order, no reordering;
* rendering is deterministic plain text, independent of any provider format.

No I/O, no state, no provider imports.

Dependency direction:

    ContextManager / AIService / Agent  →  memory_context  →  stdlib
    memory_context  →  anything in core.*   (forbidden)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

__all__ = ["MemoryRequest", "MemorySource", "render_memories", "select_memories"]

MAX_MEMORIES = 10


class MemorySource(Protocol):
    """The subset of the ``MemoryEngine`` API memory injection uses."""

    def recall(
        self,
        *,
        query: Optional[str] = None,
        category: Optional[str] = None,
        project: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        ...

    def count(self) -> int:
        ...


@dataclass(frozen=True, slots=True)
class MemoryRequest:
    """An explicit opt-in request to inject memories for one AI request."""

    source: MemorySource
    category: Optional[str] = None
    project: Optional[str] = None
    memory_type: Optional[str] = None

    def __post_init__(self) -> None:
        if not callable(getattr(self.source, "recall", None)) or not callable(
            getattr(self.source, "count", None)
        ):
            raise TypeError("source must provide the MemoryEngine recall() / count() API")
        for name in ("category", "project", "memory_type"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be a str or None")


def select_memories(request: MemoryRequest, prompt: str) -> tuple[Mapping[str, Any], ...]:
    """Return the first ``MAX_MEMORIES`` non-sensitive memories matching
    ``prompt`` under ``request``, in the source's recall order.

    Every recall match is retrieved (``limit`` = the source's size) so the
    sensitive filter never shrinks the eligible set below what recall would
    otherwise provide; sensitive entries are removed before anything is
    returned (O3, fail-closed: only an explicit ``sensitive is False`` passes).
    """
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a str")
    total = request.source.count()
    if total <= 0:
        return ()
    candidates = request.source.recall(
        query=prompt,
        category=request.category,
        project=request.project,
        memory_type=request.memory_type,
        limit=total,
    )
    eligible = [entry for entry in candidates if entry.get("sensitive") is False]
    return tuple(eligible[:MAX_MEMORIES])


def render_memories(entries: tuple[Mapping[str, Any], ...]) -> Optional[str]:
    """Render ``entries`` as a deterministic memory block, or ``None``.

    Format (one line per memory, in the given order)::

        Relevant memories:
        - [<category>] <key>: <value>
    """
    if not entries:
        return None
    lines = ["Relevant memories:"]
    for entry in entries:
        lines.append(f"- [{entry.get('category')}] {entry.get('key')}: {entry.get('value')}")
    return "\n".join(lines)
