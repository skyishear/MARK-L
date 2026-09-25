"""Tests for v8.14 Tool Router."""

from __future__ import annotations

import ast
import inspect
import os
import sys
import threading

import pytest

import core.skill_registry as skill_registry
import core.tool_router as router_module
from core.skill_registry import SkillManifest
from core.skill_tool_adapter import adapt_skill_manifest
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolAlreadyRegisteredError, ToolRegistry
from core.tool_router import ToolNotFoundError, ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "tool_router.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


class SpyTool:
    """Records the exact request object it receives and returns a fixed result."""

    def __init__(self, name: str = "spy", result: ToolResult | None = None) -> None:
        self.name = name
        self.description = "spy tool"
        self.received: list[ToolRequest] = []
        self.result = result if result is not None else ToolResult(name, "spied")

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.received.append(request)
        return self.result


def build() -> tuple[ToolRouter, ToolRegistry, SpyTool]:
    registry = ToolRegistry()
    spy = SpyTool("a")
    registry.register(spy)
    return ToolRouter(registry), registry, spy


# ── Construction ────────────────────────────────────────────────────────


class TestConstruction:
    def test_accepts_registry(self) -> None:
        r = ToolRegistry()
        assert ToolRouter(r).registry is r

    def test_registry_identity_preserved(self) -> None:
        router, registry, _ = build()
        assert router.registry is registry

    def test_rejects_non_registry(self) -> None:
        with pytest.raises(TypeError):
            ToolRouter(object())  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            ToolRouter(None)  # type: ignore[arg-type]

    def test_registry_is_required(self) -> None:
        with pytest.raises(TypeError):
            ToolRouter()  # type: ignore[call-arg]

    def test_registry_property_read_only(self) -> None:
        router, _, _ = build()
        with pytest.raises(AttributeError):
            router.registry = ToolRegistry()  # type: ignore[misc]

    def test_no_default_registry_construction(self) -> None:
        params = inspect.signature(ToolRouter.__init__).parameters
        assert list(params) == ["self", "tool_registry"]
        assert params["tool_registry"].default is inspect.Parameter.empty


# ── Routing ─────────────────────────────────────────────────────────────


class TestRouting:
    def test_routes_registered_tool(self) -> None:
        router, _, spy = build()
        res = router.route(ToolRequest("a"))
        assert res.output == "spied"
        assert len(spy.received) == 1

    def test_exact_request_reaches_invoke(self) -> None:
        router, _, spy = build()
        req = ToolRequest("a", {"x": 1})
        router.route(req)
        assert spy.received[0] is req

    def test_exact_result_identity_returned(self) -> None:
        router, _, spy = build()
        assert router.route(ToolRequest("a")) is spy.result

    def test_result_not_reconstructed(self) -> None:
        registry = ToolRegistry()
        fixed = ToolResult("a", "fixed")
        registry.register(SpyTool("a", result=fixed))
        assert ToolRouter(registry).route(ToolRequest("a")) is fixed

    def test_multiple_tools_route_correctly(self) -> None:
        registry = ToolRegistry()
        a, b, c = SpyTool("a"), SpyTool("b"), SpyTool("c")
        for t in (a, b, c):
            registry.register(t)
        router = ToolRouter(registry)
        router.route(ToolRequest("b"))
        router.route(ToolRequest("c"))
        router.route(ToolRequest("b"))
        assert (len(a.received), len(b.received), len(c.received)) == (0, 2, 1)

    def test_resolution_uses_request_tool_name(self) -> None:
        registry = ToolRegistry()
        spy = SpyTool("target")
        registry.register(spy)
        ToolRouter(registry).route(ToolRequest("target"))
        assert spy.received[0].tool_name == "target"

    def test_arguments_pass_through_unchanged(self) -> None:
        router, _, spy = build()
        router.route(ToolRequest("a", {"k": "v", "n": 2}))
        assert dict(spy.received[0].arguments) == {"k": "v", "n": 2}

    def test_static_mock_tool_routes(self) -> None:
        registry = ToolRegistry()
        mock = StaticMockTool(name="m", output="hello")
        registry.register(mock)
        res = ToolRouter(registry).route(ToolRequest("m"))
        assert res == ToolResult("m", "hello")
        assert mock.call_count == 1

    def test_exact_registered_instance_invoked(self) -> None:
        registry = ToolRegistry()
        registered = StaticMockTool(name="m")
        other = StaticMockTool(name="m")
        registry.register(registered)
        ToolRouter(registry).route(ToolRequest("m"))
        assert registered.call_count == 1
        assert other.call_count == 0

    def test_repeated_routing_deterministic(self) -> None:
        registry = ToolRegistry()
        registry.register(StaticMockTool(name="m", echo=True))
        router = ToolRouter(registry)
        req = ToolRequest("m", {"b": 2, "a": 1})
        assert router.route(req) == router.route(req) == ToolResult("m", "m(a=1, b=2)")


