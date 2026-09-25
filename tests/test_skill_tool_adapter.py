"""Tests for v8.13 Skill → Tool Adapter."""

from __future__ import annotations

import ast
import os
import sys
from types import MappingProxyType
from typing import Any

import pytest

import core.skill_registry as skill_registry
import core.skill_tool_adapter as adapter_module
from core.skill_registry import SkillManifest
from core.skill_tool_adapter import SkillTool, adapt_skill_manifest
from core.tool_interface import ToolError, ToolInterface, ToolRequest, ToolResult
from core.tool_registry import ToolAlreadyRegisteredError, ToolRegistry

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "skill_tool_adapter.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


def decl(name: str, description: str = "desc") -> dict[str, Any]:
    return {"name": name, "description": description, "parameters": {"type": "OBJECT"}}


class Recorder:
    """Handler that records every call it receives."""

    def __init__(self, result: object = "ok") -> None:
        self.calls: list[tuple[str, dict, Any]] = []
        self.result = result

    def __call__(self, tool_name: str, args: dict, ctx: Any) -> object:
        self.calls.append((tool_name, args, ctx))
        return self.result


def manifest(*declarations: dict, handler: Any = None, name: str = "skill") -> SkillManifest:
    return SkillManifest(
        name=name,
        description="test skill",
        tools=list(declarations),
        handler=handler if handler is not None else Recorder(),
    )


def _snapshot_globals() -> tuple[dict, dict]:
    return dict(skill_registry._skills), dict(skill_registry._tool_index)  # noqa: SLF001


# ── Adaptation ──────────────────────────────────────────────────────────


class TestAdaptation:
    def test_empty_tools_returns_empty_tuple(self) -> None:
        assert adapt_skill_manifest(manifest()) == ()

    def test_one_declaration_one_tool(self) -> None:
        tools = adapt_skill_manifest(manifest(decl("a")))
        assert len(tools) == 1
        assert isinstance(tools[0], SkillTool)

    def test_multiple_declarations_fan_out(self) -> None:
        tools = adapt_skill_manifest(manifest(decl("a"), decl("b"), decl("c")))
        assert [t.name for t in tools] == ["a", "b", "c"]

    def test_declaration_order_preserved(self) -> None:
        tools = adapt_skill_manifest(manifest(decl("z"), decl("a"), decl("m")))
        assert [t.name for t in tools] == ["z", "a", "m"]

    def test_returns_tuple(self) -> None:
        assert isinstance(adapt_skill_manifest(manifest(decl("a"))), tuple)

    def test_name_mapping(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("weather_report")))
        assert t.name == "weather_report"

    def test_description_mapping(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a", "Gives the weather")))
        assert t.description == "Gives the weather"

    def test_missing_description_defaults_to_empty(self) -> None:
        (t,) = adapt_skill_manifest(manifest({"name": "a"}))
        assert t.description == ""

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError):
            adapt_skill_manifest(manifest({"description": "d"}))

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValueError):
            adapt_skill_manifest(manifest(decl("   ")))

    def test_non_string_name_raises(self) -> None:
        with pytest.raises(ValueError):
            adapt_skill_manifest(manifest(decl(3)))  # type: ignore[arg-type]

    def test_non_string_description_raises(self) -> None:
        with pytest.raises(ValueError):
            adapt_skill_manifest(manifest(decl("a", None)))  # type: ignore[arg-type]

    def test_non_mapping_declaration_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            adapt_skill_manifest(manifest("not-a-dict"))  # type: ignore[arg-type]

    def test_missing_tools_raises_type_error(self) -> None:
        class NoTools:
            handler = Recorder()

        with pytest.raises(TypeError):
            adapt_skill_manifest(NoTools())  # type: ignore[arg-type]

    def test_invalid_tools_type_raises_type_error(self) -> None:
        m = manifest(decl("a"))
        m.tools = "a"  # type: ignore[assignment]
        with pytest.raises(TypeError):
            adapt_skill_manifest(m)

    def test_missing_handler_raises_type_error(self) -> None:
        class NoHandler:
            tools = [decl("a")]

        with pytest.raises(TypeError):
            adapt_skill_manifest(NoHandler())  # type: ignore[arg-type]

    def test_non_callable_handler_raises_type_error(self) -> None:
        m = manifest(decl("a"))
        m.handler = "nope"  # type: ignore[assignment]
        with pytest.raises(TypeError):
            adapt_skill_manifest(m)

    def test_invalid_context_raises(self) -> None:
        with pytest.raises(ValueError):
            adapt_skill_manifest(manifest(decl("a")), context=["x"])  # type: ignore[arg-type]

    def test_unregistered_manifest_adapts(self) -> None:
        m = manifest(decl("never_registered_tool"))
        assert not skill_registry.is_registered("never_registered_tool")
        (t,) = adapt_skill_manifest(m)
        assert t.name == "never_registered_tool"
        assert not skill_registry.is_registered("never_registered_tool")

    def test_duck_typed_manifest_accepted(self) -> None:
        class Duck:
            tools = [decl("a")]
            handler = staticmethod(lambda n, a, c: "quack")

        (t,) = adapt_skill_manifest(Duck())  # type: ignore[arg-type]
        assert t.invoke(ToolRequest("a")).output == "quack"

    def test_intra_manifest_duplicates_pass_through(self) -> None:
        tools = adapt_skill_manifest(manifest(decl("dup"), decl("dup")))
        assert [t.name for t in tools] == ["dup", "dup"]
        assert tools[0] is not tools[1]

    def test_manifest_reference_not_copied(self) -> None:
        m = manifest(decl("a"))
        (t,) = adapt_skill_manifest(m)
        assert t.manifest is m

    def test_real_weather_shaped_manifest(self) -> None:
        rec = Recorder("Weather delivered.")
        m = SkillManifest(
            name="weather",
            description="Shows live weather for a city.",
            version="1.0",
            risk_level="low",
            permissions=["open_browser"],
            dependencies=[],
            tools=[{
                "name": "weather_report",
                "description": "Gives the weather report to user",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"city": {"type": "STRING"}},
                    "required": ["city"],
                },
            }],
            handler=rec,
            examples=["What's the weather in Mumbai?"],
        )
        (t,) = adapt_skill_manifest(m, context={"ui": object()})
        res = t.invoke(ToolRequest("weather_report", {"city": "Mumbai"}))
        assert res == ToolResult("weather_report", "Weather delivered.")
        assert rec.calls[0][1] == {"city": "Mumbai"}


