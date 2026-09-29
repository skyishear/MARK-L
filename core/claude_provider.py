"""MARK L v7.1 — Claude Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``anthropic`` Python SDK to dispatch requests. The SDK client is
injected for testability; if none is supplied, a real client is
created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``anthropic`` SDK. No
retries, no fallback, no streaming, no async, no logging, no
metrics, no caching, no conversation history.
"""

from __future__ import annotations

from typing import Any, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse


class ClaudeProvider:
    """Anthropic-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "claude"

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-latest",
        *,
        api_key: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self.call_count = 0

    def _get_client(self) -> Any:
        """Return the injected client, lazily creating one if absent."""
        if self._client is None:
            from anthropic import Anthropic  # lazy import — never at module load

            self._client = (
                Anthropic(api_key=self._api_key) if self._api_key else Anthropic()
            )
        return self._client

    def complete(self, request: AIRequest) -> AIResponse:
        """Send ``request`` to the Anthropic SDK and return an
        ``AIResponse``.

        Conversion:
        - ``AIRequest.prompt`` (plus any ``request.history``) ->
          ``client.messages.create(model=self.model, max_tokens=1024,
          messages=[...])``
        - First text block of the response content -> ``AIResponse.text``,
          ``provider_name="claude"``.
        """
        self.call_count += 1
        client = self._get_client()
        messages: list[dict] = []
        if request.history is not None:
            for m in request.history.messages():
                messages.append(m.to_anthropic_payload())
        messages.append({"role": "user", "content": request.prompt})
        kwargs: dict = {"model": self.model, "max_tokens": 1024, "messages": messages}
        if request.system is not None:  # v8.36: Anthropic ``system=``
            kwargs["system"] = request.system
        sdk_response = client.messages.create(**kwargs)
        text = ""
        for block in sdk_response.content:
            # First text-bearing block wins; SDK content is a list of
            # typed blocks (text, tool_use, etc.) — accept any object
            # exposing a non-empty ``text`` attribute.
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str) and block_text:
                text = block_text
                break
        return AIResponse(text=text, provider_name=self.name)


__all__ = ["ClaudeProvider"]