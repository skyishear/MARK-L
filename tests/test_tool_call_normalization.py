"""Tests for v8.38 first provider tool-call normalization (Anthropic).

Locked contract: additive ``AIRequest.tools: tuple[ToolSpec, ...] = ()``
(model-invocable, unique names, order kept) and ``AIResponse.tool_calls:
tuple[ToolCall, ...] = ()`` (validated, order kept); only
``ClaudeProvider`` knows the Anthropic-native tool format (declarations sent
only when tools are offered; ``tool_use`` blocks -> ``ToolCall`` with ids
verbatim); malformed blocks raise ``ToolCallNormalizationError`` (structural
messages, cause kept); ``AIService`` forwards ``tools`` on every path and
raises ``ToolCallingUnsupportedError`` before invoking any provider that
does not declare ``supports_tool_calling = True``. No execution, routing,
authorization or loop; O2 and token accounting deferred.
"""

from __future__ import annotations

import ast
import dataclasses
import os
from types import MappingProxyType, SimpleNamespace

import pytest

from core.ai_provider import (
    AIRequest,
    AIResponse,
    ToolCallingUnsupportedError,
    ToolCallNormalizationError,
)
from core.ai_service import AIService
from core.claude_provider import ClaudeProvider
from core.conversation_history import ConversationHistory, Message
from core.memory_context import MemoryRequest
from core.memory_engine import MemoryEngine
from core.tool_calling import ToolCall, ToolCallResult
from core.tool_catalog import ToolSpec

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
SECRET = "model-said-SECRET-VALUE"

WEATHER_PARAMS = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "days": {"type": "integer", "enum": [1, 3]},
                   "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["city"],
    "additionalProperties": False,
}


def spec(name: str = "weather", **kw: object) -> ToolSpec:
    kw.setdefault("model_invocable", True)
    return ToolSpec(name, kw.pop("description", f"{name} tool"), kw.pop("parameters", WEATHER_PARAMS), **kw)  # type: ignore[arg-type]


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(call_id: object = "toolu_1", name: object = "weather", input: object = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name,
                           input={"city": "Paris"} if input is None else input)


class FakeMessages:
    def __init__(self, blocks: list) -> None:
        self.blocks = blocks
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.blocks)


def claude(blocks: list) -> tuple[ClaudeProvider, FakeMessages]:
    msgs = FakeMessages(blocks)
    return ClaudeProvider(client=SimpleNamespace(messages=msgs)), msgs


# ── AIRequest.tools ─────────────────────────────────────────────────────


class TestAIRequestTools:
    def test_default_is_empty_tuple(self) -> None:
        assert AIRequest(prompt="p").tools == ()

    def test_fields_additive_and_positional_compatible(self) -> None:
        assert [f.name for f in dataclasses.fields(AIRequest)] == [
            "prompt", "history", "system", "tools", "tool_exchanges"]  # v8.39: additive final field
        r = AIRequest("p", None, "S")
        assert (r.prompt, r.history, r.system, r.tools) == ("p", None, "S", ())

    def test_valid_tuple_and_collection_conversion_order_kept(self) -> None:
        a, b, c = spec("a"), spec("b"), spec("c")
        assert AIRequest("p", tools=(a, b)).tools == (a, b)
        r = AIRequest("p", tools=[c, a, b])
        assert r.tools == (c, a, b) and isinstance(r.tools, tuple)
        assert all(x is y for x, y in zip(r.tools, (c, a, b)))

    def test_duplicate_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate tool name: 'a'"):
            AIRequest("p", tools=[spec("a"), spec("b"), spec("a", description="other")])

    @pytest.mark.parametrize("item", [{"name": "x"}, "weather", None, ToolCall("c", "t")])
    def test_non_toolspec_rejected(self, item: object) -> None:
        with pytest.raises(TypeError, match=r"tools\[1\] is not a ToolSpec"):
            AIRequest("p", tools=[spec("a"), item])  # type: ignore[list-item]

    @pytest.mark.parametrize("tools", ["abc", b"abc", 5, None])
    def test_non_collection_rejected(self, tools: object) -> None:
        with pytest.raises(TypeError):
            AIRequest("p", tools=tools)  # type: ignore[arg-type]

    def test_non_model_invocable_rejected(self) -> None:
        with pytest.raises(ValueError, match="not model_invocable"):
            AIRequest("p", tools=[spec("hidden", model_invocable=False)])

    def test_frozen(self) -> None:
        r = AIRequest("p", tools=[spec()])
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.tools = ()  # type: ignore[misc]


# ── AIResponse.tool_calls ───────────────────────────────────────────────


