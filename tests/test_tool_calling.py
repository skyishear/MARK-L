"""Tests for v8.37 neutral tool-calling types (``core.tool_calling``).

Locked contract: types only — ``ToolCall(call_id, name, arguments)``,
``ToolCallResult(call_id, name, output)``, ``validate_tool_calls(calls)``;
frozen / slotted value objects; non-blank ``call_id`` / ``name``;
recursively JSON-compatible, deeply frozen, never-aliased arguments; no id
generation; unique ``call_id`` per validated sequence, order preserved; no
failure field (O2); no change to any existing module.
"""

from __future__ import annotations

import ast
import dataclasses
import os
from types import MappingProxyType

import pytest

import core.tool_calling as tc_module
from core.ai_provider import AIRequest, AIResponse
from core.claude_provider import ClaudeProvider
from core.tool_calling import ToolCall, ToolCallResult, validate_tool_calls
from core.tool_interface import ToolRequest, ToolResult

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "tool_calling.py")

ARGS = {"city": "Paris", "days": 3, "ratio": 0.5, "metric": True, "note": None,
        "tags": ["a", "b"], "where": {"lat": 48.8, "lon": [2, 3], "extra": {"x": (1, 2)}}}


def thaw(value: object) -> object:
    if isinstance(value, (dict, MappingProxyType)):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


# ── ToolCall ────────────────────────────────────────────────────────────


