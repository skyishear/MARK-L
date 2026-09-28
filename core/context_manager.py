"""MARK L v7.6 — Context Manager (v8.34: bounded history view).

Provider-agnostic layer that sits between ``ConversationHistory``
and ``AIService``. Its only responsibility is to decide which
ordered ``Message`` objects from a ``ConversationHistory`` are
forwarded to providers.

This is **not** memory, summarization, vector search, embeddings,
or retrieval. v7.6 returned the entire ordered history unchanged; v8.34
bounds it with the locked owner policy (below). Future milestones will
add filtering, memory injection and token budgeting (v8.35) here without
touching providers or routing.

v8.34 owner policy (locked):

* ``max_messages = 50`` and ``max_chars = 20_000`` — enabled by default;
* characters are ``len(Message.content)`` only (no role names, no
  structure); the request's new prompt is not part of the history and is
  not counted;
* a history within both limits is returned unchanged;
* otherwise the oldest *units* are dropped first, where a unit is a
  complete ``user`` + ``assistant`` pair, or a single message that does
  not form one (e.g. a trailing incomplete user turn); a retained view
  never deliberately begins with an orphan ``assistant`` message; order
  and content of retained messages are never changed;
* when the newest unit alone cannot be retained (an oversized newest
  message, a newest complete pair that does not fit, or a newest orphan
  ``assistant`` message that would begin the view), a
  ``ContextValidationError`` is raised — nothing is truncated, dropped
  silently or sent over budget. The error text carries sizes only, never
  message content.

The canonical ``ConversationHistory`` is the source of truth and is
never mutated: ``prepare`` returns a bounded derived view. No token
counting, no tokenizer, no provider-specific logic. No I/O, no async,
no persistence, no caching, no logging, no metrics.
"""

from __future__ import annotations

from core.conversation_history import ConversationHistory, Message


class ContextValidationError(ValueError):
    """Raised when the newest history context cannot fit the character budget."""


class ContextManager:
    """Decide which ordered ``Message`` objects are forwarded to a
    provider: a bounded, derived view of the ``ConversationHistory``
    (v8.34 policy, see the module docstring).
    """

    def __init__(self, *, max_messages: int = 50, max_chars: int = 20_000) -> None:
        for name, value in (("max_messages", max_messages), ("max_chars", max_chars)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        self._max_messages = max_messages
        self._max_chars = max_chars

    @property
    def max_messages(self) -> int:
        return self._max_messages

    @property
    def max_chars(self) -> int:
        return self._max_chars

    def prepare(self, history: ConversationHistory) -> tuple[Message, ...]:
        """Return the ordered ``Message`` objects to forward.

        Within both limits: ``history.messages()`` unchanged. Otherwise the
        oldest units are dropped until both limits hold. Accepts ``None`` or
        an empty history and returns an empty tuple. Pure: never mutates
        ``history``; deterministic for the same input.

        Raises:
            ContextValidationError: the newest unit alone cannot be retained
                within the limits (or would begin with an orphan assistant
                message).
        """
        if history is None:
            return ()
        messages = history.messages()
        if self._fits(messages):
            return messages
        units = self._units(messages)
        start = 0
        while start < len(units):
            retained = tuple(m for unit in units[start:] for m in unit)
            if retained[0].role != "assistant" and self._fits(retained):
                return retained
            start += 1
        newest = units[-1]
        chars = sum(len(m.content) for m in newest)
        if newest[0].role == "assistant" and self._fits(newest):
            reason = "would begin with an orphan assistant message"
        else:
            reason = (
                f"exceeds max_messages={self._max_messages} / "
                f"max_chars={self._max_chars}"
            )
        raise ContextValidationError(
            f"newest context ({len(newest)} message(s), {chars} characters) {reason}"
        )

    def _fits(self, messages: tuple[Message, ...]) -> bool:
        return (
            len(messages) <= self._max_messages
            and sum(len(m.content) for m in messages) <= self._max_chars
        )

    @staticmethod
    def _units(messages: tuple[Message, ...]) -> list[tuple[Message, ...]]:
        """Group oldest-first into complete user/assistant pairs or single
        messages that do not form a pair."""
        units: list[tuple[Message, ...]] = []
        i = 0
        while i < len(messages):
            if (
                messages[i].role == "user"
                and i + 1 < len(messages)
                and messages[i + 1].role == "assistant"
            ):
                units.append((messages[i], messages[i + 1]))
                i += 2
            else:
                units.append((messages[i],))
                i += 1
        return units


__all__ = ["ContextManager", "ContextValidationError"]
