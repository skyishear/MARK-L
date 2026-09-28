"""Tests for v8.31 ``core.tool_catalog`` (metadata + schema validation only).

Contract: immutable ``ToolSpec(name, description, parameters, idempotent=False,
side_effects=True, model_invocable=False)`` whose ``parameters`` is a
validated, deep read-only JSON-Schema-subset declaration; ``ToolCatalog``
with ``register`` / ``get`` / ``list`` following the ``ToolRegistry``
conventions (insertion order, same-object re-registration is a no-op, a
different spec under the same name raises, unknown ``get`` -> ``None``);
metadata only — separate from the execution registry, never executes,
routes, retries or resumes anything.
"""

from __future__ import annotations

import ast
import dataclasses
import os
import threading
from types import MappingProxyType

import pytest

import core.agent as agent_module
import core.tool_catalog as catalog_module
from core.agent import Agent
from core.tool_catalog import (
    InvalidToolSchemaError,
    ToolCatalog,
    ToolSpec,
    ToolSpecAlreadyRegisteredError,
    validate_parameters_schema,
)
from core.tool_interface import StaticMockTool, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "tool_catalog.py")

EMPTY = {"type": "object"}
WEATHER = {
    "type": "object",
    "description": "Weather lookup",
    "properties": {
        "city": {"type": "string", "description": "City name"},
        "units": {"type": "string", "enum": ["metric", "imperial"]},
        "days": {"type": "integer", "enum": [1, 3, 7]},
        "detailed": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "where": {
            "type": "object",
            "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
            "required": ["lat", "lon"],
            "additionalProperties": False,
        },
    },
    "required": ["city"],
    "additionalProperties": False,
}


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


def thaw(value: object) -> object:
    """JSON view of a stored schema: read-only mappings -> dict, tuples -> list."""
    if isinstance(value, (dict, MappingProxyType)):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


def spec(name: str = "weather", **kw: object) -> ToolSpec:
    return ToolSpec(name=name, description=kw.pop("description", "d"),  # type: ignore[arg-type]
                    parameters=kw.pop("parameters", EMPTY), **kw)  # type: ignore[arg-type]


# ── ToolSpec ────────────────────────────────────────────────────────────


