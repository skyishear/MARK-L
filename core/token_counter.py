"""MARK L v8.35 — Token Counter (provider-neutral abstraction + local tokenizer).

``TokenCounter`` is the pluggable counting contract consumed by
``ContextManager`` for the v8.35 input/context token budget:

    count(text) -> int      (non-negative, deterministic)

``LocalTokenCounter`` is the default implementation: a deterministic,
local, standard-library lexical tokenizer. Each maximal run of word
characters (``\\w+`` — Unicode letters, digits, underscore) is one token and
every other non-whitespace character is one token of its own; whitespace
separates tokens and is not counted. It is a real tokenizer, not a
characters-per-token approximation, and it is **not** a model-specific
tokenizer: provider / model tokenizers and context windows are out of scope
for v8.35 and can be plugged in later through ``TokenCounter``.

No network, no provider SDK, no third-party dependency, no I/O, no state.

Dependency direction:

    ContextManager  →  token_counter  →  stdlib
    token_counter   →  anything in core.*   (forbidden)
"""

from __future__ import annotations

import re
from typing import Protocol

__all__ = ["LocalTokenCounter", "TokenCounter"]


class TokenCounter(Protocol):
    """Counts the tokens in a text (deterministic, non-negative)."""

    def count(self, text: str) -> int:
        ...


class LocalTokenCounter:
    """Deterministic local lexical tokenizer (the v8.35 default counter)."""

    __slots__ = ()

    _PATTERN = re.compile(r"\w+|[^\w\s]")

    def count(self, text: str) -> int:
        """Return the number of tokens in ``text``.

        Raises:
            TypeError: ``text`` is not a ``str``.
        """
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        return len(self._PATTERN.findall(text))
