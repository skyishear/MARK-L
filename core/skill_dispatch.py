"""MARK L v5.0 — Controlled Skill Dispatch Decision (read-only).

Pure, deterministic decision layer between the existing SkillRegistry
check (``is_registered``) and any future actual dispatch. Given a
ready task's ``tool_name``, this module produces an immutable
``SkillDispatchDecision`` describing what *would* happen on dispatch —
it never invokes ``core.skill_registry.dispatch``, never executes a
handler, never touches MemoryEngine, and never calls an AI provider.

It depends only on the existing ``core.skill_registry`` API. It does
not import execution, planning, or foundation modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from core.skill_registry import is_registered

__all__ = ["SkillDispatchDecision", "build_dispatch_decision"]


@dataclass(frozen=True, slots=True)
class SkillDispatchDecision:
    """Immutable, deterministic decision for one ready task.

    ``would_dispatch`` is the *decision* (True if a matching skill is
    registered, False otherwise) — not the act. No handler is ever
    invoked, no AI provider is ever called, no Memory write happens.
    """

    task_id: str
    tool_name: str
    is_registered: bool
    would_dispatch: bool
    action: str  # "dispatch" | "skip"
    context: Mapping[str, object]


def build_dispatch_decision(
    task_id: str,
    tool_name: str,
    *,
    context: Mapping[str, object] | None = None,
) -> SkillDispatchDecision:
    """Build the immutable dispatch decision for one ready task.

    Pure function of ``task_id``, ``tool_name``, and (optionally) the
    caller-supplied ``context`` mapping — which is copied into a
    read-only ``MappingProxyType`` so the decision cannot be mutated
    through the caller's reference. No side effects.
    """
    registered = is_registered(tool_name)
    frozen_ctx = MappingProxyType(dict(context) if context else {})
    return SkillDispatchDecision(
        task_id=task_id,
        tool_name=tool_name,
        is_registered=registered,
        would_dispatch=registered,
        action="dispatch" if registered else "skip",
        context=frozen_ctx,
    )