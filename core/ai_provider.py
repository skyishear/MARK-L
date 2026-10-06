"""MARK L v6.0 — AI Provider Abstraction (interface + minimal mock).

Single-responsibility, provider-agnostic abstraction representing a
language model. Supports exactly one synchronous request/response
operation. No streaming, no routing, no fallback, no conversation
memory, no MCP, no tool calling, no autonomous planning.

This module is intentionally minimal. It depends on nothing in
``core.*`` beyond the provider-neutral value types it carries
(``ConversationHistory``; v8.38: ``ToolSpec`` declarations and ``ToolCall``),
so it stays independent from Planning, Memory, Reflection, Learning, Skill
Registry, and Execution Pipeline — preserving the frozen architecture.

v8.38 adds the provider tool-calling *boundary* only: ``AIRequest.tools``
(declarations offered to the model), ``AIResponse.tool_calls`` (normalized
calls the model proposed), ``ToolCallNormalizationError`` and
``ToolCallingUnsupportedError``. Nothing here executes, routes or authorizes
a tool.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Optional, Protocol

from core.conversation_history import ConversationHistory, Message
from core.tool_calling import ToolCall, ToolExchange, validate_tool_calls
from core.tool_catalog import ToolSpec


class ToolCallNormalizationError(ValueError):
    """v8.38: a provider-native tool call could not be normalized into a
    ``ToolCall`` (malformed block, invalid id / name / arguments, duplicate
    ids). Messages are structural only; any underlying validation error is
    kept as the cause."""


class ToolCallingUnsupportedError(Exception):
    """v8.38: a request offered tools to a provider that does not declare
    ``supports_tool_calling``; raised before the provider is invoked."""


@dataclass(frozen=True, slots=True)
class AIRequest:
    """Provider-agnostic request payload.

    ``prompt`` is the user turn being sent now. Optional
    ``history`` carries prior multi-turn context; when supplied,
    providers forward the full ordered list (history + current
    prompt) to their SDK. ``history`` defaults to ``None`` so all
    pre-v7.5 single-turn call sites keep working unchanged.
    """

    prompt: str
    history: Optional[ConversationHistory] = None
    # v8.36: request-level system channel (system instructions, then any
    # opt-in memory block). ``None`` keeps every request unchanged; each
    # provider module maps it to its own native system field.
    system: Optional[str] = None
    # v8.38: tool declarations offered to the model (empty: no tools). Only
    # ``ToolSpec``s with ``model_invocable=True`` and unique names; order
    # preserved. Declarations only — not authorization (v8.39).
    tools: tuple[ToolSpec, ...] = ()
    # v8.39: the completed tool-calling rounds of one run (calls proposed by the
    # model and their results), carried loop-locally into the follow-up request.
    # A non-empty value requires ``tools``. Never part of canonical history.
    tool_exchanges: tuple[ToolExchange, ...] = ()

    def __post_init__(self) -> None:
        tools = self.tools
        if isinstance(tools, (str, bytes)) or not isinstance(tools, Iterable):
            raise TypeError("tools must be a collection of ToolSpec")
        normalized = tuple(tools)
        names: set[str] = set()
        for index, spec in enumerate(normalized):
            if not isinstance(spec, ToolSpec):
                raise TypeError(f"tools[{index}] is not a ToolSpec: {type(spec).__name__}")
            if not spec.model_invocable:
                raise ValueError(f"tools[{index}] ({spec.name!r}) is not model_invocable")
            if spec.name in names:
                raise ValueError(f"duplicate tool name: {spec.name!r}")
            names.add(spec.name)
        object.__setattr__(self, "tools", normalized)
        exchanges = self.tool_exchanges
        if isinstance(exchanges, (str, bytes)) or not isinstance(exchanges, Iterable):
            raise TypeError("tool_exchanges must be a collection of ToolExchange")
        rounds = tuple(exchanges)
        for index, exchange in enumerate(rounds):
            if not isinstance(exchange, ToolExchange):
                raise TypeError(f"tool_exchanges[{index}] is not a ToolExchange: {type(exchange).__name__}")
        if rounds and not normalized:
            raise ValueError("tool_exchanges requires tools")
        object.__setattr__(self, "tool_exchanges", rounds)


@dataclass(frozen=True, slots=True)
class AIResponse:
    """Provider-agnostic response payload.

    ``text`` is the model's textual reply; ``provider_name`` records
    which concrete provider produced it (for introspection/tests).
    v8.38: ``tool_calls`` holds the normalized tool calls the model
    proposed, in response order (empty for a text-only reply).
    """

    text: str
    provider_name: str
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", validate_tool_calls(tuple(self.tool_calls)))


class AIProvider(Protocol):
    """Minimal provider interface.

    A single synchronous ``complete`` operation mapping an
    ``AIRequest`` to an ``AIResponse``. Implementations must be
    deterministic given the same request (deterministic mock) or
    document their non-determinism (real providers).

    The interface deliberately exposes no network/IO/streaming
    surface — concrete providers wire those concerns themselves behind
    this boundary.
    """

    name: str

    def complete(self, request: AIRequest) -> AIResponse:
        ...


class StaticMockProvider:
    """Deterministic, network-free mock implementation.

    Returns the configured ``response`` text verbatim for every
    request. Optional ``echo`` mode returns the request's prompt
    instead, which makes it useful for testing prompt-passthrough
    behaviour. ``call_count`` records how many requests were made
    so tests can assert that no provider call leaked.
    """

    def __init__(
        self,
        response: str = "mock-response",
        *,
        echo: bool = False,
        name: str = "mock",
    ) -> None:
        self._response = response
        self._echo = echo
        self.name = name
        self.call_count = 0

    def complete(self, request: AIRequest) -> AIResponse:
        self.call_count += 1
        text = request.prompt if self._echo else self._response
        return AIResponse(text=text, provider_name=self.name)


def default_provider(
    response: Optional[str] = None,
    *,
    echo: bool = False,
) -> AIProvider:
    """Convenience factory returning a deterministic
    ``StaticMockProvider``. Real providers will be wired in later
    milestones — for now, the mock is the default."""
    return StaticMockProvider(
        response="mock-response" if response is None else response,
        echo=echo,
    )


__all__ = [
    "AIProvider",
    "AIRequest",
    "AIResponse",
    "StaticMockProvider",
    "ToolCallNormalizationError",
    "ToolCallingUnsupportedError",
    "default_provider",
]