class TestAIResponseToolCalls:
    def test_default_and_compatibility(self) -> None:
        r = AIResponse("hi", "claude")
        assert r.tool_calls == () and (r.text, r.provider_name) == ("hi", "claude")
        assert [f.name for f in dataclasses.fields(AIResponse)] == ["text", "provider_name", "tool_calls"]

    def test_validated_and_ordered(self) -> None:
        calls = [ToolCall("b", "t"), ToolCall("a", "t")]
        r = AIResponse("", "x", tool_calls=calls)
        assert r.tool_calls == tuple(calls) and isinstance(r.tool_calls, tuple)

    def test_rejects_duplicates_and_foreign_items(self) -> None:
        with pytest.raises(ValueError):
            AIResponse("", "x", tool_calls=[ToolCall("a", "t"), ToolCall("a", "u")])
        with pytest.raises(TypeError):
            AIResponse("", "x", tool_calls=[ToolCallResult("a", "t", "o")])  # type: ignore[list-item]


# ── Claude request mapping ──────────────────────────────────────────────


class TestClaudeRequestMapping:
    def test_no_tools_payload_identical_to_v8_36(self) -> None:
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest(prompt="p"))
        assert msgs.calls[0] == {"model": "claude-3-5-sonnet-latest", "max_tokens": 1024,
                                 "messages": [{"role": "user", "content": "p"}]}
        p.complete(AIRequest(prompt="p", system="S"))
        assert set(msgs.calls[1]) == {"model", "max_tokens", "messages", "system"}

    def test_exact_anthropic_declaration_shape(self) -> None:
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest(prompt="p", tools=[spec("weather", description="Get weather"),
                                                 spec("time", parameters={"type": "object"})]))
        assert msgs.calls[0]["tools"] == [
            {"name": "weather", "description": "Get weather", "input_schema": WEATHER_PARAMS},
            {"name": "time", "description": "time tool", "input_schema": {"type": "object"}},
        ]

    def test_parameters_converted_to_plain_unaliased_structures(self) -> None:
        s = spec()
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest(prompt="p", tools=[s]))
        schema = msgs.calls[0]["tools"][0]["input_schema"]
        assert type(schema) is dict and type(schema["properties"]) is dict
        assert type(schema["required"]) is list and type(schema["properties"]["days"]["enum"]) is list
        schema["properties"]["city"]["type"] = "integer"  # mutating the SDK copy...
        assert s.parameters["properties"]["city"]["type"] == "string"  # ...never touches the spec
        assert isinstance(s.parameters, MappingProxyType)

    def test_policy_flags_never_sent(self) -> None:
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest(prompt="p", tools=[spec(idempotent=True, side_effects=False)]))
        decl = msgs.calls[0]["tools"][0]
        assert set(decl) == {"name", "description", "input_schema"}
        assert "idempotent" not in repr(msgs.calls) and "side_effects" not in repr(msgs.calls)

    def test_system_and_tools_together(self) -> None:
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest(prompt="p", system="Be brief.", tools=[spec()]))
        assert msgs.calls[0]["system"] == "Be brief." and len(msgs.calls[0]["tools"]) == 1


# ── Claude response normalization ───────────────────────────────────────


class TestClaudeResponseNormalization:
    def test_text_only(self) -> None:
        p, _ = claude([text_block("hello")])
        r = p.complete(AIRequest(prompt="p"))
        assert r == AIResponse("hello", "claude") and r.tool_calls == ()

    def test_tool_only(self) -> None:
        p, _ = claude([tool_block("toolu_A", "weather", {"city": "Rome", "tags": ["x"]})])
        r = p.complete(AIRequest(prompt="p", tools=[spec()]))
        assert r.text == "" and r.tool_calls == (ToolCall("toolu_A", "weather", {"city": "Rome", "tags": ["x"]}),)

    def test_mixed_text_and_tool_use_keeps_first_text_rule(self) -> None:
        p, _ = claude([text_block("first"), tool_block("t1"), text_block("second"), tool_block("t2", "time", {})])
        r = p.complete(AIRequest(prompt="p"))
        assert r.text == "first"
        assert [(c.call_id, c.name) for c in r.tool_calls] == [("t1", "weather"), ("t2", "time")]

    def test_tool_use_before_text(self) -> None:
        p, _ = claude([tool_block("t1"), text_block("after")])
        r = p.complete(AIRequest(prompt="p"))
        assert r.text == "after" and [c.call_id for c in r.tool_calls] == ["t1"]

    def test_multiple_calls_order_and_ids_verbatim(self) -> None:
        ids = ["toolu_01Zz", "toolu_0aa", " spaced "]
        p, _ = claude([tool_block(i, f"n{k}", {}) for k, i in enumerate(ids)])
        r = p.complete(AIRequest(prompt="p"))
        assert [c.call_id for c in r.tool_calls] == ids and [c.name for c in r.tool_calls] == ["n0", "n1", "n2"]

    def test_arguments_deeply_immutable_and_unaliased(self) -> None:
        raw = {"where": {"lat": 1}, "tags": ["a"]}
        p, _ = claude([tool_block("t", "w", raw)])
        call = p.complete(AIRequest(prompt="p")).tool_calls[0]
        raw["where"]["lat"] = 99
        raw["tags"].append("b")
        assert call.arguments["where"]["lat"] == 1 and call.arguments["tags"] == ("a",)
        with pytest.raises(TypeError):
            call.arguments["where"]["lat"] = 2  # type: ignore[index]

    def test_unknown_blocks_ignored_as_before(self) -> None:
        blocks = [SimpleNamespace(type="thinking", thinking="..."), SimpleNamespace(type="image"),
                  SimpleNamespace(text="legacy-shape"), tool_block("t1")]
        p, _ = claude(blocks)
        r = p.complete(AIRequest(prompt="p"))
        assert r.text == "legacy-shape" and [c.call_id for c in r.tool_calls] == ["t1"]

    def test_no_sdk_objects_escape(self) -> None:
        p, _ = claude([text_block("t"), tool_block()])
        r = p.complete(AIRequest(prompt="p"))
        assert type(r) is AIResponse and all(type(c) is ToolCall for c in r.tool_calls)
        assert not isinstance(r.tool_calls[0].arguments, dict)


