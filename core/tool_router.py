"""MARK L v8.14 — Tool Router.

A thin, deterministic, read-only resolver/invoker over the v8.12
``ToolRegistry``: given a ``ToolRequest``, look up ``request.tool_name``
in the injected registry and invoke the exact registered tool with the
exact request. No fallback, no retry, no policy, no caching, no
history, no logging, no async, no skill adaptation, no registration.

The router owns no mutable state (only the injected registry
reference), so it is thread-safe by construction; all state lives in
the registry and the tools themselves.

Dependency direction:

    caller  →  ToolRouter  →  ToolRegistry  →  ToolInterface tool   (allowed)
    ToolRouter  →  skill_registry / agent / anything else           (forbidden)
"""

from __future__ import annotations

from core.tool_interface import ToolRequest, ToolResult
from core.tool_registry import ToolRegistry


class ToolNotFoundError(ValueError):
    """Raised when ``request.tool_name`` is not registered."""


class ToolRouter:
    """Resolve a ``ToolRequest`` through a ``ToolRegistry`` and invoke it.

    Public API:
        ``route(request)``, ``registry`` (read-only).

    ``route`` passes the *same* request object to the registered tool
    and returns the *same* ``ToolResult`` object the tool produced.
    Exceptions raised by the tool propagate unchanged. The router never
    mutates the request or the registry and never consults the legacy
    skill registry.
    """

    __slots__ = ("_registry",)

    def __init__(self, tool_registry: ToolRegistry) -> None:
        if not isinstance(tool_registry, ToolRegistry):
            raise TypeError("tool_registry must be a ToolRegistry")
        self._registry = tool_registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def route(self, request: ToolRequest) -> ToolResult:
        """Invoke the tool registered under ``request.tool_name``.

        Raises:
            TypeError: ``request`` is not a ``ToolRequest``.
            ToolNotFoundError: no tool is registered under that name.
            Exception: whatever the tool's ``invoke`` raises, unchanged.
        """
        if not isinstance(request, ToolRequest):
            raise TypeError("request must be a ToolRequest")
        tool = self._registry.get(request.tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Tool not registered: {request.tool_name}")
        return tool.invoke(request)


__all__ = [
    "ToolNotFoundError",
    "ToolRouter",
]
