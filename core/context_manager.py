"""MARK L v7.6 — Context Manager (v8.34 bounded history view, v8.35 token budget).

Provider-agnostic layer that sits between ``ConversationHistory``
and ``AIService``. Its only responsibility is to decide which
ordered ``Message`` objects from a ``ConversationHistory`` are
forwarded to providers.

This is **not** memory, summarization, vector search, embeddings,
or retrieval. v7.6 returned the entire ordered history unchanged; v8.34
bounds it and v8.35 adds an input token budget, with the locked owner
policies below. Future milestones will add filtering and memory injection
here without touching providers or routing.

Owner policy (locked), three independent limits, all enabled by default:

* ``max_messages = 50`` (v8.34);
* ``max_chars = 20_000`` — ``len(Message.content)`` of the history only
  (no role names, no structure; the new prompt is not counted) (v8.34);
* ``max_tokens = 8_192`` — the **input/context** token budget, counted by
  an injected ``TokenCounter`` (default ``LocalTokenCounter``) over
  ``history + the request's new prompt``; no output-token reservation, and
  unrelated to any provider's output ``max_tokens`` setting (v8.35).

A history within all limits is returned unchanged. Otherwise the oldest
*units* are dropped first, where a unit is a complete ``user`` +
``assistant`` pair, or a single message that does not form one (e.g. a
trailing incomplete user turn); a retained view never deliberately begins
with an orphan ``assistant`` message; order and content of retained
messages are never changed. When the newest unit (with the prompt, for the
token budget) cannot be retained — an oversized newest message, a newest
complete pair that does not fit, a newest orphan ``assistant`` message, or
a prompt that alone exceeds the token budget — a ``ContextValidationError``
is raised: nothing is truncated, dropped silently or sent over budget. The
error text carries sizes only, never message content.

The canonical ``ConversationHistory`` is the source of truth and is never
mutated: ``prepare`` / ``prepare_request`` return a bounded derived view.
Token counting itself lives in ``core.token_counter`` (no counting logic
here); no provider or model identity, no context-window metadata. No I/O,
no async, no persistence, no caching, no logging, no metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.conversation_history import ConversationHistory, Message
from core.memory_context import MemoryRequest, render_memories, select_memories
from core.token_counter import LocalTokenCounter, TokenCounter


class ContextValidationError(ValueError):
    """Raised when the newest required context cannot fit the limits."""


@dataclass(frozen=True, slots=True)
class PreparedContext:
    """v8.36: the request-level context for one provider call.

    ``messages`` — the bounded history view; ``system`` — the request-level
    system channel text (system instructions, then the rendered memory
    block), or ``None``; ``memory_count`` — memories actually injected.
    """

    messages: tuple[Message, ...]
    system: Optional[str]
    memory_count: int


class ContextManager:
    """Decide which ordered ``Message`` objects are forwarded to a
    provider: a bounded, derived view of the ``ConversationHistory``
    (v8.34 / v8.35 policy, see the module docstring).
    """

    def __init__(
        self,
        *,
        max_messages: int = 50,
        max_chars: int = 20_000,
        max_tokens: int = 8_192,
        token_counter: Optional[TokenCounter] = None,
    ) -> None:
        for name, value in (
            ("max_messages", max_messages),
            ("max_chars", max_chars),
            ("max_tokens", max_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive int")
        counter = token_counter if token_counter is not None else LocalTokenCounter()
        if not callable(getattr(counter, "count", None)):
            raise TypeError("token_counter must provide count(text) -> int")
        self._max_messages = max_messages
        self._max_chars = max_chars
        self._max_tokens = max_tokens
        self._token_counter = counter

    @property
    def max_messages(self) -> int:
        return self._max_messages

    @property
    def max_chars(self) -> int:
        return self._max_chars

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    @property
    def token_counter(self) -> TokenCounter:
        return self._token_counter

    def prepare(self, history: ConversationHistory) -> tuple[Message, ...]:
        """Return the ordered ``Message`` objects to forward.

        Within all limits: ``history.messages()`` unchanged. Otherwise the
        oldest units are dropped until all limits hold (the token budget
        here counts the history alone). Accepts ``None`` or an empty history
        and returns an empty tuple. Pure: never mutates ``history``;
        deterministic for the same input.

        Raises:
            ContextValidationError: the newest unit alone cannot be retained
                within the limits (or would begin with an orphan assistant
                message).
        """
        if history is None:
            return ()
        return self._bound(history.messages(), prompt_tokens=0)

    def prepare_request(
        self,
        history: Optional[ConversationHistory],
        prompt: str,
    ) -> tuple[Message, ...]:
        """v8.35: the bounded view for one request, with the token budget
        covering ``history + prompt``.

        Applies ``self.prepare(history)`` first (so a subclass override is
        honoured), then drops further oldest units until the history tokens
        plus the prompt tokens fit ``max_tokens``.

        Raises:
            TypeError: ``prompt`` is not a ``str``.
            ContextValidationError: the prompt alone exceeds ``max_tokens``,
                or the newest unit plus the prompt cannot fit.
        """
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        prompt_tokens = self._count(prompt)
        if prompt_tokens > self._max_tokens:
            raise ContextValidationError(
                f"prompt ({prompt_tokens} tokens) exceeds max_tokens={self._max_tokens}"
            )
        return self._bound(tuple(self.prepare(history)), prompt_tokens=prompt_tokens)

    def prepare_context(
        self,
        history: Optional[ConversationHistory],
        prompt: str,
        *,
        system: Optional[str] = None,
        memory: Optional[MemoryRequest] = None,
        tool_context: Optional[str] = None,
    ) -> PreparedContext:
        """v8.36: the full request-level context — SYSTEM, MEMORY, HISTORY,
        PROMPT — within the 8,192-token input budget.

        The system instructions and the prompt are required and never
        truncated. The history is bounded exactly as in v8.34 / v8.35, with
        the system tokens counted alongside the prompt tokens. Memories
        (opt-in, ``memory``) are the removable derived context: the
        non-sensitive memories selected by ``select_memories`` are kept in
        recall order and dropped from the end until everything fits; memory
        never causes history trimming. Message and character limits apply to
        the history only. Canonical history is never mutated.

        v8.39: ``tool_context`` (the deterministic rendering of the offered
        tool declarations and the run's tool exchanges) is required context
        like the system instructions and the prompt: it is counted through
        the injected counter inside the same 8,192-token budget, never
        truncated, and the history is trimmed to make room for it.

        Raises:
            TypeError: ``prompt`` / ``system`` are not ``str`` (``system``
                may be ``None``), or ``memory`` is not a ``MemoryRequest``.
            ContextValidationError: system + prompt (+ tool context) alone
                exceed ``max_tokens``, or the newest history unit plus them
                cannot fit.
        """
        if not isinstance(prompt, str):
            raise TypeError("prompt must be a str")
        if system is not None and not isinstance(system, str):
            raise TypeError("system must be a str or None")
        if memory is not None and not isinstance(memory, MemoryRequest):
            raise TypeError("memory must be a MemoryRequest or None")
        if tool_context is not None and not isinstance(tool_context, str):
            raise TypeError("tool_context must be a str or None")
        prompt_tokens = self._count(prompt)
        system_tokens = self._count(system) if system is not None else 0
        tool_tokens = self._count(tool_context) if tool_context else 0
        required = prompt_tokens + system_tokens + tool_tokens
        if required > self._max_tokens:
            tools_part = f" + tool context ({tool_tokens} tokens)" if tool_tokens else ""
            raise ContextValidationError(
                f"system ({system_tokens} tokens) + prompt ({prompt_tokens} tokens){tools_part} "
                f"exceeds max_tokens={self._max_tokens}"
            )
        messages = self._bound(tuple(self.prepare(history)), prompt_tokens=required)
        fixed = prompt_tokens + tool_tokens + sum(self._count(m.content) for m in messages)
        entries = select_memories(memory, prompt) if memory is not None else ()
        for kept in range(len(entries), 0, -1):
            block = render_memories(entries[:kept])
            text = block if not system else f"{system}\n\n{block}"
            if self._count(text) + fixed <= self._max_tokens:
                return PreparedContext(messages=messages, system=text, memory_count=kept)
        return PreparedContext(messages=messages, system=system, memory_count=0)

    def _count(self, text: str) -> int:
        tokens = self._token_counter.count(text)
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise TypeError("token_counter.count must return a non-negative int")
        return tokens

    def _bound(self, messages: tuple[Message, ...], *, prompt_tokens: int) -> tuple[Message, ...]:
        n = len(messages)
        chars = [len(m.content) for m in messages]
        tokens = [self._count(m.content) for m in messages]
        # Suffix sums: retained view messages[start:] for any start.
        suffix_chars = [0] * (n + 1)
        suffix_tokens = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            suffix_chars[i] = suffix_chars[i + 1] + chars[i]
            suffix_tokens[i] = suffix_tokens[i + 1] + tokens[i]

        def fits(start: int) -> bool:
            return (
                n - start <= self._max_messages
                and suffix_chars[start] <= self._max_chars
                and suffix_tokens[start] + prompt_tokens <= self._max_tokens
            )

        if fits(0):
            return messages
        starts = self._unit_starts(messages)
        for start in starts:
            if messages[start].role != "assistant" and fits(start):
                return messages[start:]
        newest = starts[-1]
        size = f"{n - newest} message(s), {suffix_chars[newest]} characters, {suffix_tokens[newest]} tokens"
        if messages[newest].role == "assistant" and fits(newest):
            reason = "would begin with an orphan assistant message"
        else:
            reason = (
                f"exceeds max_messages={self._max_messages} / max_chars={self._max_chars} / "
                f"max_tokens={self._max_tokens} (prompt {prompt_tokens} tokens)"
            )
        raise ContextValidationError(f"newest context ({size}) {reason}")

    @staticmethod
    def _unit_starts(messages: tuple[Message, ...]) -> list[int]:
        """Start indices of the oldest-first units: complete user/assistant
        pairs or single messages that do not form a pair."""
        starts: list[int] = []
        i = 0
        while i < len(messages):
            starts.append(i)
            if (
                messages[i].role == "user"
                and i + 1 < len(messages)
                and messages[i + 1].role == "assistant"
            ):
                i += 2
            else:
                i += 1
        return starts


__all__ = ["ContextManager", "ContextValidationError", "PreparedContext"]