# ── Invocation ──────────────────────────────────────────────────────────


class TestInvocation:
    def test_handler_receives_tool_name(self) -> None:
        rec = Recorder()
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=rec))
        t.invoke(ToolRequest("a"))
        assert rec.calls[0][0] == "a"

    def test_each_tool_passes_its_own_name(self) -> None:
        rec = Recorder()
        a, b = adapt_skill_manifest(manifest(decl("a"), decl("b"), handler=rec))
        a.invoke(ToolRequest("a"))
        b.invoke(ToolRequest("b"))
        assert [c[0] for c in rec.calls] == ["a", "b"]

    def test_handler_receives_fresh_plain_dict(self) -> None:
        rec = Recorder()
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=rec))
        req = ToolRequest("a", {"x": 1})
        t.invoke(req)
        args = rec.calls[0][1]
        assert type(args) is dict
        assert args == {"x": 1}
        assert args is not req.arguments

    def test_handler_receives_captured_context(self) -> None:
        rec = Recorder()
        ctx = {"ui": object()}
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=rec), context=ctx)
        t.invoke(ToolRequest("a"))
        assert rec.calls[0][2] is t.context
        assert rec.calls[0][2]["ui"] is ctx["ui"]

    def test_request_unchanged_after_handler_mutation(self) -> None:
        def mutating(name: str, args: dict, ctx: Any) -> str:
            args["injected"] = True
            args.pop("x", None)
            return "ok"

        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=mutating))
        req = ToolRequest("a", {"x": 1})
        t.invoke(req)
        assert dict(req.arguments) == {"x": 1}

    def test_handler_mutations_do_not_leak_between_invocations(self) -> None:
        seen: list[dict] = []

        def mutating(name: str, args: dict, ctx: Any) -> str:
            seen.append(dict(args))
            args["count"] = args.get("count", 0) + 1
            return "ok"

        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=mutating))
        req = ToolRequest("a", {"x": 1})
        t.invoke(req)
        t.invoke(req)
        assert seen == [{"x": 1}, {"x": 1}]

    def test_separate_invocations_get_separate_dicts(self) -> None:
        rec = Recorder()
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=rec))
        req = ToolRequest("a", {"x": 1})
        t.invoke(req)
        t.invoke(req)
        assert rec.calls[0][1] is not rec.calls[1][1]

    def test_string_result_unchanged(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder("hello")))
        assert t.invoke(ToolRequest("a")).output == "hello"

    def test_empty_string_result_unchanged(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder("")))
        assert t.invoke(ToolRequest("a")).output == ""

    def test_none_result_becomes_empty_string(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder(None)))
        assert t.invoke(ToolRequest("a")).output == ""

    def test_no_done_fallback(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder(None)))
        assert t.invoke(ToolRequest("a")).output != "Done."

    def test_arbitrary_result_becomes_str(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder(42)))
        assert t.invoke(ToolRequest("a")).output == "42"
        (t2,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder({"k": 1})))
        assert t2.invoke(ToolRequest("a")).output == "{'k': 1}"

    def test_result_is_tool_result_with_correct_fields(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder("o")))
        res = t.invoke(ToolRequest("a"))
        assert isinstance(res, ToolResult)
        assert res.tool_name == "a"
        assert res.output == "o"

    def test_handler_exception_propagates_unchanged(self) -> None:
        class Custom(RuntimeError):
            pass

        def failing(name: str, args: dict, ctx: Any) -> str:
            raise Custom("boom")

        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=failing))
        with pytest.raises(Custom, match="boom") as info:
            t.invoke(ToolRequest("a"))
        assert type(info.value) is Custom
        assert not isinstance(info.value, ToolError)

    def test_tool_error_not_introduced(self) -> None:
        def failing(name: str, args: dict, ctx: Any) -> str:
            raise KeyError("k")

        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=failing))
        with pytest.raises(KeyError):
            t.invoke(ToolRequest("a"))
        with open(MODULE_PATH, encoding="utf-8") as f:
            src = f.read()
        assert "raise ToolError" not in src
        assert "except" not in src

    def test_name_mismatch_raises_value_error(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")))
        with pytest.raises(ValueError):
            t.invoke(ToolRequest("b"))

    def test_mismatch_does_not_invoke_handler(self) -> None:
        rec = Recorder()
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=rec))
        with pytest.raises(ValueError):
            t.invoke(ToolRequest("b"))
        assert rec.calls == []


