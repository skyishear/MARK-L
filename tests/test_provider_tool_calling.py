"""Tests for v8.40 tool calling on OpenAI, Gemini and Ollama (owner decision OD-4b).

Each provider module is the only place that knows its native tool format. The
tests use duck-typed fakes (no SDK needed) and pin: declarations only when tools
are offered and never the policy flags, native replay of ``tool_exchanges``,
normalization into neutral ``ToolCall``s (verbatim ids; the positional-id
fallback for Gemini / Ollama), fail-closed handling of cut-off or malformed
calls, byte-identical payloads when no tools are offered, and an end-to-end
two-round run through ``AIService`` + the v8.39 loop for every provider.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from core.ai_provider import AIRequest, AIResponse, ToolCallNormalizationError
from core.ai_service import AIService
from core.conversation_history import ConversationHistory, Message
from core.gemini_provider import GeminiProvider
from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider
from core.tool_calling import ToolCall, ToolCallResult, ToolExchange
from core.tool_catalog import ToolSpec
from core.tool_interface import ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter
from core.tool_runtime import run_tool_loop

CORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core")
PARAMS = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["city"],
    "additionalProperties": False,
}


def spec(name: str = "weather", **kw: object) -> ToolSpec:
    kw.setdefault("model_invocable", True)
    return ToolSpec(name, f"{name} tool", PARAMS, **kw)  # type: ignore[arg-type]


EXCHANGE = ToolExchange(
    calls=(ToolCall("c1", "weather", {"city": "Rome", "tags": ["a", "b"]}),
           ToolCall("c2", "time", {"city": "Rome"})),
    results=(ToolCallResult("c1", "weather", "sunny"), ToolCallResult("c2", "time", "noon")),
    text="Checking",
)


def history() -> ConversationHistory:
    h = ConversationHistory()
    h.extend([Message("user", "u0"), Message("assistant", "a0")])
    return h


# ═══════════════════════════ OpenAI ═══════════════════════════════════════


def oai_call(call_id: object = "call_1", name: object = "weather", arguments: object = '{"city": "Paris"}',
             type_: object = "function") -> SimpleNamespace:
    return SimpleNamespace(id=call_id, type=type_, function=SimpleNamespace(name=name, arguments=arguments))


class OAIClient:
    def __init__(self, content: object = "", tool_calls: object = None, finish_reason: object = "stop") -> None:
        self.calls: list[dict] = []
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        self._response = SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._response


def openai(**kw: object) -> tuple[OpenAIProvider, OAIClient]:
    client = OAIClient(**kw)
    return OpenAIProvider(client=client), client


class TestOpenAIRequest:
    def test_capability(self) -> None:
        assert OpenAIProvider.supports_tool_calling is True

    def test_no_tools_payload_is_unchanged(self) -> None:
        p, c = openai(content="hi")
        p.complete(AIRequest("p"))
        assert c.calls[0] == {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "p"}]}

    def test_declaration_shape_and_policy_flags_never_sent(self) -> None:
        p, c = openai(content="ok")
        p.complete(AIRequest("p", tools=[spec(idempotent=True, side_effects=False)]))
        assert c.calls[0]["tools"] == [{"type": "function", "function": {
            "name": "weather", "description": "weather tool", "parameters": PARAMS}}]
        assert "idempotent" not in repr(c.calls) and "side_effects" not in repr(c.calls)

    def test_parameters_are_plain_unaliased_copies(self) -> None:
        s = spec()
        p, c = openai(content="ok")
        p.complete(AIRequest("p", tools=[s]))
        schema = c.calls[0]["tools"][0]["function"]["parameters"]
        assert type(schema) is dict and type(schema["properties"]) is dict and type(schema["required"]) is list
        schema["properties"]["city"]["type"] = "integer"
        assert s.parameters["properties"]["city"]["type"] == "string"

    def test_exchange_is_replayed_natively_after_system_history_and_prompt(self) -> None:
        p, c = openai(content="done")
        p.complete(AIRequest("p", history=history(), system="S", tools=[spec(), spec("time")], tool_exchanges=[EXCHANGE]))
        m = c.calls[0]["messages"]
        assert [x["role"] for x in m] == ["system", "user", "assistant", "user", "assistant", "tool", "tool"]
        assert m[3] == {"role": "user", "content": "p"}
        assistant = m[4]
        assert assistant["content"] == "Checking"
        assert [t["id"] for t in assistant["tool_calls"]] == ["c1", "c2"]
        assert assistant["tool_calls"][0] == {"id": "c1", "type": "function", "function": {
            "name": "weather", "arguments": json.dumps({"city": "Rome", "tags": ["a", "b"]})}}
        assert m[5] == {"role": "tool", "tool_call_id": "c1", "content": "sunny"}
        assert m[6] == {"role": "tool", "tool_call_id": "c2", "content": "noon"}

    def test_empty_round_text_becomes_null_content(self) -> None:
        p, c = openai(content="done")
        e = ToolExchange(calls=EXCHANGE.calls, results=EXCHANGE.results)
        p.complete(AIRequest("p", tools=[spec()], tool_exchanges=[e]))
        assert c.calls[0]["messages"][1]["content"] is None


class TestOpenAIResponse:
    def test_text_only(self) -> None:
        p, _ = openai(content="hello")
        assert p.complete(AIRequest("p")) == AIResponse("hello", "openai")

    def test_tool_calls_normalized_in_order_with_verbatim_ids(self) -> None:
        p, _ = openai(content="", tool_calls=[oai_call("call_B", "weather", '{"city": "Rome", "tags": ["x"]}'),
                                              oai_call("call_A", "time", "{}")], finish_reason="tool_calls")
        r = p.complete(AIRequest("p", tools=[spec(), spec("time")]))
        assert r.tool_calls == (ToolCall("call_B", "weather", {"city": "Rome", "tags": ["x"]}),
                                ToolCall("call_A", "time", {}))

    def test_no_sdk_objects_escape(self) -> None:
        p, _ = openai(tool_calls=[oai_call()], finish_reason="tool_calls")
        r = p.complete(AIRequest("p", tools=[spec()]))
        assert all(type(c) is ToolCall for c in r.tool_calls)

    @pytest.mark.parametrize("raw", [
        oai_call(call_id=None), oai_call(call_id=" "), oai_call(name=None), oai_call(name=""),
        oai_call(arguments="not json"), oai_call(arguments='["a"]'), oai_call(arguments=None),
        oai_call(type_="custom"),
    ])
    def test_malformed_calls_raise_structurally_and_are_never_dropped(self, raw: SimpleNamespace) -> None:
        p, _ = openai(tool_calls=[oai_call("ok"), raw], finish_reason="tool_calls")
        with pytest.raises((ToolCallNormalizationError, ValueError)) as info:
            p.complete(AIRequest("p", tools=[spec()]))
        assert "Paris" not in str(info.value)

    def test_duplicate_ids_rejected(self) -> None:
        p, _ = openai(tool_calls=[oai_call("same"), oai_call("same")], finish_reason="tool_calls")
        with pytest.raises(ToolCallNormalizationError):
            p.complete(AIRequest("p", tools=[spec()]))

    @pytest.mark.parametrize("reason", ["length", "content_filter"])
    def test_cut_off_tool_call_is_never_returned(self, reason: str) -> None:
        p, _ = openai(tool_calls=[oai_call()], finish_reason=reason)
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest("p", tools=[spec()]))
        assert reason in str(info.value)

    @pytest.mark.parametrize("reason", ["stop", "tool_calls", None])
    def test_normal_finish_reasons_pass(self, reason: object) -> None:
        p, _ = openai(tool_calls=[oai_call("call_9")], finish_reason=reason)
        assert p.complete(AIRequest("p", tools=[spec()])).tool_calls[0].call_id == "call_9"

    def test_length_without_tool_calls_is_unchanged(self) -> None:
        p, _ = openai(content="partial", finish_reason="length")
        assert p.complete(AIRequest("p")).text == "partial"


# ═══════════════════════════ Gemini ═══════════════════════════════════════


def gem_part(name: str = "weather", args: object = None, call_id: object = None) -> SimpleNamespace:
    return SimpleNamespace(function_call=SimpleNamespace(name=name, args={"city": "Paris"} if args is None else args, id=call_id))


class GemClient:
    def __init__(self, parts: list | None = None, text: str = "", finish_reason: object = "STOP") -> None:
        self.calls: list[dict] = []
        candidate = SimpleNamespace(content=SimpleNamespace(parts=parts or []), finish_reason=finish_reason)
        self._response = SimpleNamespace(text=text, candidates=[candidate])
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._response


def gemini(**kw: object) -> tuple[GeminiProvider, GemClient]:
    client = GemClient(**kw)
    return GeminiProvider(client=client), client


class TestGeminiRequest:
    def test_capability(self) -> None:
        assert GeminiProvider.supports_tool_calling is True

    def test_no_tools_payload_is_unchanged(self) -> None:
        p, c = gemini(text="hi")
        p.complete(AIRequest("p"))
        assert c.calls[0] == {"model": "gemini-2.5-pro", "contents": "p"}
        p.complete(AIRequest("p", system="S", history=history()))
        assert c.calls[1]["contents"][0] == {"role": "user", "content": "u0"}  # pre-existing shape, pinned by v7.2
        assert c.calls[1]["config"] == {"system_instruction": "S"}

    def test_declaration_shape_and_system_instruction(self) -> None:
        p, c = gemini(text="ok")
        p.complete(AIRequest("p", system="Be brief.", tools=[spec(idempotent=True, side_effects=False)]))
        config = c.calls[0]["config"]
        assert config["system_instruction"] == "Be brief."
        assert config["tools"] == [{"function_declarations": [{
            "name": "weather", "description": "weather tool", "parameters_json_schema": PARAMS}]}]
        assert "idempotent" not in repr(c.calls) and "side_effects" not in repr(c.calls)

    def test_native_contents_with_model_role_and_parts(self) -> None:
        p, c = gemini(text="done")
        p.complete(AIRequest("p", history=history(), tools=[spec(), spec("time")], tool_exchanges=[EXCHANGE]))
        contents = c.calls[0]["contents"]
        assert [x["role"] for x in contents] == ["user", "model", "user", "model", "user"]
        assert contents[0] == {"role": "user", "parts": [{"text": "u0"}]}
        assert contents[1] == {"role": "model", "parts": [{"text": "a0"}]}  # assistant -> model
        assert contents[2] == {"role": "user", "parts": [{"text": "p"}]}
        assert contents[3]["parts"][0] == {"text": "Checking"}
        assert contents[3]["parts"][1] == {"function_call": {"name": "weather", "args": {"city": "Rome", "tags": ["a", "b"]}}}
        assert contents[4]["parts"] == [
            {"function_response": {"name": "weather", "response": {"output": "sunny"}}},
            {"function_response": {"name": "time", "response": {"output": "noon"}}},
        ]

    def test_args_are_plain_unaliased_copies(self) -> None:
        p, c = gemini(text="done")
        p.complete(AIRequest("p", tools=[spec(), spec("time")], tool_exchanges=[EXCHANGE]))
        sent = c.calls[0]["contents"][1]["parts"][1]["function_call"]["args"]
        assert type(sent) is dict and type(sent["tags"]) is list
        sent["tags"].append("z")
        assert EXCHANGE.calls[0].arguments["tags"] == ("a", "b")


class TestGeminiResponse:
    def test_function_calls_get_positional_ids_when_the_sdk_gives_none(self) -> None:
        p, _ = gemini(parts=[gem_part("weather", {"city": "Rome"}), gem_part("time", {})])
        r = p.complete(AIRequest("p", tools=[spec(), spec("time")]))
        assert r.tool_calls == (ToolCall("call_1", "weather", {"city": "Rome"}), ToolCall("call_2", "time", {}))

    def test_native_ids_are_kept_verbatim(self) -> None:
        p, _ = gemini(parts=[gem_part("weather", call_id="fc-77")])
        assert p.complete(AIRequest("p", tools=[spec()])).tool_calls[0].call_id == "fc-77"

    def test_missing_args_become_an_empty_mapping(self) -> None:
        part = SimpleNamespace(function_call=SimpleNamespace(name="weather", args=None, id=None))
        p, _ = gemini(parts=[part])
        assert p.complete(AIRequest("p", tools=[spec()])).tool_calls[0].arguments == {}

    def test_text_parts_are_ignored_and_text_is_taken_from_the_response(self) -> None:
        p, _ = gemini(parts=[SimpleNamespace(text="hi", function_call=None), gem_part()], text="hi")
        r = p.complete(AIRequest("p", tools=[spec()]))
        assert r.text == "hi" and len(r.tool_calls) == 1

    def test_no_candidates_means_no_calls(self) -> None:
        client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **k: SimpleNamespace(text="t", candidates=None)))
        r = GeminiProvider(client=client).complete(AIRequest("p", tools=[spec()]))
        assert r == AIResponse("t", "gemini")

    @pytest.mark.parametrize("raw", [gem_part(name=""), gem_part(args="not a mapping"), gem_part(args=[1])])
    def test_malformed_calls_raise(self, raw: SimpleNamespace) -> None:
        p, _ = gemini(parts=[gem_part(), raw])
        with pytest.raises(ToolCallNormalizationError):
            p.complete(AIRequest("p", tools=[spec()]))

    def test_duplicate_native_ids_rejected(self) -> None:
        p, _ = gemini(parts=[gem_part(call_id="x"), gem_part(call_id="x")])
        with pytest.raises(ToolCallNormalizationError):
            p.complete(AIRequest("p", tools=[spec()]))

    @pytest.mark.parametrize("reason", ["MAX_TOKENS", "SAFETY", "MALFORMED_FUNCTION_CALL", "BLOCKLIST"])
    def test_cut_off_or_blocked_calls_are_never_returned(self, reason: str) -> None:
        p, _ = gemini(parts=[gem_part()], finish_reason=reason)
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest("p", tools=[spec()]))
        assert reason in str(info.value)

    def test_enum_style_finish_reasons_are_read_by_name(self) -> None:
        p, _ = gemini(parts=[gem_part()], finish_reason=SimpleNamespace(name="MAX_TOKENS"))
        with pytest.raises(ToolCallNormalizationError):
            p.complete(AIRequest("p", tools=[spec()]))
        p, _ = gemini(parts=[gem_part()], finish_reason=SimpleNamespace(name="STOP"))
        assert len(p.complete(AIRequest("p", tools=[spec()])).tool_calls) == 1

    @pytest.mark.parametrize("reason", [None, "STOP", "FINISH_REASON_UNSPECIFIED"])
    def test_complete_finish_reasons_pass(self, reason: object) -> None:
        p, _ = gemini(parts=[gem_part()], finish_reason=reason)
        assert len(p.complete(AIRequest("p", tools=[spec()])).tool_calls) == 1


# ═══════════════════════════ Ollama ═══════════════════════════════════════


def oll_call(name: object = "weather", arguments: object = None) -> SimpleNamespace:
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments={"city": "Paris"} if arguments is None else arguments))


class OllClient:
    def __init__(self, content: object = "", tool_calls: object = None, done_reason: object = "stop", as_dict: bool = False) -> None:
        self.chat_calls: list[dict] = []
        self.generate_calls: list[dict] = []
        if as_dict:
            self._chat = {"message": {"content": content, "tool_calls": [
                {"function": {"name": c.function.name, "arguments": c.function.arguments}} for c in (tool_calls or [])]},
                "done_reason": done_reason}
        else:
            self._chat = SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls), done_reason=done_reason)

    def chat(self, **kwargs: object) -> object:
        self.chat_calls.append(kwargs)
        return self._chat

    def generate(self, **kwargs: object) -> dict:
        self.generate_calls.append(kwargs)
        return {"response": "plain"}


def ollama(**kw: object) -> tuple[OllamaProvider, OllClient]:
    client = OllClient(**kw)
    return OllamaProvider(client=client), client


class TestOllamaRequest:
    def test_capability(self) -> None:
        assert OllamaProvider.supports_tool_calling is True

    def test_no_tools_still_uses_generate_unchanged(self) -> None:
        p, c = ollama()
        assert p.complete(AIRequest("p")).text == "plain"
        assert c.generate_calls == [{"model": "llama3.1", "prompt": "p"}] and c.chat_calls == []

    def test_tools_use_chat_with_native_declarations(self) -> None:
        p, c = ollama(content="ok")
        p.complete(AIRequest("p", tools=[spec(idempotent=True, side_effects=False)]))
        assert c.generate_calls == []
        call = c.chat_calls[0]
        assert call["model"] == "llama3.1" and call["messages"] == [{"role": "user", "content": "p"}]
        assert call["tools"] == [{"type": "function", "function": {
            "name": "weather", "description": "weather tool", "parameters": PARAMS}}]
        assert "idempotent" not in repr(c.chat_calls) and "side_effects" not in repr(c.chat_calls)

    def test_system_history_prompt_and_exchange_replay(self) -> None:
        p, c = ollama(content="done")
        p.complete(AIRequest("p", history=history(), system="S", tools=[spec(), spec("time")], tool_exchanges=[EXCHANGE]))
        m = c.chat_calls[0]["messages"]
        assert [x["role"] for x in m] == ["system", "user", "assistant", "user", "assistant", "tool", "tool"]
        assert m[4] == {"role": "assistant", "content": "Checking", "tool_calls": [
            {"function": {"name": "weather", "arguments": {"city": "Rome", "tags": ["a", "b"]}}},
            {"function": {"name": "time", "arguments": {"city": "Rome"}}}]}
        assert m[5] == {"role": "tool", "tool_name": "weather", "content": "sunny"}
        assert m[6] == {"role": "tool", "tool_name": "time", "content": "noon"}

    def test_arguments_are_plain_unaliased_copies(self) -> None:
        p, c = ollama(content="done")
        p.complete(AIRequest("p", tools=[spec(), spec("time")], tool_exchanges=[EXCHANGE]))
        sent = c.chat_calls[0]["messages"][1]["tool_calls"][0]["function"]["arguments"]
        assert type(sent) is dict and type(sent["tags"]) is list


class TestOllamaResponse:
    @pytest.mark.parametrize("as_dict", [False, True])
    def test_positional_ids_in_response_order(self, as_dict: bool) -> None:
        p, _ = ollama(tool_calls=[oll_call("weather", {"city": "Rome"}), oll_call("time", {})], as_dict=as_dict)
        r = p.complete(AIRequest("p", tools=[spec(), spec("time")]))
        assert r.tool_calls == (ToolCall("call_1", "weather", {"city": "Rome"}), ToolCall("call_2", "time", {}))

    def test_text_content_is_returned(self) -> None:
        p, _ = ollama(content="thinking aloud", tool_calls=[oll_call()])
        assert p.complete(AIRequest("p", tools=[spec()])).text == "thinking aloud"

    def test_missing_arguments_become_an_empty_mapping(self) -> None:
        call = SimpleNamespace(function=SimpleNamespace(name="weather", arguments=None))
        p, _ = ollama(tool_calls=[call])
        assert p.complete(AIRequest("p", tools=[spec()])).tool_calls[0].arguments == {}

    @pytest.mark.parametrize("raw", [oll_call(name=""), oll_call(name=None), oll_call(arguments="nope"), oll_call(arguments=[1])])
    def test_malformed_calls_raise(self, raw: SimpleNamespace) -> None:
        p, _ = ollama(tool_calls=[oll_call(), raw])
        with pytest.raises(ToolCallNormalizationError):
            p.complete(AIRequest("p", tools=[spec()]))

    def test_cut_off_tool_call_is_never_returned(self) -> None:
        p, _ = ollama(tool_calls=[oll_call()], done_reason="length")
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest("p", tools=[spec()]))
        assert "length" in str(info.value)

    def test_length_without_tool_calls_is_unchanged(self) -> None:
        p, _ = ollama(content="partial", done_reason="length")
        assert p.complete(AIRequest("p", tools=[spec()])).text == "partial"


# ═══════════════ end to end: AIService + the v8.39 loop, every provider ═══════════════


class Echo:
    name = "echo"
    description = "echo"

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult("echo", f"echoed {dict(request.arguments)['text']}")


def _loop(provider_name: str, provider: object) -> tuple[object, Echo, AIService]:
    service = AIService()
    service.router.select(provider_name)._client = provider  # noqa: SLF001 - fake SDK client
    tool = Echo()
    registry = ToolRegistry()
    registry.register(tool)
    s = ToolSpec("echo", "echo text", {"type": "object", "properties": {"text": {"type": "string"}}}, side_effects=False, model_invocable=True)
    result = run_tool_loop(
        lambda request: service.complete(provider_name, request),
        prompt="say hi", tools=[s], router=ToolRouter(registry), registry=registry,
    )
    return result, tool, service


class TestEndToEnd:
    def test_openai_two_round_run(self) -> None:
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
                content="", tool_calls=[oai_call("call_1", "echo", '{"text": "hi"}')]))]),
            SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="done", tool_calls=None))]),
        ]
        sent: list[dict] = []

        def create(**kwargs: object) -> SimpleNamespace:
            sent.append(kwargs)
            return responses.pop(0)

        result, tool, _ = _loop("openai", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        assert result.response.text == "done" and (result.rounds, result.tool_executions) == (2, 1)
        assert tool.calls[0].arguments["text"] == "hi"
        assert sent[1]["messages"][-1] == {"role": "tool", "tool_call_id": "call_1", "content": "echoed hi"}

    def test_gemini_two_round_run(self) -> None:
        responses = [
            SimpleNamespace(text="", candidates=[SimpleNamespace(finish_reason="STOP", content=SimpleNamespace(
                parts=[gem_part("echo", {"text": "hi"})]))]),
            SimpleNamespace(text="done", candidates=[SimpleNamespace(finish_reason="STOP", content=SimpleNamespace(parts=[]))]),
        ]
        sent: list[dict] = []

        def generate(**kwargs: object) -> SimpleNamespace:
            sent.append(kwargs)
            return responses.pop(0)

        result, tool, _ = _loop("gemini", SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        assert result.response.text == "done" and result.tool_executions == 1
        assert sent[1]["contents"][-1]["parts"][0]["function_response"] == {"name": "echo", "response": {"output": "echoed hi"}}
        assert result.outcomes[0].call_id == "call_1"  # positional id

    def test_ollama_two_round_run(self) -> None:
        responses = [
            SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[oll_call("echo", {"text": "hi"})]), done_reason="stop"),
            SimpleNamespace(message=SimpleNamespace(content="done", tool_calls=None), done_reason="stop"),
        ]
        sent: list[dict] = []

        def chat(**kwargs: object) -> SimpleNamespace:
            sent.append(kwargs)
            return responses.pop(0)

        result, tool, _ = _loop("ollama", SimpleNamespace(chat=chat))
        assert result.response.text == "done" and result.tool_executions == 1
        assert sent[1]["messages"][-1] == {"role": "tool", "tool_name": "echo", "content": "echoed hi"}

    def test_a_cut_off_call_stops_the_run_before_any_execution(self) -> None:
        def create(**kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(
                content="", tool_calls=[oai_call("call_1", "echo", '{"text": "h')]))])

        service = AIService()
        service.router.select("openai")._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))  # noqa: SLF001
        tool = Echo()
        registry = ToolRegistry()
        registry.register(tool)
        s = ToolSpec("echo", "e", {"type": "object"}, side_effects=False, model_invocable=True)
        with pytest.raises(ToolCallNormalizationError):
            run_tool_loop(lambda r: service.complete("openai", r), prompt="p", tools=[s],
                          router=ToolRouter(registry), registry=registry)
        assert tool.calls == []


# ═══════════════ architecture ═══════════════


class TestArchitecture:
    @pytest.mark.parametrize("module", ["openai_provider", "gemini_provider", "ollama_provider"])
    def test_sdk_imports_stay_lazy_and_core_imports_are_limited(self, module: str) -> None:
        import ast

        with open(os.path.join(CORE_DIR, f"{module}.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        top_level = {n.module for n in tree.body if isinstance(n, ast.ImportFrom)} | {
            a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
        assert top_level <= {"__future__", "json", "typing", "core.ai_provider", "core.tool_calling"}, top_level

    def test_native_formats_stay_inside_their_provider_modules(self) -> None:
        owners = {
            "input_schema": {"claude_provider.py"},
            "tool_call_id": {"openai_provider.py"},
            "function_declarations": {"gemini_provider.py"},
            "parameters_json_schema": {"gemini_provider.py"},
            "function_response": {"gemini_provider.py"},
        }
        for name in os.listdir(CORE_DIR):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                source = f.read()
            for token, allowed in owners.items():
                if name not in allowed:
                    assert token not in source, (token, name)
        with open(os.path.join(CORE_DIR, "ai_service.py"), encoding="utf-8") as f:
            service_source = f.read().lower()
        for token in ("tool_name", "tool_calls", "function_call"):
            assert token not in service_source, token