class TestToolCall:
    def test_valid_construction(self) -> None:
        c = ToolCall("call-1", "weather", ARGS)
        assert (c.call_id, c.name) == ("call-1", "weather")
        assert thaw(c.arguments) == thaw(ARGS)

    def test_default_empty_arguments(self) -> None:
        c = ToolCall("c", "t")
        assert dict(c.arguments) == {} and isinstance(c.arguments, MappingProxyType)
        assert ToolCall("d", "t").arguments == c.arguments

    def test_fields_exact(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolCall)] == ["call_id", "name", "arguments"]

    def test_frozen_and_slotted(self) -> None:
        c = ToolCall("c", "t")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.name = "other"  # type: ignore[misc]
        assert not hasattr(c, "__dict__")

    def test_deep_immutability(self) -> None:
        c = ToolCall("c", "t", ARGS)
        with pytest.raises(TypeError):
            c.arguments["city"] = "x"  # type: ignore[index]
        with pytest.raises(TypeError):
            c.arguments["where"]["lat"] = 0  # type: ignore[index]
        with pytest.raises(TypeError):
            c.arguments["where"]["extra"]["y"] = 1  # type: ignore[index]
        assert isinstance(c.arguments["tags"], tuple) and isinstance(c.arguments["where"]["lon"], tuple)

    def test_defensive_copy_never_aliases(self) -> None:
        src = {"list": [1, [2, 3]], "map": {"k": "v"}}
        c = ToolCall("c", "t", src)
        src["list"].append(99)
        src["list"][1].append(4)
        src["map"]["k"] = "changed"
        src["new"] = 1
        assert thaw(c.arguments) == {"list": [1, [2, 3]], "map": {"k": "v"}}

    def test_proxy_input_is_copied_too(self) -> None:
        inner = {"a": 1}
        c = ToolCall("c", "t", MappingProxyType({"m": inner}))
        inner["a"] = 2
        assert c.arguments["m"]["a"] == 1

    @pytest.mark.parametrize("value", ["", "   ", None, 3, b"id"])
    def test_invalid_call_id(self, value: object) -> None:
        with pytest.raises(ValueError, match="call_id"):
            ToolCall(value, "t")  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", ["", "\t", None, 3])
    def test_invalid_name(self, value: object) -> None:
        with pytest.raises(ValueError, match="name"):
            ToolCall("c", value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("args", [None, [("a", 1)], "a=1", 3])
    def test_arguments_must_be_a_mapping(self, args: object) -> None:
        with pytest.raises(TypeError):
            ToolCall("c", "t", args)  # type: ignore[arg-type]

    @pytest.mark.parametrize("args, fragment", [
        ({1: "x"}, "arguments: mapping keys must be strings"),
        ({"a": {2: "x"}}, "arguments.a: mapping keys must be strings"),
        ({"a": object()}, "arguments.a: unsupported value type object"),
        ({"a": {1, 2}}, "arguments.a: unsupported value type set"),
        ({"a": b"bytes"}, "arguments.a: unsupported value type bytes"),
        ({"a": [1, {"b": [object()]}]}, "arguments.a[1].b[0]: unsupported value type object"),
        ({"a": ToolCall("x", "y")}, "unsupported value type ToolCall"),
    ])
    def test_rejects_non_json_values_deterministically(self, args: dict, fragment: str) -> None:
        for _ in range(2):
            with pytest.raises(TypeError) as info:
                ToolCall("c", "t", args)
            assert fragment in str(info.value)

    def test_call_id_preserved_verbatim_no_generation(self) -> None:
        for cid in ("toolu_01AbC", "call_9", " spaced id ", "0"):
            assert ToolCall(cid, "t").call_id == cid
        assert ToolCall("same", "t").call_id == ToolCall("same", "t").call_id

    def test_value_equality(self) -> None:
        assert ToolCall("c", "t", {"a": [1]}) == ToolCall("c", "t", {"a": (1,)})
        assert ToolCall("c", "t", {"a": 1}) != ToolCall("c", "t", {"a": 2})
        assert ToolCall("c", "t") != ToolCall("d", "t")


# ── ToolCallResult ──────────────────────────────────────────────────────


class TestToolCallResult:
    def test_valid_construction(self) -> None:
        r = ToolCallResult("call-1", "weather", "sunny")
        assert (r.call_id, r.name, r.output) == ("call-1", "weather", "sunny")
        assert ToolCallResult("c", "t", "").output == ""

    def test_fields_exact_no_failure_field(self) -> None:
        names = [f.name for f in dataclasses.fields(ToolCallResult)]
        assert names == ["call_id", "name", "output"]
        for forbidden in ("error", "is_error", "success", "failure", "status"):
            assert forbidden not in names

    def test_frozen_and_slotted(self) -> None:
        r = ToolCallResult("c", "t", "o")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.output = "x"  # type: ignore[misc]
        assert not hasattr(r, "__dict__")

    @pytest.mark.parametrize("field_name, kwargs", [
        ("call_id", {"call_id": "", "name": "t", "output": "o"}),
        ("call_id", {"call_id": None, "name": "t", "output": "o"}),
        ("name", {"call_id": "c", "name": " ", "output": "o"}),
        ("name", {"call_id": "c", "name": 7, "output": "o"}),
    ])
    def test_invalid_ids_and_names(self, field_name: str, kwargs: dict) -> None:
        with pytest.raises(ValueError, match=field_name):
            ToolCallResult(**kwargs)

    @pytest.mark.parametrize("output", [None, 3, b"bytes", ["o"]])
    def test_invalid_output(self, output: object) -> None:
        with pytest.raises(TypeError, match="output"):
            ToolCallResult("c", "t", output)  # type: ignore[arg-type]

    def test_correlates_with_its_call(self) -> None:
        call = ToolCall("call-7", "weather", {"city": "Rome"})
        result = ToolCallResult(call.call_id, call.name, "sunny")
        assert (result.call_id, result.name) == (call.call_id, call.name)

    def test_value_equality(self) -> None:
        assert ToolCallResult("c", "t", "o") == ToolCallResult("c", "t", "o")
        assert ToolCallResult("c", "t", "o") != ToolCallResult("c", "t", "p")


# ── validate_tool_calls ─────────────────────────────────────────────────


class TestValidateToolCalls:
    def test_order_preserved_and_tuple_returned(self) -> None:
        calls = [ToolCall("b", "t"), ToolCall("a", "t"), ToolCall("c", "u")]
        out = validate_tool_calls(calls)
        assert out == tuple(calls) and isinstance(out, tuple)
        assert all(x is y for x, y in zip(out, calls))

    def test_tuple_input(self) -> None:
        calls = (ToolCall("1", "t"), ToolCall("2", "t"))
        assert validate_tool_calls(calls) == calls

    def test_empty(self) -> None:
        assert validate_tool_calls([]) == () and validate_tool_calls(()) == ()

    def test_duplicate_call_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate call_id: 'x'"):
            validate_tool_calls([ToolCall("x", "a"), ToolCall("y", "b"), ToolCall("x", "c")])

    def test_same_name_different_ids_allowed(self) -> None:
        out = validate_tool_calls([ToolCall("1", "t"), ToolCall("2", "t")])
        assert [c.name for c in out] == ["t", "t"]

    @pytest.mark.parametrize("item", [ToolCallResult("c", "t", "o"), {"call_id": "c"}, None, "c"])
    def test_non_tool_call_rejected(self, item: object) -> None:
        with pytest.raises(TypeError, match=r"calls\[1\] is not a ToolCall"):
            validate_tool_calls([ToolCall("a", "t"), item])  # type: ignore[list-item]

    @pytest.mark.parametrize("calls", ["abc", b"abc", None, 5, {"a": 1}, iter([])])
    def test_non_sequence_rejected(self, calls: object) -> None:
        with pytest.raises(TypeError, match="sequence"):
            validate_tool_calls(calls)  # type: ignore[arg-type]

    def test_no_id_generation(self) -> None:
        calls = [ToolCall("keep-me", "t")]
        assert validate_tool_calls(calls)[0].call_id == "keep-me"


# ── boundary / backward compatibility ───────────────────────────────────


class TestBoundary:
    def test_exact_public_surface(self) -> None:
        assert tc_module.__all__ == ["ToolCall", "ToolCallResult", "validate_tool_calls"]

    def test_stdlib_only(self) -> None:
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert mods == {"__future__", "collections.abc", "dataclasses", "types"}

    def test_no_module_state_or_provider_concepts(self) -> None:
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        assigns = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        assert assigns == ["__all__"]
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})
        lowered = {i.lower() for i in idents}
        for token in ("openai", "anthropic", "gemini", "ollama", "route", "registry", "invoke", "agent",
                      "uuid", "random", "time"):  # (no json module: pinned by test_stdlib_only)
            assert not any(token in i for i in lowered), token

    def test_no_importer_yet(self) -> None:
        for dirpath, _, files in os.walk(CORE_DIR):
            for name in files:
                if name.endswith(".py") and name != "tool_calling.py":
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        assert "tool_calling" not in f.read(), name

    def test_existing_tool_type_pins_intact(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolRequest)] == ["tool_name", "arguments"]
        assert [f.name for f in dataclasses.fields(ToolResult)] == ["tool_name", "output"]

    def test_ai_boundary_unchanged(self) -> None:
        assert [f.name for f in dataclasses.fields(AIRequest)] == ["prompt", "history", "system"]
        assert [f.name for f in dataclasses.fields(AIResponse)] == ["text", "provider_name"]

    def test_v8_36_provider_payload_unchanged(self) -> None:
        calls: list[dict] = []

        class Messages:
            def create(self, **kw):
                calls.append(kw)
                return type("R", (), {"content": [type("B", (), {"text": "ok"})()]})()

        client = type("Cl", (), {"messages": Messages()})()
        ClaudeProvider(client=client).complete(AIRequest(prompt="p"))
        assert set(calls[0]) == {"model", "max_tokens", "messages"}
        assert calls[0]["messages"] == [{"role": "user", "content": "p"}]
