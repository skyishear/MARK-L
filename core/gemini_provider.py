"""MARK L v7.2 — Gemini Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
Google GenAI SDK (``google-genai``) to dispatch requests. The SDK
client is injected for testability; if none is supplied, a real
client is created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``google`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching, no conversation history.
"""

from __future__ import annotations

from typing import Any, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse


class GeminiProvider:
    """Google-GenAI-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "gemini"

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
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
            from google import genai  # lazy import — never at module load

            self._client = genai.Client(api_key=self._api_key) if self._api_key else genai.Client()
        return self._client

    def complete(self, request: AIRequest) -> AIResponse:
        """Send ``request`` to the Gemini SDK and return an ``AIResponse``.

        Conversion:
        - ``AIRequest.prompt`` (plus any ``request.history``) ->
          ``client.models.generate_content(model=self.model, contents=...)``.
          When history is present the SDK is called with a list of
          ``{"role": ..., "content": ...}`` dicts (newest SDK
          multi-turn shape); single-turn calls remain a plain string.
        - Response ``.text`` -> ``AIResponse.text``,
          ``provider_name="gemini"``.
        """
        self.call_count += 1
        client = self._get_client()
        extra: dict = {}
        if request.system is not None:  # v8.36: Gemini ``system_instruction``
            extra["config"] = {"system_instruction": request.system}
        if request.history is not None and len(request.history) > 0:
            contents: list[dict] = [
                m.to_gemini_payload() for m in request.history.messages()
            ]
            contents.append({"role": "user", "content": request.prompt})
            sdk_response = client.models.generate_content(
                model=self.model,
                contents=contents,
                **extra,
            )
        else:
            sdk_response = client.models.generate_content(
                model=self.model,
                contents=request.prompt,
                **extra,
            )
        text = getattr(sdk_response, "text", "") or ""
        return AIResponse(text=text, provider_name=self.name)


__all__ = ["GeminiProvider"]