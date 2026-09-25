"""MARK L v7.5 — Conversation History.

Provider-agnostic, in-memory conversation history component. Stores
ordered ``Message`` entries (user / assistant) and exposes them to
the AI provider stack for multi-turn completion. No persistence, no
embeddings, no vector DB, no summarization, no token trimming, no
caching, no async, no streaming, no logging, no metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

Role = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """A single conversation turn.

    ``role`` is either ``"user"`` or ``"assistant"``. ``content`` is
    the textual payload. Provider-specific extras (tool calls,
    system messages) are out of scope for v7.5.
    """

    role: Role
    content: str

    def to_openai_payload(self) -> dict:
        """Render this message in the OpenAI chat-completions shape."""
        return {"role": self.role, "content": self.content}

    def to_anthropic_payload(self) -> dict:
        """Render this message in the Anthropic ``messages`` shape."""
        return {"role": self.role, "content": self.content}

    def to_gemini_payload(self) -> dict:
        """Render this message in the Google GenAI ``contents`` shape."""
        return {"role": self.role, "content": self.content}

    def to_ollama_payload(self) -> dict:
        """Render this message in the Ollama ``messages`` shape."""
        return {"role": self.role, "content": self.content}


class ConversationHistory:
    """Mutable, ordered history of ``Message`` objects.

    Starts empty. ``append_user`` / ``append_assistant`` add turns
    in order. ``messages`` returns the full ordered tuple (immutable
    snapshot). ``clear`` empties the history. No I/O, no persistence.
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def append_user(self, content: str) -> Message:
        msg = Message(role="user", content=content)
        self._messages.append(msg)
        return msg

    def append_assistant(self, content: str) -> Message:
        msg = Message(role="assistant", content=content)
        self._messages.append(msg)
        return msg

    def extend(self, messages: Iterable[Message]) -> None:
        for m in messages:
            if not isinstance(m, Message):
                raise TypeError(
                    f"ConversationHistory.extend expects Message, got {type(m).__name__}"
                )
            if m.role not in ("user", "assistant"):
                raise ValueError(f"Unsupported role: {m.role!r}")
            self._messages.append(m)

    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self):
        return iter(tuple(self._messages))

    def clear(self) -> None:
        self._messages.clear()


__all__ = ["ConversationHistory", "Message", "Role"]