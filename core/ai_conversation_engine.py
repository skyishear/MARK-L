"""MARK L v6.3 — AI Conversation Engine.

Minimal orchestration layer connecting the existing AI Provider Router
to the existing ``AIProvider.complete()`` operation.

Sequence: ``AIRequest`` -> ``AIProviderRouter.select`` ->
``provider.complete`` -> ``AIResponse`` -> caller. The engine
contains no provider logic and no router logic — it only wires
together the two existing abstractions.

Depends only on ``core.ai_provider``, ``core.ai_provider_registry``,
and ``core.ai_provider_router``. No history, no memory integration,
no retries, no fallback, no streaming, no logging, no metrics.
"""

from __future__ import annotations

from core.ai_provider import AIProvider, AIRequest, AIResponse
from core.ai_provider_router import AIProviderRouter, AIProviderUnavailableError


class AIConversationEngine:
    """Orchestrates a single synchronous request/response cycle.

    Stateless and deterministic given the same router, request, and
    registered provider. The engine never modifies the router or
    registry; it only reads from them.
    """

    def __init__(self, router: AIProviderRouter) -> None:
        self._router = router

    @property
    def router(self) -> AIProviderRouter:
        """The router this engine reads from (read-only view)."""
        return self._router

    def complete(
        self,
        provider_name: str,
        request: AIRequest,
    ) -> AIResponse:
        """Route ``request`` to the named provider and return its reply.

        Raises:
            AIProviderUnavailableError: If ``provider_name`` is not
                registered in the router's registry. Propagated
                unchanged from the router.
        """
        provider: AIProvider = self._router.select(provider_name)
        return provider.complete(request)


__all__ = ["AIConversationEngine", "AIProviderUnavailableError"]