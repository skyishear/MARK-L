"""MARK L v6.2 — AI Provider Routing.

Deterministic router that selects one already-registered provider by
explicit name. Does not create providers, does not perform network
calls, and does not know anything about specific vendor SDKs.

Depends only on ``core.ai_provider`` and ``core.ai_provider_registry``.
"""

from __future__ import annotations

from core.ai_provider import AIProvider
from core.ai_provider_registry import AIProviderNotFoundError, AIProviderRegistry


class AIProviderUnavailableError(KeyError):
    """Raised when a requested provider is not present in the registry."""


class AIProviderRouter:
    """Minimal deterministic router.

    Selection rule: a provider is selected **iff** it is present in
    the supplied ``AIProviderRegistry`` under the requested ``name``.
    No priority, no scoring, no fallback, no load balancing, no
    retry, no randomness.
    """

    def __init__(self, registry: AIProviderRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> AIProviderRegistry:
        """The registry this router reads from (read-only view)."""
        return self._registry

    def select(self, name: str) -> AIProvider:
        """Return the registered provider for ``name``.

        Raises:
            AIProviderUnavailableError: If no provider is registered
                under ``name``.
        """
        try:
            return self._registry.get(name)
        except AIProviderNotFoundError as exc:
            raise AIProviderUnavailableError(
                f"AI provider '{name}' is not registered."
            ) from exc

    def is_available(self, name: str) -> bool:
        """Return whether ``name`` is currently registered."""
        return self._registry.has(name)

    def available_names(self) -> tuple[str, ...]:
        """Return the names of currently registered providers."""
        return self._registry.names()


__all__ = [
    "AIProviderRouter",
    "AIProviderUnavailableError",
]