"""MARK L v7.0 — OpenAI Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``openai`` Python SDK to dispatch requests. The SDK client is
injected for testability; if none is supplied, a real client is
created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``openai`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching.

v8.40 (tool calling, owner decision OD-4b): this module is the only place that
knows the OpenAI-native tool format. ``AIRequest.tools`` are sent as
``tools=[{"type": "function", "function": {"name", "description",
"parameters"}}]`` only when offered (never ``idempotent`` / ``side_effects``);
every ``function`` tool call of the first choice becomes a neutral ``ToolCall``
(``id`` verbatim, ``arguments`` parsed from the JSON string, never repaired).
``AIRequest.tool_exchanges`` are replayed as an assistant message carrying
``tool_calls`` followed by one ``tool`` message per result. A tool call whose
choice stopped with ``finish_reason`` ``length`` or ``content_filter``, or that
is malformed (missing id / name, non-JSON or non-object arguments, a non-function
call, duplicate ids), raises ``ToolCallNormalizationError`` and is never
returned for execution.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse, ToolCallNormalizationError
from core.tool_calling import ToolCall, validate_tool_calls


def _plain(value: object) -> object:
    """Deep plain copy of frozen declaration / argument data for the SDK."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _normalize_tool_calls(raw_calls: object) -> tuple[ToolCall, ...]:
    """Normalize the ``tool_calls`` of a choice message, in order."""
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls or ()):
        if getattr(raw, "type", "function") != "function":
            raise ToolCallNormalizationError(f"tool call {index}: unsupported tool call type")
        call_id = getattr(raw, "id", None)
        function = getattr(raw, "function", None)
        name = getattr(function, "name", None)
        raw_arguments = getattr(function, "arguments", None)
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolCallNormalizationError(f"tool call {index}: id is missing or invalid")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallNormalizationError(f"tool call {index}: name is missing or invalid")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else None
        except ValueError as exc:
            raise ToolCallNormalizationError(f"tool call {index}: arguments are not valid JSON") from exc
        if not isinstance(arguments, Mapping):
            raise ToolCallNormalizationError(f"tool call {index}: arguments are not a JSON object")
        try:
            calls.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
        except (TypeError, ValueError) as exc:
            raise ToolCallNormalizationError(f"tool call {index}: arguments are not valid tool-call arguments") from exc
    try:
        return validate_tool_calls(calls)
    except ValueError as exc:
        raise ToolCallNormalizationError("duplicate tool call id in response") from exc


class OpenAIProvider:
    """OpenAI-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "openai"
    supports_tool_calling: bool = True  # v8.40 neutral capability flag

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
        for exchange in request.tool_exchanges:  # v8.40: replay completed rounds natively
            messages.append({
                "role": "assistant",
                "content": exchange.text or None,
                "tool_calls": [
                    {"id": call.call_id, "type": "function",
                     "function": {"name": call.name, "arguments": json.dumps(_plain(call.arguments))}}
                    for call in exchange.calls
                ],
            })
            for result in exchange.results:
                messages.append({"role": "tool", "tool_call_id": result.call_id, "content": result.output})
        kwargs: dict = {"model": self.model, "messages": messages}
        if request.tools:  # v8.40: OpenAI-native declarations, only when offered
            kwargs["tools"] = [
                {"type": "function",
                 "function": {"name": spec.name, "description": spec.description,
                              "parameters": _plain(spec.parameters)}}
                for spec in request.tools
            ]
        sdk_response = client.chat.completions.create(**kwargs)
        choice = sdk_response.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _normalize_tool_calls(getattr(message, "tool_calls", None))
        finish_reason = getattr(choice, "finish_reason", None)
        if tool_calls and finish_reason in ("length", "content_filter"):
            # A tool call cut off by the output limit or a filter is never returned.
            raise ToolCallNormalizationError(f"tool call response stopped with finish_reason {finish_reason!r}")
        return AIResponse(text=text, provider_name=self.name, tool_calls=tool_calls)


__all__ = ["OpenAIProvider"]