# ── malformed tool_use blocks ───────────────────────────────────────────


class TestMalformed:
    @pytest.mark.parametrize("block, reason", [
        (SimpleNamespace(type="tool_use", name="w", input={}), "id is missing or invalid"),
        (tool_block(call_id=""), "id is missing or invalid"),
        (tool_block(call_id="  "), "id is missing or invalid"),
        (tool_block(call_id=7), "id is missing or invalid"),
        (SimpleNamespace(type="tool_use", id="t", input={}), "name is missing or invalid"),
        (tool_block(name=""), "name is missing or invalid"),
        (tool_block(name=3), "name is missing or invalid"),
        (tool_block(input=[1, 2]), "input is not a mapping"),
        (tool_block(input=SECRET), "input is not a mapping"),
        (SimpleNamespace(type="tool_use", id="t", name="w"), "input is not a mapping"),
    ])
    def test_structural_errors(self, block: SimpleNamespace, reason: str) -> None:
        p, _ = claude([text_block("ok"), block])
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest(prompt="p"))
        assert str(info.value) == f"content block 1: tool_use {reason}"
        assert SECRET not in str(info.value)

    @pytest.mark.parametrize("bad", [{"x": object()}, {"x": {1: "v"}}, {"x": [{SECRET: {3}}]}])
    def test_invalid_nested_arguments_keep_cause(self, bad: dict) -> None:
        p, _ = claude([tool_block("t", "w", bad)])
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest(prompt="p"))
        assert str(info.value) == "content block 0: tool_use input is not valid tool-call arguments"
        assert isinstance(info.value.__cause__, (TypeError, ValueError))
        assert SECRET not in str(info.value)

    def test_duplicate_ids_keep_cause(self) -> None:
        p, _ = claude([tool_block(SECRET, "a", {}), tool_block(SECRET, "b", {})])
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest(prompt="p"))
        assert str(info.value) == "duplicate tool_use id in response"
        assert isinstance(info.value.__cause__, ValueError) and SECRET not in str(info.value)

    def test_malformed_block_never_dropped_even_with_valid_ones(self) -> None:
        p, _ = claude([tool_block("ok1"), tool_block(call_id=None), tool_block("ok2")])
        with pytest.raises(ToolCallNormalizationError, match="content block 1"):
            p.complete(AIRequest(prompt="p"))

    def test_error_types(self) -> None:
        assert issubclass(ToolCallNormalizationError, ValueError)
        assert not issubclass(ToolCallingUnsupportedError, ValueError)


# ── AIService: forwarding + unsupported providers ──────────────────────


class CapableCapture:
    name = "capable"
    supports_tool_calling = True

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse("ok", self.name)


class PlainCapture(CapableCapture):
    name = "plain"
    supports_tool_calling = False


class NoFlagCapture:
    name = "noflag"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: AIRequest) -> AIResponse:
        self.calls += 1
        return AIResponse("ok", self.name)


