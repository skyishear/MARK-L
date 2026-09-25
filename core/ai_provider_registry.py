"""MARK L v6.1 — AI Provider Registry.

Owns registration and lookup for the v6.0 ``AIProvider`` abstraction.
No routing, no selection, no fallback, no network, no SDKs. Depends
only on ``core.ai_provider`` — isolated from Planning, Execution,
Memory, Reflection, Learning, and Skill Registry.
"""

from __future__ import annotations

from typing import Iterable

from core.ai_provider import AIProvider


class AIProviderAlreadyRegisteredError(ValueError):
    """Raised when a provider name is registered more than once."""


class AIProviderNotFoundError(KeyError):
    """Raised when a provider name is not present in the registry."""


class AIProviderRegistry:
    """Minimal, deterministic AI provider registry.

    - ``register(provider)`` stores the provider under its
      ``provider.name``; duplicates raise.
    - ``get(name)`` retrieves a registered provider or raises.
    - ``names()`` returns the registered names in insertion order,
      which is deterministic.

    No implicit selection logic — callers explicitly request a
    provider by name.
    """

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> AIProvider:
        """Register ``provider`` under its ``name`` attribute.

        Raises:
            AIProviderAlreadyRegisteredError: If the name is already
                registered with a different instance.
        """
        name = provider.name
        existing = self._providers.get(name)
        if existing is not None and existing is not provider:
            raise AIProviderAlreadyRegisteredError(
                f"AI provider '{name}' is already registered."
            )
        self._providers[name] = provider
        return provider

    def get(self, name: str) -> AIProvider:
        """Return the registered provider for ``name``.

        Raises:
            AIProviderNotFoundError: If no provider is registered
                under ``name``.
        """
        try:
            return self._providers[name]
        except KeyError as exc:
            raise AIProviderNotFoundError(name) from exc

    def has(self, name: str) -> bool:
        """Return whether ``name`` is currently registered."""
        return name in self._providers

    def names(self) -> tuple[str, ...]:
        """Return registered provider names in deterministic order."""
        return tuple(self._providers.keys())

    def list_providers(self) -> tuple[AIProvider, ...]:
        """Return registered providers in insertion order."""
        return tuple(self._providers.values())

    def unregister(self, name: str) -> None:
        """Remove a registered provider by name. No-op if absent."""
        self._providers.pop(name, None)

    def clear(self) -> None:
        """Remove every registered provider."""
        self._providers.clear()


__all__ = [
    "AIProviderAlreadyRegisteredError",
    "AIProviderNotFoundError",
    "AIProviderRegistry",
]