"""MARK L v7.3 — Ollama Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``ollama`` Python SDK to dispatch requests against a local Ollama
server. The SDK client is injected for testability; if none is
supplied, a real client is created lazily on first use (never at
import time).

Depends on ``core.ai_provider`` and the ``ollama`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching, no conversation history.
"""

from __future__ import annotations

from typing import Any, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse


class OllamaProvider:
    """Ollama-backed provider using the official SDK.

    Constructor stores the model name, an optional ``host`` URL,
    and (optionally) a pre-built client. The client is created
    lazily only on first use when none was injected, so importing
    the module is free of any SDK initialization.
    """

    name: str = "ollama"

    def __init__(
        self,
        model: str = "llama3.1",
        *,
        host: Optional[str] = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self.host = host
        self._client = client
        self.call_count = 0

    def _get_client(self) -> Any:
        """Return the injected client, lazily creating one if absent."""
        if self._client is None:
            from ollama import Client  # lazy import — never at module load

            self._client = (
                Client(host=self.host) if self.host else Client()
            )
        return self._client

    def complete(self, request: AIRequest) -> AIResponse:
        """Send ``request`` to the Ollama SDK and return an
        ``AIResponse``.

        Conversion:
        - ``AIRequest.prompt`` (plus any ``request.history``) ->
          ``client.generate(model=self.model, prompt=..., messages=...)``.
          When history is present the SDK receives the full ordered
          ``messages`` list plus the current ``prompt``; single-turn
          calls remain a plain ``prompt`` string.
        - Response ``["response"]`` -> ``AIResponse.text``,
          ``provider_name="ollama"``.
        """
        self.call_count += 1
        client = self._get_client()
        if request.history is not None and len(request.history) > 0:
            messages = [m.to_ollama_payload() for m in request.history.messages()]
            sdk_response = client.generate(
                model=self.model,
                prompt=request.prompt,
                messages=messages,
            )
        else:
            sdk_response = client.generate(
                model=self.model,
                prompt=request.prompt,
            )
        text = ""
        if isinstance(sdk_response, dict):
            text = sdk_response.get("response", "") or ""
        else:
            raw = getattr(sdk_response, "response", None)
            if isinstance(raw, str):
                text = raw
        return AIResponse(text=text, provider_name=self.name)


__all__ = ["OllamaProvider"]