# ── Errors ──────────────────────────────────────────────────────────────


class TestErrors:
    def test_unknown_tool_raises_tool_not_found(self) -> None:
        router, _, _ = build()
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("missing"))

    def test_error_message_contains_tool_name(self) -> None:
        router, _, _ = build()
        with pytest.raises(ToolNotFoundError, match="Tool not registered: missing"):
            router.route(ToolRequest("missing"))

    def test_error_is_value_error(self) -> None:
        assert issubclass(ToolNotFoundError, ValueError)
        assert ToolNotFoundError.__bases__ == (ValueError,)
        assert ToolNotFoundError.__subclasses__() == []

    def test_empty_registry_raises(self) -> None:
        with pytest.raises(ToolNotFoundError):
            ToolRouter(ToolRegistry()).route(ToolRequest("anything"))

    def test_non_request_raises_type_error(self) -> None:
        router, _, _ = build()
        for bad in ("a", None, {"tool_name": "a"}, object()):
            with pytest.raises(TypeError):
                router.route(bad)  # type: ignore[arg-type]

    def test_tool_exception_propagates_unchanged(self) -> None:
        class Custom(RuntimeError):
            pass

        class Failing:
            name = "f"
            description = "fails"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise Custom("boom")

        registry = ToolRegistry()
        registry.register(Failing())
        with pytest.raises(Custom, match="boom") as info:
            ToolRouter(registry).route(ToolRequest("f"))
        assert type(info.value) is Custom

    def test_tool_error_propagates_unchanged(self) -> None:
        class Failing:
            name = "f"
            description = "fails"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError("tool failed")

        registry = ToolRegistry()
        registry.register(Failing())
        with pytest.raises(ToolError, match="tool failed"):
            ToolRouter(registry).route(ToolRequest("f"))

    def test_router_has_no_exception_handling(self) -> None:
        for node in ast.walk(_tree()):
            assert not isinstance(node, (ast.Try, ast.ExceptHandler))

    def test_not_found_does_not_invoke_anything(self) -> None:
        router, _, spy = build()
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("missing"))
        assert spy.received == []


# ── Immutability / no mutation ──────────────────────────────────────────


class TestNoMutation:
    def test_request_not_mutated(self) -> None:
        router, _, _ = build()
        req = ToolRequest("a", {"x": 1})
        router.route(req)
        assert req.tool_name == "a"
        assert dict(req.arguments) == {"x": 1}

    def test_registry_not_mutated(self) -> None:
        router, registry, _ = build()
        before = (registry.names(), registry.list_tools(), registry.count())
        router.route(ToolRequest("a"))
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("missing"))
        assert (registry.names(), registry.list_tools(), registry.count()) == before

    def test_router_does_not_register(self) -> None:
        router, registry, _ = build()
        assert not hasattr(router, "register")
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("new"))
        assert not registry.has("new")

    def test_router_does_not_unregister(self) -> None:
        router, registry, _ = build()
        assert not hasattr(router, "unregister")
        router.route(ToolRequest("a"))
        assert registry.has("a")

    def test_unregister_causes_routing_failure(self) -> None:
        router, registry, _ = build()
        router.route(ToolRequest("a"))
        registry.unregister("a")
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("a"))

    def test_clear_causes_routing_failure(self) -> None:
        router, registry, _ = build()
        registry.clear()
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("a"))

    def test_live_registry_view_not_snapshot(self) -> None:
        router, registry, _ = build()
        late = SpyTool("late")
        registry.register(late)
        router.route(ToolRequest("late"))
        assert len(late.received) == 1

    def test_duplicate_handling_remains_registry_responsibility(self) -> None:
        router, registry, _ = build()
        with pytest.raises(ToolAlreadyRegisteredError):
            registry.register(SpyTool("a"))
        assert not hasattr(router, "replace")

    def test_router_owns_no_mutable_state(self) -> None:
        router, _, _ = build()
        assert ToolRouter.__slots__ == ("_registry",)
        assert not hasattr(router, "__dict__")
        for attr in ("_lock", "_cache", "_history", "call_count", "_last"):
            assert not hasattr(router, attr), attr
        router.route(ToolRequest("a"))
        assert router.registry is router.registry


