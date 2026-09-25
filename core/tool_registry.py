"""MARK L v8.12 — Tool Registry.

Owns registration and lookup for the v8.11 ``ToolInterface``
contract. No routing, no dispatch, no execution, no discovery, no
adapters, no persistence, no I/O. Depends only on
``core.tool_interface`` — isolated from Agent, AIService, Skill
Registry, Planning, Memory, Reflection, the legacy execution stack
and the v8.x Foundation stores.

Unlike the legacy ``core.skill_registry`` (module-level globals,
import-time side effects, filesystem discovery), every ``ToolRegistry``
is an independent in-process instance with no shared state.

Dependency direction:

    callers / future Agent / Router / adapters  →  ToolRegistry  (allowed)
    ToolRegistry  →  ToolInterface  →  stdlib                    (allowed)
    ToolRegistry  →  anything else in core.*                     (forbidden)
"""

from __future__ import annotations

import threading

from core.tool_interface import ToolInterface


class ToolAlreadyRegisteredError(ValueError):
    """Raised when a tool name is registered with a different instance."""


class ToolRegistry:
    """Deterministic, thread-safe, in-process registry of tools.

    Public API:
        ``register(tool)``, ``unregister(name)``, ``get(name)``,
        ``has(name)``, ``names()``, ``list_tools()``,
        ``clear()``, ``count()``.

    Tools are stored **by reference** — the exact caller-provided
    object, no wrapper, no copy — and keyed by the ``tool.name``
    captured at registration time. If the object's ``name`` is
    mutated afterwards the registry does **not** re-key: the original
    name remains the lookup key and ``names()`` is unchanged.

    Insertion order is preserved. ``names()`` / ``list_tools()`` return
    tuple snapshots that never expose internal containers. Duplicate
    names with a *different* instance raise; re-registering the *same*
    instance is an idempotent no-op that keeps its original position.
    The registry never calls ``invoke``.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolInterface] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    # ── Write ────────────────────────────────────────────────────────────

    def register(self, tool: ToolInterface) -> ToolInterface:
        """Register ``tool`` under its ``name`` attribute.

        Raises:
            TypeError: ``tool`` lacks ``name`` / ``description`` /
                callable ``invoke`` (the three ``ToolInterface``
                members), or ``description`` is not a ``str``.
            ValueError: ``name`` is blank or not a ``str``.
            ToolAlreadyRegisteredError: ``name`` is already held by a
                different instance.
        """
        name = self._validate_tool(tool)
        with self._lock:
            existing = self._tools.get(name)
            if existing is not None:
                if existing is tool:
                    return tool
                raise ToolAlreadyRegisteredError(
                    f"tool '{name}' is already registered"
                )
            self._tools[name] = tool
            self._order.append(name)
        return tool

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name not in self._tools:
                return False
            del self._tools[name]
            self._order.remove(name)
            return True

    def clear(self) -> None:
        with self._lock:
            self._tools.clear()
            self._order.clear()

    # ── Read ─────────────────────────────────────────────────────────────

    def get(self, name: str) -> ToolInterface | None:
        with self._lock:
            return self._tools.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._order)

    def list_tools(self) -> tuple[ToolInterface, ...]:
        with self._lock:
            return tuple(self._tools[name] for name in self._order)

    def count(self) -> int:
        with self._lock:
            return len(self._tools)

    def __len__(self) -> int:
        return self.count()

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _validate_tool(tool: object) -> str:
        # Structural check against exactly the three ToolInterface
        # members; no runtime_checkable Protocol, no inheritance.
        for member in ("name", "description", "invoke"):
            if not hasattr(tool, member):
                raise TypeError(f"tool must define '{member}'")
        if not callable(getattr(tool, "invoke")):
            raise TypeError("tool.invoke must be callable")
        if not isinstance(getattr(tool, "description"), str):
            raise TypeError("tool.description must be a str")
        name = getattr(tool, "name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool.name must be a non-empty string")
        return name


__all__ = [
    "ToolAlreadyRegisteredError",
    "ToolRegistry",
]
