"""MARK L v7.2 — Gemini Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
Google GenAI SDK (``google-genai``) to dispatch requests. The SDK
client is injected for testability; if none is supplied, a real
client is created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``google`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching, no conversation history.

v8.40 (tool calling, owner decision OD-4b): this module is the only place that
knows the Gemini-native tool format. When ``AIRequest.tools`` are offered they
are sent as ``config["tools"] = [{"function_declarations": [{"name",
"description", "parameters_json_schema"}]}]`` (never ``idempotent`` /
``side_effects``), with contents in the SDK's native ``role`` (``user`` /
``model``) and ``parts`` shape; requests without tools are unchanged. Every
``function_call`` part of the first candidate becomes a neutral ``ToolCall``;
Gemini calls may carry no id, so the positional-id fallback applies (``call_1``,
``call_2``, ... in response order) when the SDK gives none. ``tool_exchanges``
are replayed as a ``model`` content with ``function_call`` parts and a ``user``
content with ``function_response`` parts (paired by name and order). A call whose
candidate stopped with a ``finish_reason`` other than ``STOP`` (cut off, blocked,
malformed) or that is malformed raises ``ToolCallNormalizationError`` and is
never returned for execution.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse, ToolCallNormalizationError
from core.tool_calling import ToolCall, validate_tool_calls

_COMPLETE_FINISH_REASONS = (None, "STOP", "FINISH_REASON_UNSPECIFIED")


def _plain(value: object) -> object:
    """Deep plain copy of frozen declaration / argument data for the SDK."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _normalize_tool_calls(candidate: object) -> tuple[ToolCall, ...]:
    """Normalize the ``function_call`` parts of a candidate, in order."""
    parts = getattr(getattr(candidate, "content", None), "parts", None) or ()
    calls: list[ToolCall] = []
    for index, part in enumerate(parts):
        raw = getattr(part, "function_call", None)
        if raw is None:
            continue
        name = getattr(raw, "name", None)
        raw_id = getattr(raw, "id", None)
        arguments = getattr(raw, "args", None)
        if not isinstance(name, str) or not name.strip():
            raise ToolCallNormalizationError(f"part {index}: function_call name is missing or invalid")
        call_id = raw_id if isinstance(raw_id, str) and raw_id.strip() else f"call_{len(calls) + 1}"
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise ToolCallNormalizationError(f"part {index}: function_call args are not a mapping")
        try:
            calls.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
        except (TypeError, ValueError) as exc:
            raise ToolCallNormalizationError(f"part {index}: function_call args are not valid tool-call arguments") from exc
    try:
        return validate_tool_calls(calls)
    except ValueError as exc:
        raise ToolCallNormalizationError("duplicate function_call id in response") from exc


def _tool_contents(request: AIRequest) -> list[dict]:
    """Native ``contents`` (``user`` / ``model`` roles, ``parts``) for a tool request."""
    contents: list[dict] = []
    if request.history is not None:
        for m in request.history.messages():
            contents.append({"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]})
    contents.append({"role": "user", "parts": [{"text": request.prompt}]})
    for exchange in request.tool_exchanges:
        model_parts: list[dict] = []
        if exchange.text:
            model_parts.append({"text": exchange.text})
        for call in exchange.calls:
            model_parts.append({"function_call": {"name": call.name, "args": _plain(call.arguments)}})
        contents.append({"role": "model", "parts": model_parts})
        contents.append({
            "role": "user",
            "parts": [
                {"function_response": {"name": result.name, "response": {"output": result.output}}}
                for result in exchange.results
            ],
        })
    return contents


class GeminiProvider:
    """Google-GenAI-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "gemini"
    supports_tool_calling: bool = True  # v8.40 neutral capability flag

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
        if request.tools:  # v8.40: native tool-calling request
            config: dict = {"tools": [{"function_declarations": [
                {"name": spec.name, "description": spec.description,
                 "parameters_json_schema": _plain(spec.parameters)}
                for spec in request.tools
            ]}]}
            if request.system is not None:
                config["system_instruction"] = request.system
            sdk_response = client.models.generate_content(
                model=self.model, contents=_tool_contents(request), config=config,
            )
            candidates = getattr(sdk_response, "candidates", None) or ()
            candidate = candidates[0] if candidates else None
            tool_calls = _normalize_tool_calls(candidate)
            finish = getattr(candidate, "finish_reason", None)
            finish = getattr(finish, "name", finish)
            if tool_calls and finish not in _COMPLETE_FINISH_REASONS:
                # A tool call cut off, blocked or malformed is never returned.
                raise ToolCallNormalizationError(f"function_call response stopped with finish_reason {finish!r}")
            text = getattr(sdk_response, "text", "") or ""
            return AIResponse(text=text, provider_name=self.name, tool_calls=tool_calls)
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