# ── Isolation from legacy skill system ──────────────────────────────────


class TestSkillIsolation:
    def test_no_skill_registry_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(skill_registry, "is_registered", lambda n: called.append("is_registered") or True)
        with pytest.raises(ToolNotFoundError):
            ToolRouter(ToolRegistry()).route(ToolRequest("weather_report"))
        assert called == []

    def test_no_automatic_skill_adaptation(self) -> None:
        # A manifest that exists but was never adapted+registered is invisible.
        m = SkillManifest(
            name="s", description="d",
            tools=[{"name": "unadapted", "description": "x"}],
            handler=lambda n, a, c: "never",
        )
        registry = ToolRegistry()
        with pytest.raises(ToolNotFoundError):
            ToolRouter(registry).route(ToolRequest("unadapted"))
        # Explicit adaptation by the caller is what makes it routable.
        for t in adapt_skill_manifest(m):
            registry.register(t)
        assert ToolRouter(registry).route(ToolRequest("unadapted")).output == "never"

    def test_skill_globals_untouched(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        router, _, _ = build()
        router.route(ToolRequest("a"))
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest("nope"))
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001

    def test_adapted_skill_tool_routes_end_to_end(self) -> None:
        calls: list[tuple] = []
        m = SkillManifest(
            name="weather", description="d",
            tools=[{"name": "weather_report", "description": "x"}],
            handler=lambda n, a, c: calls.append((n, a, c)) or "sunny",
        )
        registry = ToolRegistry()
        (tool,) = adapt_skill_manifest(m, context={"ui": "UI"})
        registry.register(tool)
        res = ToolRouter(registry).route(ToolRequest("weather_report", {"city": "Mumbai"}))
        assert res == ToolResult("weather_report", "sunny")
        assert calls == [("weather_report", {"city": "Mumbai"}, tool.context)]


# ── Concurrency ─────────────────────────────────────────────────────────


class TestConcurrency:
    def test_shared_router_concurrent_routing(self) -> None:
        registry = ToolRegistry()
        tools = [StaticMockTool(name=f"t{i}", output=f"o{i}") for i in range(8)]
        for t in tools:
            registry.register(t)
        router = ToolRouter(registry)
        results: dict[str, list[str]] = {t.name: [] for t in tools}
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker(name: str) -> None:
            try:
                for _ in range(20):
                    out = router.route(ToolRequest(name)).output
                    with lock:
                        results[name].append(out)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t.name,)) for t in tools for _ in range(3)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors
        for t in tools:
            assert results[t.name] == [f"o{t.name[1:]}"] * 60
            assert t.call_count == 60


# ── Public API / architecture ───────────────────────────────────────────


class TestPublicAPI:
    def test_all_exact(self) -> None:
        assert router_module.__all__ == ["ToolNotFoundError", "ToolRouter"]

    def test_router_surface(self) -> None:
        router, _, _ = build()
        assert callable(router.route)
        assert isinstance(inspect.getattr_static(ToolRouter, "registry"), property)

    def test_no_forbidden_surface(self) -> None:
        router, _, _ = build()
        for attr in (
            "register", "unregister", "discover", "fallback", "retry",
            "policy", "cache", "history", "metrics", "log", "clear",
            "route_async", "aroute", "dispatch", "adapt", "skills",
        ):
            assert not hasattr(router, attr), attr
        for attr in ("default_router", "build_default_router", "ROUTER", "router"):
            assert not hasattr(router_module, attr), attr

    def test_route_is_synchronous(self) -> None:
        assert not inspect.iscoroutinefunction(ToolRouter.route)