class TestToolSpec:
    def test_construction(self) -> None:
        s = ToolSpec("weather", "Look up weather", WEATHER)
        assert (s.name, s.description) == ("weather", "Look up weather")
        # Stored as a deep read-only copy; JSON-equivalent to the declaration
        # (arrays are frozen as tuples, the repository's immutable-sequence form).
        assert thaw(s.parameters) == WEATHER

    def test_fields_exact(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolSpec)] == [
            "name", "description", "parameters", "idempotent", "side_effects", "model_invocable"]

    def test_most_restrictive_defaults(self) -> None:
        s = spec()
        assert s.idempotent is False and s.side_effects is True and s.model_invocable is False

    def test_explicit_metadata(self) -> None:
        s = spec(idempotent=True, side_effects=False, model_invocable=True)
        assert (s.idempotent, s.side_effects, s.model_invocable) == (True, False, True)

    def test_frozen_and_slotted(self) -> None:
        s = spec()
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.model_invocable = True  # type: ignore[misc]
        assert not hasattr(s, "__dict__")

    def test_parameters_deep_read_only(self) -> None:
        s = spec(parameters=WEATHER)
        assert isinstance(s.parameters, MappingProxyType)
        with pytest.raises(TypeError):
            s.parameters["type"] = "array"  # type: ignore[index]
        props = s.parameters["properties"]
        assert isinstance(props, MappingProxyType)
        with pytest.raises(TypeError):
            props["city"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            props["where"]["properties"]["lat"]["type"] = "string"  # type: ignore[index]
        assert isinstance(s.parameters["required"], tuple)

    def test_parameters_defensively_copied(self) -> None:
        source = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        s = spec(parameters=source)
        source["properties"]["a"]["type"] = "integer"
        source["required"].append("zzz")
        source["properties"]["b"] = {"type": "string"}
        assert s.parameters["properties"]["a"]["type"] == "string"
        assert tuple(s.parameters["required"]) == ("a",)
        assert "b" not in s.parameters["properties"]

    def test_parameters_content_and_order_preserved(self) -> None:
        s = spec(parameters=WEATHER)
        assert list(s.parameters) == list(WEATHER)
        assert list(s.parameters["properties"]) == list(WEATHER["properties"])
        assert list(s.parameters["properties"]["units"]["enum"]) == ["metric", "imperial"]
        assert thaw(s.parameters) == WEATHER  # nothing added, dropped, reordered or repaired

    @pytest.mark.parametrize("kw, exc", [
        ({"name": ""}, ValueError), ({"name": "  "}, ValueError), ({"name": 3}, ValueError),
        ({"description": None}, TypeError),
        ({"idempotent": 1}, TypeError), ({"side_effects": "yes"}, TypeError),
        ({"model_invocable": None}, TypeError),
    ])
    def test_invalid_fields(self, kw: dict, exc: type) -> None:
        with pytest.raises(exc):
            spec(**kw)

    def test_invalid_schema_rejected_at_construction(self) -> None:
        with pytest.raises(InvalidToolSchemaError):
            spec(parameters={"type": "string"})


# ── schema validation ───────────────────────────────────────────────────


class TestSchemaValidation:
    @pytest.mark.parametrize("schema", [
        EMPTY,
        WEATHER,
        {"type": "object", "properties": {}},
        {"type": "object", "properties": {"xs": {"type": "array"}}},
        {"type": "object", "properties": {"m": {"type": "array", "items": {
            "type": "array", "items": {"type": "object", "properties": {"k": {"type": "integer"}}}}}}},
        {"type": "object", "properties": {"n": {"type": "number", "enum": [1, 2.5]}}},
        {"type": "object", "properties": {"b": {"type": "boolean", "enum": [True]}}},
        MappingProxyType({"type": "object", "required": (), "properties": MappingProxyType({})}),
    ])
    def test_valid(self, schema: object) -> None:
        assert validate_parameters_schema(schema) is None

    @pytest.mark.parametrize("schema, fragment", [
        (None, "$: schema must be a mapping"),
        ([], "$: schema must be a mapping"),
        ({}, "'type' must be one of"),
        ({"type": "string"}, "root schema must have type 'object'"),
        ({"type": "array"}, "root schema must have type 'object'"),
        ({"type": "null"}, "'type' must be one of"),
        ({"type": ["object", "null"]}, "'type' must be one of"),
        ({"type": "object", "$schema": "x"}, "unsupported keyword"),
        ({"type": "object", "items": {"type": "string"}}, "unsupported keyword"),
        ({"type": "object", "enum": [{}]}, "unsupported keyword"),
        ({"type": "object", 1: "x"}, "keys must be strings"),
        ({"type": "object", "description": 3}, "'description' must be a string"),
        ({"type": "object", "properties": []}, "'properties' must be a mapping"),
        ({"type": "object", "properties": {"": {"type": "string"}}}, "property names"),
        ({"type": "object", "properties": {"a": "string"}}, "$.properties.a: schema must be a mapping"),
        ({"type": "object", "properties": {"a": {"type": "string", "minLength": 1}}},
         "$.properties.a: unsupported keyword"),
        ({"type": "object", "properties": {"a": {"type": "string", "properties": {}}}}, "unsupported keyword"),
        ({"type": "object", "required": "a", "properties": {"a": {"type": "string"}}}, "'required' must be a list"),
        ({"type": "object", "required": [1], "properties": {}}, "'required' entries must be strings"),
        ({"type": "object", "required": ["a", "a"], "properties": {"a": {"type": "string"}}}, "unique"),
        ({"type": "object", "required": ["missing"]}, "not in 'properties'"),
        ({"type": "object", "additionalProperties": {"type": "string"}}, "'additionalProperties' must be a boolean"),
        ({"type": "object", "properties": {"xs": {"type": "array", "items": "string"}}},
         "$.properties.xs.items: schema must be a mapping"),
        ({"type": "object", "properties": {"s": {"type": "string", "enum": []}}}, "non-empty list"),
        ({"type": "object", "properties": {"s": {"type": "string", "enum": "abc"}}}, "non-empty list"),
        ({"type": "object", "properties": {"s": {"type": "string", "enum": ["a", 1]}}}, "of type 'string'"),
        ({"type": "object", "properties": {"i": {"type": "integer", "enum": [1.5]}}}, "of type 'integer'"),
        ({"type": "object", "properties": {"i": {"type": "integer", "enum": [True]}}}, "of type 'integer'"),
        ({"type": "object", "properties": {"n": {"type": "number", "enum": [False]}}}, "of type 'number'"),
        ({"type": "object", "properties": {"b": {"type": "boolean", "enum": [1]}}}, "of type 'boolean'"),
        ({"type": "object", "properties": {"s": {"type": "string", "enum": ["a", "a"]}}}, "unique"),
        ({"type": "object", "properties": {"w": {"type": "object", "required": ["x"]}}},
         "$.properties.w: 'required' names not in 'properties'"),
    ])
    def test_invalid(self, schema: object, fragment: str) -> None:
        with pytest.raises(InvalidToolSchemaError) as info:
            validate_parameters_schema(schema)
        assert fragment in str(info.value)

    def test_error_is_value_error(self) -> None:
        assert issubclass(InvalidToolSchemaError, ValueError)

    def test_pure_does_not_modify_input(self) -> None:
        import copy

        schema = copy.deepcopy(WEATHER)
        validate_parameters_schema(schema)
        assert schema == WEATHER
        with pytest.raises(InvalidToolSchemaError):
            bad = {"type": "object", "properties": {"a": {"type": "string", "x": 1}}}
            validate_parameters_schema(bad)
        assert bad == {"type": "object", "properties": {"a": {"type": "string", "x": 1}}}

    def test_deterministic(self) -> None:
        bad = {"type": "object", "properties": {"a": {"type": "string", "zeta": 1, "alpha": 2}}}
        messages = set()
        for _ in range(3):
            with pytest.raises(InvalidToolSchemaError) as info:
                validate_parameters_schema(bad)
            messages.add(str(info.value))
        assert len(messages) == 1 and "['alpha', 'zeta']" in messages.pop()


# ── ToolCatalog ─────────────────────────────────────────────────────────


class TestToolCatalog:
    def test_register_get_list(self) -> None:
        c = ToolCatalog()
        s = spec()
        assert c.register(s) is s
        assert c.get("weather") is s
        assert c.list() == (s,)

    def test_insertion_order_multiple_specs(self) -> None:
        c = ToolCatalog()
        specs = [spec(n) for n in ("zeta", "alpha", "mid")]
        for s in specs:
            c.register(s)
        assert c.list() == tuple(specs)
        assert [s.name for s in c.list()] == ["zeta", "alpha", "mid"]

    def test_same_object_reregistration_is_noop(self) -> None:
        c = ToolCatalog()
        a, b = spec("a"), spec("b")
        c.register(a)
        c.register(b)
        assert c.register(a) is a
        assert c.list() == (a, b)

    def test_different_spec_same_name_raises(self) -> None:
        c = ToolCatalog()
        first = spec()
        c.register(first)
        with pytest.raises(ToolSpecAlreadyRegisteredError):
            c.register(spec(description="other"))
        with pytest.raises(ToolSpecAlreadyRegisteredError):
            c.register(spec())  # equal value, different object: registry convention
        assert c.get("weather") is first and len(c.list()) == 1
        assert issubclass(ToolSpecAlreadyRegisteredError, ValueError)

    def test_unknown_lookup_returns_none(self) -> None:
        assert ToolCatalog().get("missing") is None

    def test_register_requires_tool_spec(self) -> None:
        with pytest.raises(TypeError):
            ToolCatalog().register({"name": "x"})  # type: ignore[arg-type]

    def test_list_is_a_snapshot(self) -> None:
        c = ToolCatalog()
        snap = c.list()
        c.register(spec())
        assert snap == () and isinstance(c.list(), tuple)

    def test_instances_are_independent(self) -> None:
        a, b = ToolCatalog(), ToolCatalog()
        a.register(spec())
        assert b.get("weather") is None and b.list() == ()

    def test_thread_safe_registration(self) -> None:
        c = ToolCatalog()
        specs = [spec(f"t{i}") for i in range(50)]
        threads = [threading.Thread(target=c.register, args=(s,)) for s in specs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert {s.name for s in c.list()} == {s.name for s in specs}

    def test_minimal_public_surface(self) -> None:
        public = {n for n in vars(ToolCatalog) if not n.startswith("_")}
        assert public == {"register", "get", "list"}


# ── separation from execution ───────────────────────────────────────────


class Spy:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "d"
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        return ToolResult(request.tool_name, "ok")


class TestSeparationFromExecution:
    def test_no_spec_does_not_affect_registry_or_routing(self) -> None:
        registry = ToolRegistry()
        tool = registry.register(Spy("weather"))
        catalog = ToolCatalog()
        assert catalog.get("weather") is None  # no spec -> no metadata
        assert registry.get("weather") is tool
        assert ToolRouter(registry).route(ToolRequest("weather", {})).output == "ok"

    def test_spec_does_not_register_or_execute(self) -> None:
        registry = ToolRegistry()
        tool = Spy("weather")
        catalog = ToolCatalog()
        catalog.register(spec("weather", model_invocable=True, idempotent=True))
        assert registry.get("weather") is None and tool.calls == 0

    def test_catalog_and_registry_share_nothing(self) -> None:
        registry = ToolRegistry()
        registry.register(StaticMockTool(name="a"))
        catalog = ToolCatalog()
        catalog.register(spec("b"))
        assert registry.names() == ("a",) and [s.name for s in catalog.list()] == ["b"]

    def test_agent_execution_untouched(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        _, run, _, results = a.execute_projection_with_run_status("fix the wifi")
        assert len(results) == 1
        # v8.32: the Agent owns an (empty by default) catalog; execution ignores it.
        assert a.tool_catalog.list() == ()


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_stdlib_only_imports(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom):
                assert node.module in {"__future__", "dataclasses", "types", "typing"}, node.module
            elif isinstance(node, ast.Import):
                assert [a.name for a in node.names] == ["threading"], node.names[0].name
        assert catalog_module.__all__ == ["InvalidToolSchemaError", "ToolCatalog", "ToolSpec",
                                          "ToolSpecAlreadyRegisteredError", "validate_parameters_schema"]

    def test_no_execution_or_policy_surface(self) -> None:
        tree = _tree()
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})
        for token in ("invoke", "route", "ToolRouter", "ToolRegistry", "ToolRequest", "retry", "resume",
                      "sleep", "Agent", "AIService", "open", "print"):
            assert token not in idents, token

    def test_no_mutable_module_state(self) -> None:
        for name, value in vars(catalog_module).items():
            if not name.startswith("__"):
                assert not isinstance(value, (list, set)), name
                if isinstance(value, dict):
                    assert name == "_KEYS_BY_TYPE", name  # constant lookup table, never mutated
        tree = _tree()
        mutating = {c.func.attr for c in ast.walk(tree) if isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name) and c.func.value.id.startswith("_")}
        assert not mutating & {"append", "update", "pop", "clear", "setdefault"}

    def test_only_the_agent_imports_it(self) -> None:
        # v8.32: the Agent (composition root) is the one sanctioned consumer.
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "tool_catalog.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "tool_catalog" not in f.read(), name
        with open(os.path.join(CORE_DIR, "agent", "__init__.py"), encoding="utf-8") as f:
            assert "from core.tool_catalog import ToolCatalog" in f.read()

    def test_tool_stack_contracts_unchanged(self) -> None:
        assert [f.name for f in dataclasses.fields(ToolRequest)] == ["tool_name", "arguments"]
        assert [f.name for f in dataclasses.fields(ToolResult)] == ["tool_name", "output"]
        assert not hasattr(StaticMockTool, "schema")
        assert len(agent_module.__all__) == 16
