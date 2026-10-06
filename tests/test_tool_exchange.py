"""Tests for v8.39 tool exchanges: ``ToolExchange``, ``AIRequest.tool_exchanges``,
the Claude follow-up mapping, the R-2 hardening and ``AIService`` forwarding.

Owner decisions covered: OD-B (loop-local carrier, canonical history unchanged),
O2 (results carry sanitized text only; no error flag is sent), and the C8 audit
confirmations (R-2).
"""

from __future__ import annotations

import dataclasses
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
from core.tool_calling import ToolCall, ToolCallResult, ToolExchange
from core.tool_catalog import ToolSpec

PARAMS = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["city"],
}


def spec(name: str = "weather", **kw: object) -> ToolSpec:
    kw.setdefault("model_invocable", True)
    return ToolSpec(name, f"{name} tool", PARAMS, **kw)  # type: ignore[arg-type]


def call(call_id: str = "c1", name: str = "weather", **arguments: object) -> ToolCall:
    return ToolCall(call_id, name, arguments or {"city": "Rome"})


def result(call_id: str = "c1", name: str = "weather", output: str = "sunny") -> ToolCallResult:
    return ToolCallResult(call_id, name, output)


def exchange(*pairs: tuple[str, str], text: str = "") -> ToolExchange:
    return ToolExchange(
        calls=tuple(call(i, n) for i, n in pairs),
        results=tuple(result(i, n, f"out-{i}") for i, n in pairs),
        text=text,
    )


# ── ToolExchange ────────────────────────────────────────────────────────


