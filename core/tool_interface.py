"""MARK L v8.11 — Tool Interface (contract + minimal mock).

Single-responsibility, implementation-agnostic contract representing
one invokable tool. Supports exactly one synchronous
request/response operation. No registry, no routing, no adapters,
no schemas, no permissions, no retries, no async, no persistence,
no logging, no networking, no subprocesses, no filesystem access.

This module is intentionally minimal and is a **leaf**: it depends on
nothing in ``core.*`` other than the standard library, so it stays
independent from Agent, AIService, Skill Registry, Planning, Memory,
Reflection, the legacy execution stack and the v8.x Foundation
stores. It coexists with — and does not touch — the pre-existing
``core.skill_registry`` vocabulary, where a "tool" is a declaration
dict owned by a ``SkillManifest``; bridging the two is a future
adapter concern, not this module's.

Dependency direction:

    future adapters / registries / Agent  →  ToolInterface   (allowed)
    ToolInterface  →  anything in core.*                     (forbidden)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Implementation-agnostic invocation payload.

    ``tool_name`` identifies the tool being invoked; ``arguments`` is
    an arbitrary mapping copied into a read-only view so the request
    can never be mutated through the caller's reference or through
    the request object itself.
    """

    tool_name: str
    arguments: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("arguments must be a mapping")
        # Defensive copy behind a read-only view (frozen dataclass, so
        # assign through object.__setattr__ once, here).
        object.__setattr__(
            self, "arguments", MappingProxyType(dict(self.arguments))
        )


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Implementation-agnostic result payload.

    ``output`` is the tool's textual result; ``tool_name`` records
    which tool produced it (for introspection/tests).
    """

    tool_name: str
    output: str


class ToolError(Exception):
    """Raised by a tool implementation when an invocation fails."""


class ToolInterface(Protocol):
    """Minimal tool interface.

    A single synchronous ``invoke`` operation mapping a
    ``ToolRequest`` to a ``ToolResult``. Implementations should be
    deterministic given the same request (deterministic mock) or
    document their non-determinism (real tools). Failures are
    signalled by raising ``ToolError``.

    The interface deliberately exposes no I/O, network or async
    surface — concrete tools wire those concerns themselves behind
    this boundary.
    """

    name: str
    description: str

    def invoke(self, request: ToolRequest) -> ToolResult:
        ...


class StaticMockTool:
    """Deterministic, side-effect-free reference implementation.

    Returns the configured ``output`` verbatim for every request.
    Optional ``echo`` mode instead renders the request as
    ``"<tool_name>(k1=v1, k2=v2)"`` with keys sorted, which makes it
    useful for testing argument passthrough. ``call_count`` records
    how many invocations were made so tests can assert that no tool
    call leaked.
    """

    def __init__(
        self,
        output: str = "mock-output",
        *,
        echo: bool = False,
        name: str = "mock",
        description: str = "Deterministic mock tool.",
    ) -> None:
        self._output = output
        self._echo = echo
        self.name = name
        self.description = description
        self.call_count = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.call_count += 1
        if self._echo:
            rendered = ", ".join(
                f"{key}={request.arguments[key]!r}"
                for key in sorted(request.arguments)
            )
            output = f"{request.tool_name}({rendered})"
        else:
            output = self._output
        return ToolResult(tool_name=request.tool_name, output=output)


__all__ = [
    "StaticMockTool",
    "ToolError",
    "ToolInterface",
    "ToolRequest",
    "ToolResult",
]
