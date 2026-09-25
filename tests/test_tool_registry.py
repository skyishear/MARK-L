"""Tests for v8.12 Tool Registry."""

from __future__ import annotations

import ast
import os
import threading

import pytest

import core.tool_registry as registry_module
from core.tool_interface import StaticMockTool, ToolInterface, ToolRequest, ToolResult
from core.tool_registry import ToolAlreadyRegisteredError, ToolRegistry

HERE = os.path.dirname(__file__)
CORE_DIR = os.path.normpath(os.path.join(HERE, "..", "core"))
MODULE_PATH = os.path.join(CORE_DIR, "tool_registry.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


class DuckTool:
    """Structurally conforming tool with no inheritance."""

    def __init__(self, name: str = "duck", description: str = "duck tool") -> None:
        self.name = name
        self.description = description
        self.invoked = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.invoked += 1
        return ToolResult(tool_name=request.tool_name, output="quack")


class TestEmpty:
    def test_count_is_zero(self) -> None:
        assert ToolRegistry().count() == 0

    def test_len_is_zero(self) -> None:
        assert len(ToolRegistry()) == 0

    def test_names_empty(self) -> None:
        assert ToolRegistry().names() == ()

    def test_list_tools_empty(self) -> None:
        assert ToolRegistry().list_tools() == ()

    def test_get_unknown_returns_none(self) -> None:
        assert ToolRegistry().get("nope") is None

    def test_has_unknown_false(self) -> None:
        assert ToolRegistry().has("nope") is False


class TestRegisterAndLookup:
    def test_register_returns_same_instance(self) -> None:
        r = ToolRegistry()
        t = StaticMockTool(name="a")
        assert r.register(t) is t

    def test_register_then_get_identity(self) -> None:
        r = ToolRegistry()
        t = StaticMockTool(name="a")
        r.register(t)
        assert r.get("a") is t

    def test_has_after_register(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        assert r.has("a") is True
        assert r.has("b") is False

    def test_register_increments_count(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        r.register(StaticMockTool(name="b"))
        assert r.count() == 2
        assert len(r) == 2

    def test_static_mock_tool_registers(self) -> None:
        r = ToolRegistry()
        t = StaticMockTool()
        r.register(t)
        assert r.get("mock") is t

    def test_duck_typed_object_registers(self) -> None:
        r = ToolRegistry()
        t = DuckTool()
        r.register(t)
        assert r.get("duck") is t
        assert ToolInterface not in type(t).__mro__

    def test_list_tools_identity(self) -> None:
        r = ToolRegistry()
        a, b = StaticMockTool(name="a"), DuckTool(name="b")
        r.register(a)
        r.register(b)
        listed = r.list_tools()
        assert listed[0] is a
        assert listed[1] is b


class TestDuplicates:
    def test_duplicate_different_instance_raises(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        with pytest.raises(ToolAlreadyRegisteredError):
            r.register(StaticMockTool(name="a"))

    def test_error_is_value_error(self) -> None:
        assert issubclass(ToolAlreadyRegisteredError, ValueError)
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        with pytest.raises(ValueError):
            r.register(DuckTool(name="a"))

    def test_duplicate_does_not_replace(self) -> None:
        r = ToolRegistry()
        first = StaticMockTool(name="a")
        r.register(first)
        with pytest.raises(ToolAlreadyRegisteredError):
            r.register(StaticMockTool(name="a"))
        assert r.get("a") is first
        assert r.count() == 1

    def test_same_instance_idempotent(self) -> None:
        r = ToolRegistry()
        t = StaticMockTool(name="a")
        assert r.register(t) is t
        assert r.register(t) is t
        assert r.count() == 1

    def test_idempotent_reregistration_preserves_order(self) -> None:
        r = ToolRegistry()
        a, b = StaticMockTool(name="a"), StaticMockTool(name="b")
        r.register(a)
        r.register(b)
        r.register(a)
        assert r.names() == ("a", "b")
        assert r.list_tools() == (a, b)

    def test_no_replace_api(self) -> None:
        assert not hasattr(ToolRegistry, "replace")


class TestValidation:
    def test_missing_name_raises_type_error(self) -> None:
        class NoName:
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult: ...

        with pytest.raises(TypeError):
            ToolRegistry().register(NoName())  # type: ignore[arg-type]

    def test_blank_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            ToolRegistry().register(DuckTool(name=""))
        with pytest.raises(ValueError):
            ToolRegistry().register(DuckTool(name="   "))

    def test_non_string_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            ToolRegistry().register(DuckTool(name=3))  # type: ignore[arg-type]

    def test_missing_description_raises_type_error(self) -> None:
        class NoDescription:
            name = "n"

            def invoke(self, request: ToolRequest) -> ToolResult: ...

        with pytest.raises(TypeError):
            ToolRegistry().register(NoDescription())  # type: ignore[arg-type]

    def test_non_string_description_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            ToolRegistry().register(DuckTool(description=None))  # type: ignore[arg-type]

    def test_missing_invoke_raises_type_error(self) -> None:
        class NoInvoke:
            name = "n"
            description = "d"

        with pytest.raises(TypeError):
            ToolRegistry().register(NoInvoke())  # type: ignore[arg-type]

    def test_non_callable_invoke_raises_type_error(self) -> None:
        class BadInvoke:
            name = "n"
            description = "d"
            invoke = "not callable"

        with pytest.raises(TypeError):
            ToolRegistry().register(BadInvoke())  # type: ignore[arg-type]

    def test_none_tool_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            ToolRegistry().register(None)  # type: ignore[arg-type]

    def test_bare_callable_rejected(self) -> None:
        with pytest.raises(TypeError):
            ToolRegistry().register(lambda request: None)  # type: ignore[arg-type]

    def test_invalid_registration_leaves_registry_empty(self) -> None:
        r = ToolRegistry()
        with pytest.raises(ValueError):
            r.register(DuckTool(name=""))
        assert r.count() == 0
        assert r.names() == ()


class TestOrderAndSnapshots:
    def test_names_insertion_order(self) -> None:
        r = ToolRegistry()
        for n in ("c", "a", "b"):
            r.register(StaticMockTool(name=n))
        assert r.names() == ("c", "a", "b")

    def test_list_tools_insertion_order(self) -> None:
        r = ToolRegistry()
        tools = [StaticMockTool(name=n) for n in ("c", "a", "b")]
        for t in tools:
            r.register(t)
        assert list(r.list_tools()) == tools

    def test_names_returns_tuple(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        assert isinstance(r.names(), tuple)

    def test_list_tools_returns_tuple(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        assert isinstance(r.list_tools(), tuple)

    def test_snapshots_do_not_track_later_mutation(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        names, tools = r.names(), r.list_tools()
        r.register(StaticMockTool(name="b"))
        r.unregister("a")
        assert names == ("a",)
        assert len(tools) == 1

    def test_snapshots_are_not_internal_containers(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        assert r.names() is not r._order  # noqa: SLF001
        assert r.list_tools() is not r._tools  # noqa: SLF001


class TestUnregisterAndClear:
    def test_unregister_existing_true(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        assert r.unregister("a") is True
        assert r.get("a") is None
        assert r.has("a") is False
        assert r.count() == 0

    def test_unregister_unknown_false(self) -> None:
        assert ToolRegistry().unregister("missing") is False

    def test_unregister_preserves_relative_order(self) -> None:
        r = ToolRegistry()
        for n in ("a", "b", "c"):
            r.register(StaticMockTool(name=n))
        r.unregister("b")
        assert r.names() == ("a", "c")

    def test_reregister_after_unregister_appends(self) -> None:
        r = ToolRegistry()
        a = StaticMockTool(name="a")
        r.register(a)
        r.register(StaticMockTool(name="b"))
        r.unregister("a")
        r.register(a)
        assert r.names() == ("b", "a")

    def test_clear_resets_state(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="a"))
        r.register(StaticMockTool(name="b"))
        r.clear()
        assert r.count() == 0
        assert len(r) == 0
        assert r.names() == ()
        assert r.list_tools() == ()
        assert r.get("a") is None

    def test_clear_on_empty_is_safe(self) -> None:
        r = ToolRegistry()
        r.clear()
        assert r.count() == 0


class TestMutableToolName:
    def test_name_mutation_does_not_rekey(self) -> None:
        r = ToolRegistry()
        t = DuckTool(name="original")
        r.register(t)
        t.name = "renamed"
        assert r.names() == ("original",)
        assert r.get("renamed") is None
        assert r.has("renamed") is False

    def test_original_name_remains_usable(self) -> None:
        r = ToolRegistry()
        t = DuckTool(name="original")
        r.register(t)
        t.name = "renamed"
        assert r.get("original") is t
        assert r.has("original") is True
        assert r.unregister("original") is True

    def test_registering_renamed_instance_again_registers_under_new_name(self) -> None:
        # Name is captured at registration time; the same instance may
        # therefore be registered again under its new name.
        r = ToolRegistry()
        t = DuckTool(name="original")
        r.register(t)
        t.name = "renamed"
        r.register(t)
        assert r.names() == ("original", "renamed")
        assert r.get("original") is t
        assert r.get("renamed") is t


class TestSharedInstances:
    def test_same_instance_in_two_registries(self) -> None:
        t = StaticMockTool(name="shared")
        r1, r2 = ToolRegistry(), ToolRegistry()
        r1.register(t)
        r2.register(t)
        assert r1.get("shared") is t
        assert r2.get("shared") is t

    def test_registries_are_independent(self) -> None:
        t = StaticMockTool(name="shared")
        r1, r2 = ToolRegistry(), ToolRegistry()
        r1.register(t)
        r2.register(t)
        r1.unregister("shared")
        assert r1.has("shared") is False
        assert r2.has("shared") is True
        r2.clear()
        assert r1.count() == 0 and r2.count() == 0

    def test_tool_not_mutated_by_registration(self) -> None:
        t = StaticMockTool(name="a")
        before = dict(vars(t))
        ToolRegistry().register(t)
        assert vars(t) == before


class TestNoInvocation:
    def test_registry_never_invokes(self) -> None:
        r = ToolRegistry()
        mock, duck = StaticMockTool(name="m"), DuckTool(name="d")
        r.register(mock)
        r.register(duck)
        r.register(mock)
        r.get("m")
        r.has("d")
        r.names()
        r.list_tools()
        r.count()
        len(r)
        r.unregister("d")
        r.clear()
        assert mock.call_count == 0
        assert duck.invoked == 0

    def test_registered_tool_still_invokable_by_caller(self) -> None:
        r = ToolRegistry()
        r.register(StaticMockTool(name="m", output="x"))
        tool = r.get("m")
        assert tool is not None
        assert tool.invoke(ToolRequest("m")).output == "x"


class TestDeterminism:
    def test_two_registries_same_input_same_state(self) -> None:
        def build() -> ToolRegistry:
            r = ToolRegistry()
            for n in ("x", "y", "z"):
                r.register(StaticMockTool(name=n))
            r.unregister("y")
            return r

        a, b = build(), build()
        assert a.names() == b.names() == ("x", "z")
        assert a.count() == b.count() == 2

    def test_concurrent_registration_is_consistent(self) -> None:
        r = ToolRegistry()
        tools = [StaticMockTool(name=f"t{i}") for i in range(50)]
        errors: list[BaseException] = []

        def worker(t: StaticMockTool) -> None:
            try:
                r.register(t)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in tools]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors
        assert r.count() == 50
        assert set(r.names()) == {t.name for t in tools}

    def test_concurrent_duplicate_registration_admits_exactly_one(self) -> None:
        r = ToolRegistry()
        contenders = [StaticMockTool(name="same") for _ in range(20)]
        winners: list[StaticMockTool] = []
        rejected: list[BaseException] = []
        start = threading.Barrier(len(contenders))

        def worker(t: StaticMockTool) -> None:
            start.wait()
            try:
                winners.append(r.register(t))
            except ToolAlreadyRegisteredError as exc:
                rejected.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in contenders]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert len(winners) == 1
        assert len(rejected) == len(contenders) - 1
        assert r.get("same") is winners[0]


class TestPublicAPI:
    def test_all_exact(self) -> None:
        assert registry_module.__all__ == ["ToolAlreadyRegisteredError", "ToolRegistry"]

    def test_registry_methods(self) -> None:
        r = ToolRegistry()
        for name in (
            "register", "unregister", "get", "has", "names",
            "list_tools", "clear", "count", "__len__",
        ):
            assert callable(getattr(r, name)), name

    def test_no_forbidden_operations(self) -> None:
        r = ToolRegistry()
        for attr in (
            "dispatch", "invoke", "route", "discover", "discover_tools",
            "load", "save", "persist", "replace", "register_tool",
            "unregister_tool", "default_registry", "build_default_registry",
            "get_tool_declarations", "agent", "skill_registry",
        ):
            assert not hasattr(r, attr), attr
        for attr in ("default_registry", "build_default_registry", "register_tool"):
            assert not hasattr(registry_module, attr), attr

    def test_constructor_takes_no_arguments(self) -> None:
        import inspect
        assert list(inspect.signature(ToolRegistry.__init__).parameters) == ["self"]

    def test_uses_rlock(self) -> None:
        r = ToolRegistry()
        assert type(r._lock) is type(threading.RLock())  # noqa: SLF001


class TestArchitecturalIsolation:
    def test_imports_limited_to_stdlib_and_tool_interface(self) -> None:
        allowed_roots = {"__future__", "threading", "typing", "dataclasses", "types"}
        allowed_full = {"core.tool_interface"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    node.module.split(".")[0] in allowed_roots
                    or node.module in allowed_full
                ), node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_no_forbidden_modules(self) -> None:
        forbidden = {
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_provider_registry", "core.default_ai_provider_registry",
            "core.skill_registry", "core.skill_dispatch", "core.memory_engine",
            "core.reflection_engine", "core.planner", "core.planning_engine",
            "core.execution_pipeline", "core.execution_orchestrator",
            "core.execution_session", "core.execution_coordinator",
            "core.execution_result", "core.execution_progress",
            "core.execution_event", "core.execution_planner",
            "core.pipeline_engine", "core.pipeline_run", "core.goal_manager",
            "core.task_graph", "core.problem_solver", "core.conversation_history",
            "os", "sys", "io", "socket", "asyncio", "subprocess", "logging",
            "pathlib", "json", "pickle", "http", "urllib", "concurrent",
            "importlib", "sqlite3", "shelve", "multiprocessing", "glob",
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
        for name, value in vars(registry_module).items():
            if not name.startswith("__"):
                assert not isinstance(value, (dict, list, set)), name

    def test_no_core_module_imports_tool_registry(self) -> None:
        for name in os.listdir(CORE_DIR):
            path = os.path.join(CORE_DIR, name)
            # tool_router.py (v8.14), tool_dispatch.py (v8.17) and
            # stage_dispatch.py (v8.22) are the sanctioned consumers.
            if name.endswith(".py") and name not in (
                "tool_registry.py", "tool_router.py", "tool_dispatch.py",
                "stage_dispatch.py",
            ):
                with open(path, encoding="utf-8") as f:
                    assert "tool_registry" not in f.read(), name
        # core/agent/__init__.py is a sanctioned consumer since v8.15
        # (composition only); its own tests guard that boundary.


class TestCoexistenceWithSkillRegistry:
    def test_skill_registry_untouched_and_distinct(self) -> None:
        import core.skill_registry as skill_registry

        assert not hasattr(skill_registry, "ToolRegistry")
        assert not hasattr(registry_module, "SkillManifest")
        assert not hasattr(registry_module, "register_skill")
        assert not hasattr(registry_module, "discover_skills")
        assert registry_module.ToolRegistry is not getattr(
            skill_registry, "ToolRegistry", None
        )

    def test_tool_registry_does_not_touch_skill_globals(self) -> None:
        import core.skill_registry as skill_registry

        before_skills = dict(skill_registry._skills)  # noqa: SLF001
        before_index = dict(skill_registry._tool_index)  # noqa: SLF001
        r = ToolRegistry()
        r.register(StaticMockTool(name="weather"))
        assert skill_registry._skills == before_skills  # noqa: SLF001
        assert skill_registry._tool_index == before_index  # noqa: SLF001
        assert skill_registry.is_registered("weather") == ("weather" in before_index)

    def test_registry_instances_have_no_shared_state(self) -> None:
        # Anti-pattern check against the legacy module-level registry.
        r1, r2 = ToolRegistry(), ToolRegistry()
        r1.register(StaticMockTool(name="a"))
        assert r2.count() == 0
        assert r1._tools is not r2._tools  # noqa: SLF001