class TestToolExchange:
    def test_fields_exact_and_defaults(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolExchange)] == ["calls", "results", "text"]
        e = ToolExchange(calls=(call(),), results=(result(),))
        assert e.text == ""

    def test_lists_become_tuples_and_order_kept(self) -> None:
        e = ToolExchange(calls=[call("a"), call("b")], results=[result("a"), result("b")], text="hi")  # type: ignore[arg-type]
        assert isinstance(e.calls, tuple) and isinstance(e.results, tuple)
        assert [c.call_id for c in e.calls] == ["a", "b"]
        assert [r.call_id for r in e.results] == ["a", "b"] and e.text == "hi"

    def test_frozen_and_slotted(self) -> None:
        e = exchange(("a", "weather"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.text = "x"  # type: ignore[misc]
        assert not hasattr(e, "__dict__")

    def test_empty_calls_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolExchange(calls=(), results=())

    def test_one_result_per_call(self) -> None:
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a"), call("b")), results=(result("a"),))
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a"),), results=(result("a"), result("b")))

    def test_results_must_match_calls_by_id_name_and_order(self) -> None:
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a"),), results=(result("zzz"),))
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a", "weather"),), results=(result("a", "other"),))
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a"), call("b")), results=(result("b"), result("a")))

    def test_duplicate_call_ids_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolExchange(calls=(call("a"), call("a")), results=(result("a"), result("a")))

    def test_type_validation(self) -> None:
        with pytest.raises(TypeError):
            ToolExchange(calls=(call("a"),), results="a")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ToolExchange(calls=(call("a"),), results=({"call_id": "a"},))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ToolExchange(calls=(call("a"),), results=(result("a"),), text=5)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ToolExchange(calls=("a",), results=(result("a"),))  # type: ignore[arg-type]


# ── AIRequest.tool_exchanges ────────────────────────────────────────────


class TestAIRequestToolExchanges:
    def test_default_empty_and_positional_compatibility(self) -> None:
        r = AIRequest("p")
        assert r.tool_exchanges == ()
        assert [f.name for f in dataclasses.fields(AIRequest)][-1] == "tool_exchanges"
        assert AIRequest("p", None, "S", (spec(),)).system == "S"  # earlier positions unchanged

    def test_valid_collection_converted_to_tuple(self) -> None:
        e = exchange(("a", "weather"))
        r = AIRequest("p", tools=[spec()], tool_exchanges=[e])  # type: ignore[arg-type]
        assert r.tool_exchanges == (e,) and isinstance(r.tool_exchanges, tuple)

    def test_requires_tools(self) -> None:
        with pytest.raises(ValueError):
            AIRequest("p", tool_exchanges=(exchange(("a", "weather")),))

    def test_type_validation(self) -> None:
        with pytest.raises(TypeError):
            AIRequest("p", tools=[spec()], tool_exchanges="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            AIRequest("p", tools=[spec()], tool_exchanges=[call()])  # type: ignore[list-item]

    def test_frozen(self) -> None:
        r = AIRequest("p")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.tool_exchanges = ()  # type: ignore[misc]


# ── Claude follow-up mapping (OD-B / O2) ────────────────────────────────


class Messages:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.response


def claude(blocks: list, **attrs: object) -> tuple[ClaudeProvider, Messages]:
    msgs = Messages(SimpleNamespace(content=blocks, **attrs))
    return ClaudeProvider(client=SimpleNamespace(messages=msgs)), msgs


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(call_id: str = "toolu_1", name: str = "weather", input: object = None) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input={"city": "Paris"} if input is None else input)


class TestClaudeExchangeMapping:
    def test_round_replayed_after_the_user_turn(self) -> None:
        p, msgs = claude([text_block("done")])
        e = ToolExchange(calls=(call("t1", "weather", city="Rome"),), results=(result("t1", "weather", "sunny"),), text="Checking")
        p.complete(AIRequest("p", tools=[spec()], tool_exchanges=[e]))
        assert msgs.calls[0]["messages"] == [
            {"role": "user", "content": "p"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Checking"},
                {"type": "tool_use", "id": "t1", "name": "weather", "input": {"city": "Rome"}},
            ]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "sunny"}]},
        ]

    def test_empty_text_is_omitted_and_all_results_share_one_user_message(self) -> None:
        p, msgs = claude([text_block("done")])
        p.complete(AIRequest("p", tools=[spec()], tool_exchanges=[exchange(("a", "weather"), ("b", "weather"))]))
        assistant, user = msgs.calls[0]["messages"][1:]
        assert [b["type"] for b in assistant["content"]] == ["tool_use", "tool_use"]
        assert [b["tool_use_id"] for b in user["content"]] == ["a", "b"]
        assert [b["content"] for b in user["content"]] == ["out-a", "out-b"]

    def test_multiple_rounds_in_order_after_history_and_prompt(self) -> None:
        p, msgs = claude([text_block("done")])
        h = ConversationHistory()
        h.extend([Message("user", "u0"), Message("assistant", "a0")])
        req = AIRequest("p", history=h, tools=[spec()],
                        tool_exchanges=[exchange(("a", "weather")), exchange(("b", "weather"))])
        p.complete(req)
        roles = [m["role"] for m in msgs.calls[0]["messages"]]
        assert roles == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
        assert msgs.calls[0]["messages"][2] == {"role": "user", "content": "p"}
        assert msgs.calls[0]["messages"][3]["content"][0]["id"] == "a"
        assert msgs.calls[0]["messages"][5]["content"][0]["id"] == "b"

    def test_arguments_are_plain_unaliased_copies(self) -> None:
        p, msgs = claude([text_block("done")])
        e = ToolExchange(calls=(ToolCall("a", "weather", {"city": "X", "tags": ["p", "q"]}),),
                         results=(result("a"),))
        p.complete(AIRequest("p", tools=[spec()], tool_exchanges=[e]))
        sent = msgs.calls[0]["messages"][1]["content"][0]["input"]
        assert type(sent) is dict and type(sent["tags"]) is list
        sent["tags"].append("zz")
        assert e.calls[0].arguments["tags"] == ("p", "q")
        assert isinstance(e.calls[0].arguments, MappingProxyType)

    def test_no_error_flag_is_ever_sent(self) -> None:
        p, msgs = claude([text_block("done")])
        failed = ToolExchange(calls=(call("a"),), results=(result("a", output="error: failed (ToolError)"),))
        p.complete(AIRequest("p", tools=[spec()], tool_exchanges=[failed]))
        assert "is_error" not in repr(msgs.calls)

    def test_no_exchange_payload_identical_to_v8_38(self) -> None:
        p, msgs = claude([text_block("ok")])
        p.complete(AIRequest("p", tools=[spec()]))
        assert [m["role"] for m in msgs.calls[0]["messages"]] == ["user"]
        assert set(msgs.calls[0]) == {"model", "max_tokens", "messages", "tools"}


