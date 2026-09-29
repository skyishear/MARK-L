"""MARK L v6.0 — AI Provider Abstraction (interface + minimal mock).

Single-responsibility, provider-agnostic abstraction representing a
language model. Supports exactly one synchronous request/response
operation. No streaming, no routing, no fallback, no conversation
memory, no MCP, no tool calling, no autonomous planning.

This module is intentionally minimal. It depends on nothing in
``core.*`` other than the standard library, so it stays independent
from Planning, Memory, Reflection, Learning, Skill Registry, and
Execution Pipeline — preserving the frozen architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from core.conversation_history import ConversationHistory, Message


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


@dataclass(frozen=True, slots=True)
class AIResponse:
    """Provider-agnostic response payload.

    ``text`` is the model's textual reply; ``provider_name`` records
    which concrete provider produced it (for introspection/tests).
    """

    text: str
    provider_name: str


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
    "default_provider",
]