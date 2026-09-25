"""MARK L v6.8 — Default AI Provider Bootstrap.

Single-purpose module that constructs an ``AIProviderRegistry`` and
registers every built-in provider in a fixed, documented order.
Returns the populated registry. No configuration, no environment
loading, no networking, no SDK initialization.

Depends only on the existing registry + provider modules. No imports
from planning / execution / memory / reflection / learning /
problem-solver / skill-registry / agent.
"""

from __future__ import annotations

from core.ai_provider_registry import AIProviderRegistry
from core.claude_provider import ClaudeProvider
from core.gemini_provider import GeminiProvider
from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider


def build_default_registry() -> AIProviderRegistry:
    """Return a fresh ``AIProviderRegistry`` pre-populated with every
    built-in provider, in this order:

    1. ``openai``  — :class:`OpenAIProvider`
    2. ``claude``  — :class:`ClaudeProvider`
    3. ``gemini``  — :class:`GeminiProvider`
    4. ``ollama``  — :class:`OllamaProvider`

    The function is deterministic: it allocates a new registry on
    every call and always registers the same four providers in the
    same order. It performs no I/O, no networking, no SDK
    initialization, and no configuration loading.
    """
    registry = AIProviderRegistry()
    registry.register(OpenAIProvider())
    registry.register(ClaudeProvider())
    registry.register(GeminiProvider())
    registry.register(OllamaProvider())
    return registry


__all__ = ["build_default_registry"]