class TestClaudeCutOffToolCalls:
    @pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
    def test_tool_use_with_cut_off_stop_reason_is_never_returned(self, reason: str) -> None:
        p, _ = claude([tool_block()], stop_reason=reason)
        with pytest.raises(ToolCallNormalizationError) as info:
            p.complete(AIRequest("p", tools=[spec()]))
        assert reason in str(info.value) and "Paris" not in str(info.value)

    @pytest.mark.parametrize("reason", ["max_tokens", "refusal"])
    def test_text_only_with_those_stop_reasons_is_unchanged(self, reason: str) -> None:
        p, _ = claude([text_block("partial text")], stop_reason=reason)
        assert p.complete(AIRequest("p")) == AIResponse("partial text", "claude")

    @pytest.mark.parametrize("reason", ["tool_use", "end_turn", None])
    def test_other_stop_reasons_and_missing_attribute_are_normal(self, reason: object) -> None:
        p, _ = claude([tool_block("toolu_9")], stop_reason=reason)
        r = p.complete(AIRequest("p", tools=[spec()]))
        assert [c.call_id for c in r.tool_calls] == ["toolu_9"]

    def test_missing_stop_reason_attribute_is_normal(self) -> None:
        p, _ = claude([tool_block("toolu_8")])  # response object has no stop_reason at all
        assert p.complete(AIRequest("p", tools=[spec()])).tool_calls[0].call_id == "toolu_8"


# ── AIService forwarding / guard ────────────────────────────────────────


class Capture:
    name = "capable"
    supports_tool_calling = True

    def __init__(self) -> None:
        self.requests: list[AIRequest] = []

    def complete(self, request: AIRequest) -> AIResponse:
        self.requests.append(request)
        return AIResponse("ok", self.name)


class Plain(Capture):
    name = "plain"
    supports_tool_calling = False


def service(*providers: Capture, **kw: object) -> AIService:
    s = AIService(**kw)  # type: ignore[arg-type]
    for p in providers:
        s._registry.register(p)  # noqa: SLF001 - test double
    return s


class TestAIServiceForwarding:
    def test_single_turn_request_is_forwarded_unchanged(self) -> None:
        cap = Capture()
        req = AIRequest("p", tools=[spec()], tool_exchanges=[exchange(("a", "weather"))])
        service(cap).complete("capable", req)
        assert cap.requests[0] is req

    def test_exchanges_survive_the_history_path(self) -> None:
        cap = Capture()
        h = ConversationHistory()
        h.extend([Message("user", "u"), Message("assistant", "a")])
        e = exchange(("a", "weather"))
        service(cap).complete("capable", AIRequest("p", tools=[spec()], tool_exchanges=[e]), history=h)
        assert cap.requests[0].tool_exchanges == (e,)
        assert cap.requests[0].history.messages() == h.messages()

    def test_exchanges_survive_the_system_path(self) -> None:
        cap = Capture()
        e = exchange(("a", "weather"))
        service(cap, system="Be brief.").complete("capable", AIRequest("p", tools=[spec()], tool_exchanges=[e]))
        assert cap.requests[0].tool_exchanges == (e,) and cap.requests[0].system == "Be brief."

    def test_unsupported_provider_is_rejected_before_invocation(self) -> None:
        plain = Plain()
        with pytest.raises(ToolCallingUnsupportedError):
            service(plain).complete("plain", AIRequest("p", tools=[spec()], tool_exchanges=[exchange(("a", "weather"))]))
        assert plain.requests == []

    def test_no_tools_request_path_is_unchanged(self) -> None:
        cap = Capture()
        req = AIRequest("p")
        service(cap).complete("capable", req)
        assert cap.requests[0] is req and cap.requests[0].tool_exchanges == ()