class TestAIService:
    def _service(self, **kw) -> tuple[AIService, CapableCapture]:
        s = AIService(**kw)
        cap = CapableCapture()
        s._registry.register(cap)  # noqa: SLF001 - test double
        return s, cap

    def test_tools_forwarded_single_turn(self) -> None:
        s, cap = self._service()
        req = AIRequest(prompt="p", tools=[spec()])
        s.complete("capable", req)
        assert cap.requests[0] is req

    def test_tools_forwarded_with_history(self) -> None:
        s, cap = self._service()
        h = ConversationHistory()
        h.extend([Message("user", "u"), Message("assistant", "a")])
        tools = (spec("a"), spec("b"))
        s.complete("capable", AIRequest(prompt="p", tools=tools), history=h)
        assert cap.requests[0].tools == tools and cap.requests[0].history.messages() == h.messages()

    def test_tools_forwarded_on_system_and_memory_path(self) -> None:
        s, cap = self._service(system="SYS")
        e = MemoryEngine()
        e.remember("prefs", "k", "p fact")
        tools = (spec(),)
        s.complete("capable", AIRequest(prompt="p", tools=tools), memory=MemoryRequest(e))
        sent = cap.requests[0]
        assert sent.tools == tools and sent.system.startswith("SYS")

    @pytest.mark.parametrize("provider_name", ["openai", "gemini", "ollama"])
    def test_builtin_unsupported_providers_rejected_before_invocation(
            self, provider_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
        s = AIService()
        provider = s.router.select(provider_name)
        called: list[str] = []
        monkeypatch.setattr(provider, "complete", lambda request: called.append("x"))
        with pytest.raises(ToolCallingUnsupportedError, match=provider_name):
            s.complete(provider_name, AIRequest(prompt="p", tools=[spec()]))
        assert called == []

    @pytest.mark.parametrize("fake", [PlainCapture, NoFlagCapture])
    def test_custom_provider_without_capability_rejected(self, fake: type) -> None:
        s = AIService()
        provider = fake()
        s._registry.register(provider)  # noqa: SLF001
        with pytest.raises(ToolCallingUnsupportedError):
            s.complete(provider.name, AIRequest(prompt="p", tools=[spec()]))
        assert getattr(provider, "calls", len(getattr(provider, "requests", []))) == 0

    def test_truthy_non_true_capability_is_not_support(self) -> None:
        s = AIService()
        provider = NoFlagCapture()
        provider.supports_tool_calling = "yes"  # type: ignore[attr-defined]
        s._registry.register(provider)  # noqa: SLF001
        with pytest.raises(ToolCallingUnsupportedError):
            s.complete("noflag", AIRequest(prompt="p", tools=[spec()]))

    def test_unsupported_providers_work_without_tools(self) -> None:
        s = AIService()
        provider = NoFlagCapture()
        s._registry.register(provider)  # noqa: SLF001
        assert s.complete("noflag", AIRequest(prompt="p")).text == "ok" and provider.calls == 1

    def test_claude_capability_and_end_to_end(self) -> None:
        assert ClaudeProvider.supports_tool_calling is True
        s = AIService()
        claude_provider = s.router.select("claude")
        msgs = FakeMessages([text_block("checking"), tool_block("toolu_X", "weather", {"city": "Oslo"})])
        claude_provider._client = SimpleNamespace(messages=msgs)  # noqa: SLF001 - fake SDK client
        r = s.complete("claude", AIRequest(prompt="weather?", tools=[spec()]))
        assert r.text == "checking" and r.tool_calls == (ToolCall("toolu_X", "weather", {"city": "Oslo"}),)
        assert msgs.calls[0]["tools"][0]["name"] == "weather"


# ── architecture ────────────────────────────────────────────────────────


def _imports(path: str) -> set[str]:
    tree = ast.parse(open(path, encoding="utf-8").read())
    return {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


class TestArchitecture:
    def test_tool_calling_stays_provider_neutral(self) -> None:
        assert _imports(os.path.join(CORE_DIR, "tool_calling.py")) == {
            "__future__", "collections.abc", "dataclasses", "types"}

    def test_aiservice_has_no_provider_specific_logic(self) -> None:
        src = open(os.path.join(CORE_DIR, "ai_service.py"), encoding="utf-8").read()
        for token in ("input_schema", "tool_use", "anthropic", "claude", "openai", "gemini", "ollama"):
            assert token not in src.lower(), token
        assert not [m for m in _imports(os.path.join(CORE_DIR, "ai_service.py")) if "tool_catalog" in m]

    def test_only_claude_knows_the_native_format(self) -> None:
        for dirpath, _, files in os.walk(CORE_DIR):
            for name in files:
                if name.endswith(".py") and name != "claude_provider.py":
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        assert "input_schema" not in f.read(), name

    def test_other_providers_untouched_and_no_capability(self) -> None:
        from core.gemini_provider import GeminiProvider
        from core.ollama_provider import OllamaProvider
        from core.openai_provider import OpenAIProvider
        for cls in (OpenAIProvider, GeminiProvider, OllamaProvider):
            assert not hasattr(cls, "supports_tool_calling"), cls.__name__

    def test_no_new_dependency_or_network(self) -> None:
        mods = _imports(os.path.join(CORE_DIR, "claude_provider.py"))
        assert mods == {"__future__", "typing", "core.ai_provider", "core.tool_calling", "anthropic"}
