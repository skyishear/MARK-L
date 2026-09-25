"""MARK L v8.13 — Skill → Tool Adapter (boundary layer).

Converts the legacy ``core.skill_registry.SkillManifest`` model (one
handler shared by N Gemini-style tool declaration dicts) into v8.11
``ToolInterface`` objects: **one declaration → one ``SkillTool``**.
Pure conversion only — no registration, no routing, no dispatch, no
execution infrastructure, no error recovery, no I/O.

The adapter never calls the legacy registry's registration, dispatch
or discovery functions and never touches its module-level state, so a
manifest does **not** have to be registered to be adapted and the
legacy runtime is unaffected. Registration into the v8.12 registry is
the caller's responsibility.

Context
-------
Legacy handlers take ``(tool_name, args, ctx)``. ``ToolRequest``
carries only ``tool_name`` + ``arguments``, so **request-scoped
context is not representable under the current ``ToolRequest``
contract** and is intentionally outside this milestone. ``context``
is captured once at adaptation time as a read-only, structurally
copied mapping whose *values* keep their original identity (live
runtime objects such as a UI handle must be passed by reference).

Mutation semantics (asymmetric, by design)
------------------------------------------
* ``name`` / ``description`` are captured at adaptation time — later
  edits to ``manifest.tools`` do **not** re-key existing ``SkillTool``s.
* ``manifest.handler`` is resolved at **invocation** time — swapping it
  after adaptation *does* affect subsequent invocations, matching the
  legacy ``dispatch`` late-binding behaviour.

Dependency direction:

    caller / future router  →  skill_tool_adapter                  (allowed)
    skill_tool_adapter  →  tool_interface, skill_registry (type)   (allowed)
    skill_tool_adapter  →  v8.12 registry / agent / anything else  (forbidden)
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Optional

from core.skill_registry import SkillManifest
from core.tool_interface import ToolRequest, ToolResult


class SkillTool:
    """A ``ToolInterface``-conforming view over one skill declaration.

    Holds a reference to the original manifest (not a copy), the
    captured ``name`` / ``description``, and the read-only
    adaptation-time ``context``. Contains no mutable adapter-owned
    runtime state: no lock, no counters, no caches. Concurrent
    invocation safety remains the underlying handler's responsibility,
    exactly as with legacy ``dispatch``.
    """

    __slots__ = ("_manifest", "_name", "_description", "_context")

    def __init__(
        self,
        manifest: SkillManifest,
        name: str,
        description: str,
        context: Mapping[str, object],
    ) -> None:
        self._manifest = manifest
        self._name = name
        self._description = description
        self._context = context

    # ── ToolInterface members ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def invoke(self, request: ToolRequest) -> ToolResult:
        """Invoke the manifest's *current* handler for this declaration.

        Raises:
            ValueError: ``request.tool_name`` differs from this tool's
                captured name (the handler is never invoked).
            Exception: whatever the handler raises, propagated unchanged
                (not wrapped in ``ToolError``).
        """
        if request.tool_name != self._name:
            raise ValueError(
                f"request.tool_name {request.tool_name!r} does not match "
                f"tool name {self._name!r}"
            )
        # Fresh mutable dict per call: handlers may mutate ``args``
        # (legacy contract) without touching the frozen request or
        # leaking into other invocations.
        result = self._manifest.handler(
            self._name, dict(request.arguments), self._context
        )
        if result is None:
            output = ""
        elif isinstance(result, str):
            output = result
        else:
            output = str(result)
        return ToolResult(tool_name=self._name, output=output)

    # ── Introspection ───────────────────────────────────────────────────

    @property
    def manifest(self) -> SkillManifest:
        return self._manifest

    @property
    def context(self) -> Mapping[str, object]:
        return self._context


def adapt_skill_manifest(
    manifest: SkillManifest,
    *,
    context: Optional[Mapping[str, object]] = None,
) -> tuple[SkillTool, ...]:
    """Adapt every declaration in ``manifest.tools`` to a ``SkillTool``.

    Returns one ``SkillTool`` per declaration, in declaration order
    (``()`` when there are none). Duplicate names inside one manifest
    are passed through unchanged — collision detection belongs to the
    v8.12 registry at registration time, as it does for legacy
    registration.

    Raises:
        TypeError: ``manifest`` lacks ``tools`` / ``handler``, ``tools``
            is not a list/tuple of mappings, or ``handler`` is not
            callable.
        ValueError: a declaration's ``name`` is missing, blank or not a
            ``str``; or its ``description`` is not a ``str``; or
            ``context`` is not a mapping.
    """
    if not hasattr(manifest, "tools") or not hasattr(manifest, "handler"):
        raise TypeError("manifest must define 'tools' and 'handler'")
    tools = manifest.tools
    if not isinstance(tools, (list, tuple)):
        raise TypeError("manifest.tools must be a list or tuple of declarations")
    if not callable(manifest.handler):
        raise TypeError("manifest.handler must be callable")
    if context is None:
        frozen_context: Mapping[str, object] = MappingProxyType({})
    elif isinstance(context, Mapping):
        # Structural copy behind a read-only view; values keep identity.
        frozen_context = MappingProxyType(dict(context))
    else:
        raise ValueError("context must be a mapping or None")

    adapted: list[SkillTool] = []
    for index, declaration in enumerate(tools):
        if not isinstance(declaration, Mapping):
            raise TypeError(f"manifest.tools[{index}] must be a mapping")
        name = declaration.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"manifest.tools[{index}] must declare a non-empty string 'name'"
            )
        description = declaration.get("description", "")
        if not isinstance(description, str):
            raise ValueError(
                f"manifest.tools[{index}] 'description' must be a str"
            )
        adapted.append(SkillTool(manifest, name, description, frozen_context))
    return tuple(adapted)


__all__ = [
    "SkillTool",
    "adapt_skill_manifest",
]
