"""MARK L v7.6 — Context Manager.

Provider-agnostic layer that sits between ``ConversationHistory``
and ``AIService``. Its only responsibility is to decide which
ordered ``Message`` objects from a ``ConversationHistory`` are
forwarded to providers.

This is **not** memory, summarization, vector search, embeddings,
or retrieval. The v7.6 implementation returns the entire ordered
history unchanged. Future milestones will add filtering, truncation,
memory injection, and token budgeting here without touching
providers or routing.

The public API is a single ``prepare(history) -> tuple[Message, ...]``
method. No I/O, no async, no persistence, no caching, no logging,
no metrics.
"""

from __future__ import annotations

from core.conversation_history import ConversationHistory, Message


class ContextManager:
    """Decide which ordered ``Message`` objects are forwarded to a
    provider.

    v7.6 returns the entire ``ConversationHistory`` unchanged so the
    full transcript is available to every provider call. Later
    versions will add filtering, truncation, memory injection, and
    token budgeting in this layer only.
    """

    def prepare(self, history: ConversationHistory) -> tuple[Message, ...]:
        """Return the ordered ``Message`` objects to forward.

        Currently returns ``history.messages()`` verbatim. Accepts an
        empty history and returns an empty tuple. Pure function with
        no side effects and no I/O.
        """
        if history is None:
            return ()
        return history.messages()


__all__ = ["ContextManager"]