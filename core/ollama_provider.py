"""MARK L v7.3 — Ollama Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``ollama`` Python SDK to dispatch requests against a local Ollama
server. The SDK client is injected for testability; if none is
supplied, a real client is created lazily on first use (never at
import time).

Depends on ``core.ai_provider`` and the ``ollama`` SDK. No retries,
no fallback, no streaming, no async, no logging, no metrics, no
caching, no conversation history.

v8.40 (tool calling, owner decision OD-4b): this module is the only place that
knows the Ollama-native tool format. Ollama's ``generate`` has no tool support,
so when ``AIRequest.tools`` are offered the request goes through ``chat``
(``tools=[{"type": "function", "function": {"name", "description",
"parameters"}}]``, never ``idempotent`` / ``side_effects``); requests without
tools still use ``generate`` unchanged. Ollama tool calls carry no id, so the
positional-id fallback applies (``call_1``, ``call_2``, ... in response order).
``tool_exchanges`` are replayed as an assistant message with ``tool_calls`` and
one ``tool`` message (``tool_name``) per result. A call whose response stopped
with ``done_reason`` ``length`` or that is malformed raises
``ToolCallNormalizationError`` and is never returned for execution.
"""

from __future__ import annotations

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


def _field(source: object, key: str) -> object:
    """Read ``key`` from a mapping or an attribute (the SDK returns either)."""
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _normalize_tool_calls(raw_calls: object) -> tuple[ToolCall, ...]:
    """Normalize ``message.tool_calls``, in order, with positional ids."""
    calls: list[ToolCall] = []
    for index, raw in enumerate(raw_calls or ()):
        function = _field(raw, "function")
        name = _field(function, "name")
        arguments = _field(function, "arguments")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallNormalizationError(f"tool call {index}: name is missing or invalid")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise ToolCallNormalizationError(f"tool call {index}: arguments are not a mapping")
        try:
            calls.append(ToolCall(call_id=f"call_{len(calls) + 1}", name=name, arguments=arguments))
        except (TypeError, ValueError) as exc:
            raise ToolCallNormalizationError(f"tool call {index}: arguments are not valid tool-call arguments") from exc
    return validate_tool_calls(calls)


class OllamaProvider:
    """Ollama-backed provider using the official SDK.

    Constructor stores the model name, an optional ``host`` URL,
    and (optionally) a pre-built client. The client is created
    lazily only on first use when none was injected, so importing
    the module is free of any SDK initialization.
    """

    name: str = "ollama"
    supports_tool_calling: bool = True  # v8.40 neutral capability flag

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
        if request.tools:  # v8.40: native tool-calling request via ``chat``
            messages: list[dict] = []
            if request.system is not None:
                messages.append({"role": "system", "content": request.system})
            if request.history is not None:
                messages.extend(m.to_ollama_payload() for m in request.history.messages())
            messages.append({"role": "user", "content": request.prompt})
            for exchange in request.tool_exchanges:
                messages.append({
                    "role": "assistant",
                    "content": exchange.text,
                    "tool_calls": [
                        {"function": {"name": call.name, "arguments": _plain(call.arguments)}}
                        for call in exchange.calls
                    ],
                })
                for result in exchange.results:
                    messages.append({"role": "tool", "tool_name": result.name, "content": result.output})
            sdk_response = client.chat(
                model=self.model,
                messages=messages,
                tools=[
                    {"type": "function",
                     "function": {"name": spec.name, "description": spec.description,
                                  "parameters": _plain(spec.parameters)}}
                    for spec in request.tools
                ],
            )
            message = _field(sdk_response, "message")
            tool_calls = _normalize_tool_calls(_field(message, "tool_calls"))
            done_reason = _field(sdk_response, "done_reason")
            if tool_calls and done_reason == "length":
                # A tool call cut off by the output limit is never returned.
                raise ToolCallNormalizationError(f"tool call response stopped with done_reason {done_reason!r}")
            content = _field(message, "content")
            return AIResponse(
                text=content if isinstance(content, str) else "",
                provider_name=self.name,
                tool_calls=tool_calls,
            )
        extra: dict = {}
        if request.system is not None:  # v8.36: Ollama ``system=``
            extra["system"] = request.system
        if request.history is not None and len(request.history) > 0:
            messages = [m.to_ollama_payload() for m in request.history.messages()]
            sdk_response = client.generate(
                model=self.model,
                prompt=request.prompt,
                messages=messages,
                **extra,
            )
        else:
            sdk_response = client.generate(
                model=self.model,
                prompt=request.prompt,
                **extra,
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