# ── Context ─────────────────────────────────────────────────────────────


class TestContext:
    def test_default_context_empty(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")))
        assert dict(t.context) == {}
        assert isinstance(t.context, MappingProxyType)

    def test_context_structure_copied(self) -> None:
        ctx = {"k": "v"}
        (t,) = adapt_skill_manifest(manifest(decl("a")), context=ctx)
        assert dict(t.context) == {"k": "v"}
        assert t.context is not ctx

    def test_context_read_only(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")), context={"k": 1})
        with pytest.raises(TypeError):
            t.context["k"] = 2  # type: ignore[index]

    def test_caller_mutation_does_not_affect_captured(self) -> None:
        ctx = {"k": 1}
        (t,) = adapt_skill_manifest(manifest(decl("a")), context=ctx)
        ctx["k"] = 2
        ctx["new"] = 3
        assert dict(t.context) == {"k": 1}

    def test_context_values_keep_identity(self) -> None:
        ui = object()
        (t,) = adapt_skill_manifest(manifest(decl("a")), context={"ui": ui})
        assert t.context["ui"] is ui

    def test_context_shared_across_tools_and_invocations(self) -> None:
        rec = Recorder()
        a, b = adapt_skill_manifest(manifest(decl("a"), decl("b"), handler=rec), context={"k": 1})
        a.invoke(ToolRequest("a"))
        a.invoke(ToolRequest("a"))
        b.invoke(ToolRequest("b"))
        assert all(c[2] is a.context for c in rec.calls)
        assert a.context is b.context

    def test_accepts_read_only_mapping_as_context(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")), context=MappingProxyType({"k": 1}))
        assert dict(t.context) == {"k": 1}

    def test_no_adapter_owned_mutable_state(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")))
        assert SkillTool.__slots__ == ("_manifest", "_name", "_description", "_context")
        assert not hasattr(t, "__dict__")
        assert not hasattr(t, "_lock")
        assert not hasattr(t, "call_count")

    def test_invoke_does_not_change_tool_state(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("a")), context={"k": 1})
        before = (t.name, t.description, t.context, t.manifest)
        t.invoke(ToolRequest("a"))
        assert (t.name, t.description, t.context, t.manifest) == before
        assert t.context is before[2]


# ── Late binding / mutation ─────────────────────────────────────────────


class TestLateBinding:
    def test_swapping_handler_affects_invocation(self) -> None:
        m = manifest(decl("a"), handler=Recorder("first"))
        (t,) = adapt_skill_manifest(m)
        assert t.invoke(ToolRequest("a")).output == "first"
        m.handler = Recorder("second")
        assert t.invoke(ToolRequest("a")).output == "second"

    def test_changing_declaration_name_does_not_rekey(self) -> None:
        m = manifest(decl("a"))
        (t,) = adapt_skill_manifest(m)
        m.tools[0]["name"] = "renamed"
        assert t.name == "a"
        assert t.invoke(ToolRequest("a")).tool_name == "a"
        with pytest.raises(ValueError):
            t.invoke(ToolRequest("renamed"))

    def test_changing_declaration_description_does_not_change_tool(self) -> None:
        m = manifest(decl("a", "old"))
        (t,) = adapt_skill_manifest(m)
        m.tools[0]["description"] = "new"
        assert t.description == "old"

    def test_appending_declaration_does_not_grow_existing_result(self) -> None:
        m = manifest(decl("a"))
        tools = adapt_skill_manifest(m)
        m.tools.append(decl("b"))
        assert len(tools) == 1
        assert len(adapt_skill_manifest(m)) == 2


# ── Registry integration ────────────────────────────────────────────────


class TestRegistryIntegration:
    def test_adapted_tools_register(self) -> None:
        r = ToolRegistry()
        tools = adapt_skill_manifest(manifest(decl("a"), decl("b")))
        for t in tools:
            r.register(t)
        assert r.names() == ("a", "b")

    def test_identity_preserved_through_registry(self) -> None:
        r = ToolRegistry()
        (t,) = adapt_skill_manifest(manifest(decl("a")))
        assert r.register(t) is t
        assert r.get("a") is t
        assert r.list_tools()[0] is t

    def test_registered_tool_invokable_through_registry(self) -> None:
        r = ToolRegistry()
        (t,) = adapt_skill_manifest(manifest(decl("a"), handler=Recorder("out")))
        r.register(t)
        assert r.get("a").invoke(ToolRequest("a")).output == "out"

    def test_cross_manifest_collision_raised_by_registry(self) -> None:
        r = ToolRegistry()
        (t1,) = adapt_skill_manifest(manifest(decl("same"), name="s1"))
        (t2,) = adapt_skill_manifest(manifest(decl("same"), name="s2"))
        r.register(t1)
        with pytest.raises(ToolAlreadyRegisteredError):
            r.register(t2)
        assert r.get("same") is t1

    def test_intra_manifest_collision_raised_by_registry(self) -> None:
        r = ToolRegistry()
        a, b = adapt_skill_manifest(manifest(decl("dup"), decl("dup")))
        r.register(a)
        with pytest.raises(ToolAlreadyRegisteredError):
            r.register(b)

    def test_adapter_does_not_register(self) -> None:
        r = ToolRegistry()
        adapt_skill_manifest(manifest(decl("a")))
        assert r.count() == 0
        assert not hasattr(adapter_module, "ToolRegistry")

    def test_structural_tool_interface_conformance(self) -> None:
        tool: ToolInterface = adapt_skill_manifest(manifest(decl("a")))[0]
        assert isinstance(tool.name, str)
        assert isinstance(tool.description, str)
        assert callable(tool.invoke)
        assert ToolInterface not in SkillTool.__mro__


# ── Legacy isolation ────────────────────────────────────────────────────


class TestLegacyIsolation:
    def test_globals_unchanged_by_adaptation(self) -> None:
        before = _snapshot_globals()
        adapt_skill_manifest(manifest(decl("iso_a"), decl("iso_b")))
        assert _snapshot_globals() == before

    def test_globals_unchanged_by_invoke(self) -> None:
        (t,) = adapt_skill_manifest(manifest(decl("iso_c")))
        before = _snapshot_globals()
        t.invoke(ToolRequest("iso_c"))
        assert _snapshot_globals() == before

    def test_no_dispatch_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("dispatch"))
        (t,) = adapt_skill_manifest(manifest(decl("a")))
        t.invoke(ToolRequest("a"))
        assert called == []

    def test_no_register_skill_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "register_skill", lambda m: called.append("register"))
        adapt_skill_manifest(manifest(decl("a")))
        assert called == []

    def test_no_discover_skills_on_import(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "discover_skills", lambda *a, **k: called.append("discover"))
        import importlib
        sys.modules.pop("core.skill_tool_adapter", None)
        try:
            importlib.import_module("core.skill_tool_adapter")
        finally:
            sys.modules["core.skill_tool_adapter"] = adapter_module
        assert called == []

    def test_source_never_touches_registry_internals(self) -> None:
        # AST-level: no identifier/attribute in the adapter refers to the
        # legacy registry's functions or module-level state.
        forbidden = {
            "_skills", "_tool_index", "dispatch", "register_skill",
            "discover_skills", "get_tool_declarations", "list_skills",
            "is_registered",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden, node.id
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden, node.attr

    def test_legacy_sources_untouched_by_adapter(self) -> None:
        for rel in (
            os.path.join("core", "skill_registry.py"),
            os.path.join("core", "skill_dispatch.py"),
            os.path.join("core", "tool_interface.py"),
            os.path.join("core", "tool_registry.py"),
            os.path.join("core", "agent", "__init__.py"),
            "main.py",
        ):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                assert "skill_tool_adapter" not in f.read(), rel

    def test_legacy_dispatch_still_works_alongside(self) -> None:
        # Real registry path is unaffected: an unregistered name still
        # returns None from legacy dispatch even though it is adaptable.
        (t,) = adapt_skill_manifest(manifest(decl("adapter_only_tool")))
        assert skill_registry.dispatch("adapter_only_tool", {}, {}) is None
        assert t.invoke(ToolRequest("adapter_only_tool")).output == "ok"


# ── Architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_import_allowlist(self) -> None:
        allowed_roots = {"__future__", "types", "typing", "dataclasses"}
        allowed_full = {"core.tool_interface", "core.skill_registry"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    node.module.split(".")[0] in allowed_roots
                    or node.module in allowed_full
                ), node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_only_skill_manifest_from_skill_registry(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "core.skill_registry":
                assert [n.name for n in node.names] == ["SkillManifest"]

    def test_only_request_and_result_from_tool_interface(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "core.tool_interface":
                assert sorted(n.name for n in node.names) == ["ToolRequest", "ToolResult"]

    def test_forbidden_core_imports(self) -> None:
        forbidden = {
            "core.tool_registry", "core.skill_dispatch", "core.agent",
            "core.ai_service", "core.ai_provider", "core.memory_engine",
            "core.reflection_engine", "core.planner", "core.planning_engine",
            "core.execution_pipeline", "core.execution_orchestrator",
            "core.execution_session", "core.execution_coordinator",
            "core.execution_result", "core.execution_progress",
            "core.execution_event", "core.execution_planner",
            "core.pipeline_engine", "core.pipeline_run", "core.goal_manager",
            "core.task_graph", "core.problem_solver", "main", "skills",
            "os", "sys", "io", "socket", "asyncio", "subprocess", "logging",
            "pathlib", "importlib", "threading", "json", "pickle", "http", "urllib",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, node.module
                assert node.module.split(".")[0] not in forbidden, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] not in forbidden, n.name

    def test_no_async_constructs(self) -> None:
        for node in ast.walk(_tree()):
            assert not isinstance(
                node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
            )

    def test_no_io_calls(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "exec", "eval", "input"}

    def test_no_module_level_mutable_state(self) -> None:
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else [node.target.id] if isinstance(node.target, ast.Name) else []
                )
                assert targets == ["__all__"], targets
        for name, value in vars(adapter_module).items():
            if not name.startswith("__"):
                assert not isinstance(value, (dict, list, set)), name

    def test_public_api_exact(self) -> None:
        assert adapter_module.__all__ == ["SkillTool", "adapt_skill_manifest"]

    def test_no_registration_or_router_api(self) -> None:
        for attr in (
            "register", "register_tool", "register_all", "dispatch", "route",
            "discover", "adapt_and_register", "default_registry", "ToolRegistry",
        ):
            assert not hasattr(adapter_module, attr), attr
        for attr in ("register", "dispatch", "route", "_lock", "call_count", "cache"):
            assert not hasattr(SkillTool, attr), attr

    def test_no_core_module_imports_adapter(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "skill_tool_adapter.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "skill_tool_adapter" not in f.read(), name

    def test_statelessness_two_adaptations_independent(self) -> None:
        m = manifest(decl("a"))
        (t1,) = adapt_skill_manifest(m, context={"k": 1})
        (t2,) = adapt_skill_manifest(m, context={"k": 2})
        assert t1 is not t2
        assert t1.context["k"] == 1
        assert t2.context["k"] == 2
        assert t1.manifest is t2.manifest
