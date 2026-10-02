"""MARK L v7.1 — Claude Provider (Real Transport).

Concrete ``AIProvider`` implementation that uses the official
``anthropic`` Python SDK to dispatch requests. The SDK client is
injected for testability; if none is supplied, a real client is
created lazily on first use (never at import time).

Depends on ``core.ai_provider`` and the ``anthropic`` SDK. No
retries, no fallback, no streaming, no async, no logging, no
metrics, no caching, no conversation history.

v8.38 (first provider tool-call normalization): the only module that knows
the Anthropic-native tool format. ``AIRequest.tools`` (``ToolSpec``s) are
sent as ``tools=[{"name", "description", "input_schema"}]`` — only when
non-empty, as plain ``dict`` / ``list`` copies, never ``idempotent`` /
``side_effects``; every ``tool_use`` response block becomes a neutral
``ToolCall`` (``id`` verbatim, no id generation) in response order. A
malformed ``tool_use`` block raises ``ToolCallNormalizationError`` — never
repaired, invented or dropped. No SDK object leaves this module. Nothing is
executed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from core.ai_provider import AIProvider, AIRequest, AIResponse, ToolCallNormalizationError
from core.tool_calling import ToolCall, validate_tool_calls


def _plain(value: object) -> object:
    """Deep plain copy of frozen declaration data (mappings -> dict,
    tuples / lists -> list) for the SDK; never aliases internal structures."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _normalize_tool_calls(blocks: list) -> tuple[ToolCall, ...]:
    """Normalize every ``tool_use`` content block into a ``ToolCall``, in
    order; other block types are ignored. Messages are structural only."""
    calls: list[ToolCall] = []
    for index, block in enumerate(blocks):
        if getattr(block, "type", None) != "tool_use":
            continue
        call_id = getattr(block, "id", None)
        name = getattr(block, "name", None)
        arguments = getattr(block, "input", None)
        if not isinstance(call_id, str) or not call_id.strip():
            raise ToolCallNormalizationError(f"content block {index}: tool_use id is missing or invalid")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallNormalizationError(f"content block {index}: tool_use name is missing or invalid")
        if not isinstance(arguments, Mapping):
            raise ToolCallNormalizationError(f"content block {index}: tool_use input is not a mapping")
        try:
            calls.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
        except (TypeError, ValueError) as exc:
            raise ToolCallNormalizationError(
                f"content block {index}: tool_use input is not valid tool-call arguments"
            ) from exc
    try:
        return validate_tool_calls(calls)
    except ValueError as exc:
        raise ToolCallNormalizationError("duplicate tool_use id in response") from exc


class ClaudeProvider:
    """Anthropic-backed provider using the official SDK.

    Constructor stores the model name and (optionally) a pre-built
    client and API key. The client is created lazily only on first
    use when none was injected, so importing the module is free of
    any SDK initialization.
    """

    name: str = "claude"
    supports_tool_calling: bool = True  # v8.38 neutral capability flag

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
        if request.tools:  # v8.38: Anthropic-native declarations, only when offered
            kwargs["tools"] = [
                {"name": spec.name, "description": spec.description,
                 "input_schema": _plain(spec.parameters)}
                for spec in request.tools
            ]
        sdk_response = client.messages.create(**kwargs)
        blocks = list(sdk_response.content)
        text = ""
        for block in blocks:
            # First text-bearing block wins; SDK content is a list of
            # typed blocks (text, tool_use, etc.) — accept any object
            # exposing a non-empty ``text`` attribute.
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str) and block_text:
                text = block_text
                break
        return AIResponse(
            text=text, provider_name=self.name, tool_calls=_normalize_tool_calls(blocks)
        )


__all__ = ["ClaudeProvider"]