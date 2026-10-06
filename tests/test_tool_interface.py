"""Tests for v8.11 Tool Interface (contract + minimal mock)."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import os
import typing
from types import MappingProxyType

import pytest

import core.tool_interface as tool_module
from core.tool_interface import (
    StaticMockTool,
    ToolError,
    ToolInterface,
    ToolRequest,
    ToolResult,
)

HERE = os.path.dirname(__file__)
CORE_DIR = os.path.normpath(os.path.join(HERE, "..", "core"))
MODULE_PATH = os.path.join(CORE_DIR, "tool_interface.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


class TestToolRequest:
    def test_construction(self) -> None:
        r = ToolRequest(tool_name="t", arguments={"a": 1})
        assert r.tool_name == "t"
        assert dict(r.arguments) == {"a": 1}

    def test_default_arguments_empty(self) -> None:
        r = ToolRequest(tool_name="t")
        assert dict(r.arguments) == {}
        assert isinstance(r.arguments, MappingProxyType)

    def test_arguments_are_read_only(self) -> None:
        r = ToolRequest(tool_name="t", arguments={"a": 1})
        assert isinstance(r.arguments, MappingProxyType)
        with pytest.raises(TypeError):
            r.arguments["a"] = 2  # type: ignore[index]
        with pytest.raises(TypeError):
            del r.arguments["a"]  # type: ignore[attr-defined]

    def test_arguments_defensively_copied(self) -> None:
        src = {"a": 1}
        r = ToolRequest(tool_name="t", arguments=src)
        src["a"] = 99
        src["b"] = 2
        assert dict(r.arguments) == {"a": 1}

    def test_accepts_any_mapping(self) -> None:
        r = ToolRequest(tool_name="t", arguments=MappingProxyType({"k": "v"}))
        assert dict(r.arguments) == {"k": "v"}

    def test_non_mapping_arguments_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolRequest(tool_name="t", arguments=["a"])  # type: ignore[arg-type]

    def test_blank_tool_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolRequest(tool_name="")
        with pytest.raises(ValueError):
            ToolRequest(tool_name="   ")

    def test_non_string_tool_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolRequest(tool_name=3)  # type: ignore[arg-type]

    def test_frozen(self) -> None:
        r = ToolRequest(tool_name="t")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.tool_name = "x"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.arguments = {}  # type: ignore[misc]

    def test_slots(self) -> None:
        r = ToolRequest(tool_name="t")
        assert not hasattr(r, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            r.extra = 1  # type: ignore[attr-defined]

    def test_field_names_exact(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(ToolRequest)) == (
            "tool_name", "arguments",
        )

    def test_equality_by_value(self) -> None:
        assert ToolRequest("t", {"a": 1}) == ToolRequest("t", {"a": 1})
        assert ToolRequest("t", {"a": 1}) != ToolRequest("t", {"a": 2})


class TestToolResult:
    def test_construction(self) -> None:
        res = ToolResult(tool_name="t", output="o")
        assert res.tool_name == "t"
        assert res.output == "o"

    def test_frozen(self) -> None:
        res = ToolResult(tool_name="t", output="o")
        with pytest.raises(dataclasses.FrozenInstanceError):
            res.output = "x"  # type: ignore[misc]

    def test_slots(self) -> None:
        res = ToolResult(tool_name="t", output="o")
        assert not hasattr(res, "__dict__")

    def test_field_names_exact(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(ToolResult)) == (
            "tool_name", "output",
        )

    def test_equality_by_value(self) -> None:
        assert ToolResult("t", "o") == ToolResult("t", "o")


class TestToolError:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(ToolError, Exception)
        assert ToolError.__bases__ == (Exception,)

    def test_no_hierarchy(self) -> None:
        # v8.33: the one sanctioned subclass is the explicit transient signal.
        from core.tool_interface import TransientToolError

        assert ToolError.__subclasses__() == [TransientToolError]

    def test_raise_and_catch(self) -> None:
        with pytest.raises(ToolError, match="boom"):
            raise ToolError("boom")


class TestToolInterfaceProtocol:
    def test_is_protocol(self) -> None:
        assert typing.get_origin(ToolInterface) is None
        assert getattr(ToolInterface, "_is_protocol", False) is True
        assert typing.Protocol in ToolInterface.__mro__

    def test_not_an_abc_with_registered_impls(self) -> None:
        import abc
        assert not any(
            isinstance(b, type) and b.__name__ == "ABC" for b in ToolInterface.__mro__
        )
        assert abc.ABC not in ToolInterface.__bases__

    def test_declares_required_members(self) -> None:
        annotations = typing.get_type_hints(ToolInterface)
        assert annotations["name"] is str
        assert annotations["description"] is str
        assert callable(getattr(ToolInterface, "invoke", None))

    def test_invoke_is_synchronous(self) -> None:
        assert not inspect.iscoroutinefunction(ToolInterface.invoke)
        assert not inspect.iscoroutinefunction(StaticMockTool.invoke)

    def test_structural_conformance_of_mock(self) -> None:
        tool: ToolInterface = StaticMockTool()
        assert isinstance(tool.name, str)
        assert isinstance(tool.description, str)
        assert callable(getattr(tool, "invoke", None))

    def test_structural_conformance_of_unrelated_class(self) -> None:
        # Any class with the right shape satisfies the contract — no
        # inheritance required.
        class Custom:
            name = "custom"
            description = "custom tool"

            def invoke(self, request: ToolRequest) -> ToolResult:
                return ToolResult(tool_name=request.tool_name, output="ok")

        tool: ToolInterface = Custom()
        assert tool.invoke(ToolRequest("x")).output == "ok"
        assert ToolInterface not in type(tool).__mro__


class TestStaticMockTool:
    def test_defaults(self) -> None:
        t = StaticMockTool()
        assert t.name == "mock"
        assert t.description == "Deterministic mock tool."
        assert t.call_count == 0
        assert t.invoke(ToolRequest("t")).output == "mock-output"

    def test_configured_output(self) -> None:
        t = StaticMockTool("hello")
        assert t.invoke(ToolRequest("t")).output == "hello"

    def test_custom_name_and_description(self) -> None:
        t = StaticMockTool(name="n", description="d")
        assert t.name == "n"
        assert t.description == "d"

    def test_result_carries_request_tool_name(self) -> None:
        t = StaticMockTool()
        assert t.invoke(ToolRequest("weather")).tool_name == "weather"

    def test_returns_tool_result(self) -> None:
        assert isinstance(StaticMockTool().invoke(ToolRequest("t")), ToolResult)

    def test_deterministic(self) -> None:
        t = StaticMockTool("x")
        req = ToolRequest("t", {"a": 1})
        assert t.invoke(req) == t.invoke(req) == ToolResult("t", "x")

    def test_deterministic_across_instances(self) -> None:
        req = ToolRequest("t", {"b": 2, "a": 1})
        assert StaticMockTool(echo=True).invoke(req) == StaticMockTool(echo=True).invoke(req)

    def test_echo_renders_request(self) -> None:
        t = StaticMockTool(echo=True)
        out = t.invoke(ToolRequest("calc", {"b": 2, "a": "x"})).output
        assert out == "calc(a='x', b=2)"

    def test_echo_with_no_arguments(self) -> None:
        assert StaticMockTool(echo=True).invoke(ToolRequest("t")).output == "t()"

    def test_echo_key_order_is_sorted_not_insertion(self) -> None:
        t = StaticMockTool(echo=True)
        assert t.invoke(ToolRequest("t", {"z": 1, "a": 2})).output == "t(a=2, z=1)"

    def test_call_count_increments(self) -> None:
        t = StaticMockTool()
        for i in range(3):
            t.invoke(ToolRequest("t"))
            assert t.call_count == i + 1

    def test_call_count_is_per_instance(self) -> None:
        a, b = StaticMockTool(), StaticMockTool()
        a.invoke(ToolRequest("t"))
        assert a.call_count == 1
        assert b.call_count == 0

    def test_does_not_mutate_request(self) -> None:
        req = ToolRequest("t", {"a": 1})
        StaticMockTool(echo=True).invoke(req)
        assert dict(req.arguments) == {"a": 1}


class TestToolErrorPropagation:
    def test_failing_tool_raises_tool_error(self) -> None:
        class Failing:
            name = "failing"
            description = "always fails"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError(f"cannot run {request.tool_name}")

        tool: ToolInterface = Failing()
        with pytest.raises(ToolError, match="cannot run x"):
            tool.invoke(ToolRequest("x"))

    def test_tool_error_is_catchable_as_exception(self) -> None:
        try:
            raise ToolError("e")
        except Exception as exc:  # noqa: BLE001
            assert isinstance(exc, ToolError)


class TestPublicAPI:
    def test_all_exact(self) -> None:
        assert set(tool_module.__all__) == {
            "ToolRequest", "ToolResult", "ToolError", "ToolInterface", "StaticMockTool",
            "TransientToolError",  # v8.33 transient signal
        }
        assert len(tool_module.__all__) == 6

    def test_all_names_resolve(self) -> None:
        for name in tool_module.__all__:
            assert hasattr(tool_module, name), name

    def test_no_module_level_mutable_state(self) -> None:
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else [node.target.id] if isinstance(node.target, ast.Name) else []
                )
                assert targets == ["__all__"], f"unexpected module-level state: {targets}"
        public = {
            n for n in vars(tool_module)
            if not n.startswith("_") and n not in tool_module.__all__
        }
        # Only imported names remain; none of them is a mutable container.
        for n in public:
            assert not isinstance(getattr(tool_module, n), (dict, list, set)), n

    def test_no_speculative_fields(self) -> None:
        for cls in (ToolRequest, ToolResult):
            names = {f.name for f in dataclasses.fields(cls)}
            for forbidden in (
                "schema", "input_schema", "metadata", "version", "permissions",
                "risk_level", "risk", "context", "ctx", "error", "success",
            ):
                assert forbidden not in names, (cls.__name__, forbidden)
        assert not hasattr(StaticMockTool, "schema")


class TestArchitecturalIsolation:
    def test_stdlib_only_imports(self) -> None:
        allowed_roots = {"__future__", "dataclasses", "types", "typing"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] in allowed_roots, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_no_core_imports(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("core"), node.module
                assert node.level == 0
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert not n.name.startswith("core"), n.name

    def test_no_forbidden_stdlib_modules(self) -> None:
        forbidden = {
            "os", "sys", "io", "socket", "asyncio", "subprocess", "logging",
            "pathlib", "json", "pickle", "http", "urllib", "concurrent",
            "threading", "multiprocessing", "sqlite3", "shelve", "importlib",
            "time", "uuid", "random",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
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
                assert node.func.id not in {"open", "print", "exec", "eval", "input"}, node.func.id

    def test_no_core_module_imports_tool_interface(self) -> None:
        for name in os.listdir(CORE_DIR):
            path = os.path.join(CORE_DIR, name)
            # tool_registry.py (v8.12), skill_tool_adapter.py (v8.13) and
            # tool_router.py (v8.14) are the sanctioned consumers.
            if name.endswith(".py") and name not in (
                "tool_interface.py", "tool_registry.py", "skill_tool_adapter.py",
                "tool_router.py", "tool_runtime.py",  # v8.39: the loop builds ToolRequests
            ):
                with open(path, encoding="utf-8") as f:
                    assert "tool_interface" not in f.read(), name
        # core/agent/__init__.py is a sanctioned consumer since v8.16
        # (ToolRequest for the opt-in routing method); its own tests guard it.


class TestCoexistenceWithSkillSystem:
    def test_skill_registry_untouched_and_distinct(self) -> None:
        import core.skill_registry as skill_registry
        from core.skill_dispatch import SkillDispatchDecision

        # Skill vocabulary keeps its own types; nothing is shared.
        assert skill_registry.SkillManifest is not ToolRequest
        assert SkillDispatchDecision is not ToolResult
        assert not hasattr(skill_registry, "ToolInterface")
        assert not hasattr(skill_registry, "ToolRequest")
        assert not hasattr(tool_module, "SkillManifest")
        assert not hasattr(tool_module, "register_skill")
        assert not hasattr(tool_module, "dispatch")

    def test_tool_interface_has_no_registry_surface(self) -> None:
        for attr in (
            "register", "register_tool", "dispatch", "discover", "lookup",
            "list_tools", "get_tool", "route", "default_tool",
        ):
            assert not hasattr(tool_module, attr), attr

    def test_no_global_registry_in_mock(self) -> None:
        a = StaticMockTool(name="a")
        b = StaticMockTool(name="a")
        # Same name, no conflict: nothing registers anywhere.
        assert a is not b
        assert a.call_count == b.call_count == 0
