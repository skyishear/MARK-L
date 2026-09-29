"""MARK L v8.37 — Neutral Tool-Calling Types (types only).

Provider-neutral value types for model tool calling:

* ``ToolCall(call_id, name, arguments)`` — one tool call proposed by a
  model (untrusted input);
* ``ToolCallResult(call_id, name, output)`` — the model-facing result of
  one ``ToolCall``, correlated by ``call_id`` (and ``name``, which some
  providers key results by);
* ``validate_tool_calls(calls)`` — checks an ordered sequence of calls.

These are **types only**. They are distinct from the execution-side
``ToolRequest`` / ``ToolResult`` (authorized input and router output):
converting between the two, provider mapping, execution, authorization,
model tool selection and runtime loops belong to later milestones. Tool
declarations reuse the existing ``ToolSpec`` metadata; there is no separate
declaration type. No failure / error field yet (deferred to owner decision
O2).

Identity: ``call_id`` is required, opaque and stored verbatim; this module
never generates identifiers. ``call_id`` values must be unique within one
validated sequence.

``arguments`` must be a mapping with ``str`` keys whose values are,
recursively, JSON-compatible: ``str``, ``int``, ``float``, ``bool``,
``None``, lists / tuples, or mappings with ``str`` keys. The stored value is
a deep read-only copy (mappings behind ``MappingProxyType``, arrays as
tuples) that never aliases the caller's objects.

Standard library only; no provider, routing, registry, catalog, execution
or Agent dependency; no I/O, no state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

__all__ = ["ToolCall", "ToolCallResult", "validate_tool_calls"]


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _freeze_json(value: object, path: str) -> object:
    """Validate ``value`` as JSON-compatible and return a deep read-only copy."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: mapping keys must be strings")
            frozen[key] = _freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{path}[{i}]") for i, item in enumerate(value))
    raise TypeError(f"{path}: unsupported value type {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One model-proposed tool call (provider-neutral, immutable)."""

    call_id: str
    name: str
    arguments: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        _require_text("call_id", self.call_id)
        _require_text("name", self.name)
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments must be a mapping")
        object.__setattr__(self, "arguments", _freeze_json(self.arguments, "arguments"))


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """The model-facing result of one ``ToolCall`` (provider-neutral, immutable)."""

    call_id: str
    name: str
    output: str

    def __post_init__(self) -> None:
        _require_text("call_id", self.call_id)
        _require_text("name", self.name)
        if not isinstance(self.output, str):
            raise TypeError("output must be a str")


def validate_tool_calls(calls: Sequence[ToolCall]) -> tuple[ToolCall, ...]:
    """Validate an ordered sequence of ``ToolCall`` objects.

    Returns the calls as a tuple in their original order.

    Raises:
        TypeError: ``calls`` is not a sequence (a ``str`` is rejected) or an
            item is not a ``ToolCall``.
        ValueError: two calls share a ``call_id``.
    """
    if isinstance(calls, (str, bytes)) or not isinstance(calls, Sequence):
        raise TypeError("calls must be a sequence of ToolCall")
    seen: set[str] = set()
    for index, call in enumerate(calls):
        if not isinstance(call, ToolCall):
            raise TypeError(f"calls[{index}] is not a ToolCall: {type(call).__name__}")
        if call.call_id in seen:
            raise ValueError(f"duplicate call_id: {call.call_id!r}")
        seen.add(call.call_id)
    return tuple(calls)