class TestArchitecture:
    def test_import_allowlist(self) -> None:
        allowed_roots = {"__future__", "typing", "dataclasses", "types"}
        allowed_full = {"core.tool_interface", "core.tool_registry"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    node.module.split(".")[0] in allowed_roots
                    or node.module in allowed_full
                ), node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_imports_only_needed_names(self) -> None:
        names = {
            (node.module, n.name)
            for node in ast.walk(_tree())
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("core")
            for n in node.names
        }
        assert names == {
            ("core.tool_interface", "ToolRequest"),
            ("core.tool_interface", "ToolResult"),
            ("core.tool_registry", "ToolRegistry"),
        }

    def test_forbidden_imports(self) -> None:
        forbidden = {
            "core.skill_registry", "core.skill_dispatch", "core.skill_tool_adapter",
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_provider_registry", "core.memory_engine", "core.reflection_engine",
            "core.planner", "core.planning_engine", "core.execution_pipeline",
            "core.execution_orchestrator", "core.execution_session",
            "core.execution_coordinator", "core.execution_result",
            "core.execution_progress", "core.execution_event",
            "core.execution_planner", "core.pipeline_engine", "core.pipeline_run",
            "core.goal_manager", "core.task_graph", "core.problem_solver",
            "os", "sys", "io", "socket", "asyncio", "threading", "subprocess",
            "logging", "pathlib", "importlib", "json", "pickle", "http", "urllib",
            "concurrent", "time", "random",
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

    def test_no_private_registry_access(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"_tools", "_order", "_lock"}, node.attr

    def test_only_public_registry_method_used(self) -> None:
        used = {
            node.attr
            for node in ast.walk(_tree())
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "_registry"
        }
        assert used == {"get"}

    def test_no_module_level_mutable_state(self) -> None:
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else [node.target.id] if isinstance(node.target, ast.Name) else []
                )
                assert targets == ["__all__"], targets
        for name, value in vars(router_module).items():
            if not name.startswith("__"):
                assert not isinstance(value, (dict, list, set)), name

    def test_import_has_no_side_effects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "discover_skills", lambda *a, **k: called.append("discover"))
        monkeypatch.setattr(skill_registry, "register_skill", lambda m: called.append("register"))
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        import importlib
        sys.modules.pop("core.tool_router", None)
        try:
            importlib.import_module("core.tool_router")
        finally:
            sys.modules["core.tool_router"] = router_module
        assert called == []
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001

    def test_no_core_module_imports_router(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "tool_router.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "tool_router" not in f.read(), name
        # core/agent/__init__.py is a sanctioned consumer since v8.15
        # (composition only); main.py must still not import the router.
        for rel in ("main.py",):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                assert "tool_router" not in f.read(), rel

    def test_dependency_direction(self) -> None:
        # Router depends on registry + interface; neither depends on the router.
        for dep in ("tool_registry.py", "tool_interface.py", "skill_tool_adapter.py"):
            with open(os.path.join(CORE_DIR, dep), encoding="utf-8") as f:
                assert "tool_router" not in f.read(), dep


class TestCoexistence:
    def test_coexists_with_v8_11_to_v8_13(self) -> None:
        # Interface, registry and adapter remain importable, distinct, and unchanged in role.
        from core import skill_tool_adapter, tool_interface, tool_registry

        assert ToolRouter is not tool_registry.ToolRegistry
        assert ToolNotFoundError is not ToolAlreadyRegisteredError
        assert ToolNotFoundError is not tool_interface.ToolError
        assert not hasattr(tool_registry, "ToolRouter")
        assert not hasattr(tool_interface, "ToolRouter")
        assert not hasattr(skill_tool_adapter, "ToolRouter")

    def test_legacy_dispatch_untouched(self) -> None:
        # Legacy runtime path still answers independently of the router.
        assert skill_registry.dispatch("router_only_tool", {}, {}) is None
        registry = ToolRegistry()
        registry.register(StaticMockTool(name="router_only_tool", output="x"))
        assert ToolRouter(registry).route(ToolRequest("router_only_tool")).output == "x"
        assert skill_registry.dispatch("router_only_tool", {}, {}) is None
