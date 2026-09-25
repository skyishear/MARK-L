"""MARK L v6.9 — AI Service.

Minimal public entry point over the existing AI stack. Internally
constructs ``build_default_registry()``, wraps it in
``AIProviderRouter``, and exposes a single ``complete`` method that
delegates directly to ``AIConversationEngine``.

No routing logic, no provider selection, no retries, no fallback,
no caching, no logging, no metrics, no SDK init, no networking.
"""

from __future__ import annotations

from core.ai_conversation_engine import AIConversationEngine
from core.ai_provider import AIRequest, AIResponse
from core.ai_provider_router import AIProviderRouter, AIProviderUnavailableError
from core.context_manager import ContextManager
from core.conversation_history import ConversationHistory
from core.default_ai_provider_registry import build_default_registry


class AIService:
    """Single public entry point for the AI stack.

    The service owns its own ``AIProviderRegistry`` (built from
    ``build_default_registry()``), an ``AIProviderRouter`` over it,
    an ``AIConversationEngine``, and a ``ContextManager`` that
    prepares the ordered message list forwarded to providers.
    ``complete`` is a thin delegation: the optional
    ``ConversationHistory`` is run through the context manager and
    attached to the request, then handed to the engine.
    """

    def __init__(
        self,
        context_manager: ContextManager | None = None,
    ) -> None:
        self._registry = build_default_registry()
        self._router = AIProviderRouter(self._registry)
        self._engine = AIConversationEngine(self._router)
        self._context_manager = (
            context_manager if context_manager is not None else ContextManager()
        )

    @property
    def registry(self) -> object:
        """The internal registry (read-only view)."""
        return self._registry

    @property
    def router(self) -> AIProviderRouter:
        """The internal router (read-only view)."""
        return self._router

    @property
    def context_manager(self) -> ContextManager:
        """The internal context manager (read-only view)."""
        return self._context_manager

    def complete(
        self,
        provider_name: str,
        request: AIRequest,
        history: ConversationHistory | None = None,
    ) -> AIResponse:
        """Route ``request`` to ``provider_name`` and return the reply.

        ``history`` (optional) is a multi-turn context. When supplied,
        it is run through the internal ``ContextManager`` and the
        resulting ordered messages are attached to the request so the
        underlying SDK receives the entire prepared context. When
        omitted, the request is single-turn (the pre-v7.5 default).
        """
        merged = request
        if history is not None:
            prepared = self._context_manager.prepare(history)
            effective = ConversationHistory()
            effective.extend(prepared)
            merged = AIRequest(prompt=request.prompt, history=effective)
        return self._engine.complete(provider_name, merged)


__all__ = ["AIService", "AIProviderUnavailableError"]