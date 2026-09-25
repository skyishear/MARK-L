"""MARK L v8.17 — Tool Dispatch Decision (read-only).

Pure, deterministic decision layer between a v8.12 ``ToolRegistry``
lookup and any actual routing. Given a ready task's ``tool_name`` and
an explicitly injected registry, this module produces an immutable
``ToolDispatchDecision`` describing what *would* happen on dispatch —
it never routes, never invokes a tool, never touches the legacy skill
registry, and never calls an AI provider.

This is the v8.x counterpart of the frozen ``core.skill_dispatch``
(which hard-wires ``core.skill_registry.is_registered``). Here the
registration predicate is ``registry.has(tool_name)`` on the injected
collaborator, so the two runtimes stay fully separate.

Dependency direction:

    Agent / callers  →  tool_dispatch  →  tool_registry  →  (v8.11 contract)
    tool_dispatch  →  agent / skill_dispatch / skill_registry   (forbidden)
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

from core.tool_registry import ToolRegistry

__all__ = ["ToolDispatchDecision", "build_tool_dispatch_decision"]


@dataclass(frozen=True, slots=True)
class ToolDispatchDecision:
    """Immutable, deterministic dispatch decision for one ready task.

    ``would_dispatch`` is the *decision* (True if ``tool_name`` is
    registered in the injected ``ToolRegistry``, False otherwise) —
    not the act. No tool is invoked, no router is called. ``context``
    is informational only (e.g. ``{"project": ...}``); nothing in the
    v8.x tool stack consumes it.
    """

    task_id: str
    tool_name: str
    is_registered: bool
    would_dispatch: bool
    action: str  # "dispatch" | "skip"
    context: Mapping[str, object]


def build_tool_dispatch_decision(
    task_id: str,
    tool_name: str,
    *,
    registry: ToolRegistry,
    context: Optional[Mapping[str, object]] = None,
) -> ToolDispatchDecision:
    """Build the immutable dispatch decision for one ready task.

    Pure function of ``task_id``, ``tool_name``, the registry's current
    membership (via ``registry.has``) and the optional ``context``
    mapping, which is copied into a read-only ``MappingProxyType`` so
    the decision cannot be mutated through the caller's reference.

    Raises:
        TypeError: ``registry`` is not a ``ToolRegistry``.
        ValueError: ``task_id`` / ``tool_name`` blank or not ``str``,
            or ``context`` not a mapping.
    """
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name must be a non-empty string")
    if context is not None and not isinstance(context, Mapping):
        raise ValueError("context must be a mapping or None")
    registered = registry.has(tool_name)
    frozen_ctx = MappingProxyType(dict(context) if context else {})
    return ToolDispatchDecision(
        task_id=task_id,
        tool_name=tool_name,
        is_registered=registered,
        would_dispatch=registered,
        action="dispatch" if registered else "skip",
        context=frozen_ctx,
    )
