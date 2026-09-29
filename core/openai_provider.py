"""MARK L v7.0 — OpenAI Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``openai`` Python SDK to dispatch requests. The SDK client is
injected for testability; if none is supplied, a real client is
created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``openai`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching.
"""

from __future__ import annotations

from typing import Any, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse


class OpenAIProvider:
    """OpenAI-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
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
            from openai import OpenAI  # lazy import — never at module load

            self._client = OpenAI(api_key=self._api_key) if self._api_key else OpenAI()
        return self._client

    def complete(self, request: AIRequest) -> AIResponse:
        """Send ``request`` to the OpenAI SDK and return an ``AIResponse``.

        Conversion:
        - ``AIRequest.prompt`` (plus any ``request.history``) ->
          ``client.chat.completions.create(
                model=self.model,
                messages=[...full ordered list...],
          )``
        - First choice message text -> ``AIResponse.text``,
          ``provider_name="openai"``.
        """
        self.call_count += 1
        client = self._get_client()
        messages: list[dict] = []
        if request.system is not None:  # v8.36: leading system message
            messages.append({"role": "system", "content": request.system})
        if request.history is not None:
            for m in request.history.messages():
                messages.append(m.to_openai_payload())
        messages.append({"role": "user", "content": request.prompt})
        sdk_response = client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        text = sdk_response.choices[0].message.content or ""
        return AIResponse(text=text, provider_name=self.name)


__all__ = ["OpenAIProvider"]