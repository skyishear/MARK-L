"""Tests for v8.16 Router-Backed Tool Dispatch Path."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import threading
from types import MappingProxyType

import pytest

import core.agent as agent_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
from core.agent import Agent
from core.skill_registry import SkillManifest
from core.skill_tool_adapter import adapt_skill_manifest
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolNotFoundError, ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")
METHOD = "execute_request_with_tool_routing"


def _agent_tree() -> ast.Module:
    with open(AGENT_FILE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _method_node() -> ast.FunctionDef:
    for node in ast.walk(_agent_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == METHOD:
            return node
    raise AssertionError("method not found")


def _skill_globals() -> tuple[dict, dict]:
    return dict(skill_registry._skills), dict(skill_registry._tool_index)  # noqa: SLF001


class SpyTool:
    def __init__(self, name: str, output: str = "spied") -> None:
        self.name = name
        self.description = "spy"
        self.received: list[ToolRequest] = []
        self.result = ToolResult(name, output)

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.received.append(request)
        return self.result


class SpyRouter(ToolRouter):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(registry)
        self.requests: list[ToolRequest] = []

    def route(self, request: ToolRequest) -> ToolResult:
        self.requests.append(request)
        return super().route(request)


def build() -> tuple[Agent, SpyRouter, SpyTool]:
    registry = ToolRegistry()
    spy = SpyTool("a")
    registry.register(spy)
    router = SpyRouter(registry)
    return Agent(tool_registry=registry, tool_router=router), router, spy


# ── API shape ───────────────────────────────────────────────────────────


class TestAPIShape:
    def test_method_exists(self) -> None:
        assert callable(getattr(Agent, METHOD))

    def test_signature_follows_conventions(self) -> None:
        sig = inspect.signature(getattr(Agent, METHOD))
        params = list(sig.parameters.values())
        assert [p.name for p in params] == ["self", "tool_name", "arguments"]
        assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert params[2].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[2].default is None

    def test_is_synchronous(self) -> None:
        assert not inspect.iscoroutinefunction(getattr(Agent, METHOD))

    def test_name_follows_execute_request_family(self) -> None:
        assert METHOD.startswith("execute_request_with_")
        siblings = [n for n in dir(Agent) if n.startswith("execute_request")]
        assert METHOD in siblings

    def test_returns_tool_result(self) -> None:
        a, _, _ = build()
        assert isinstance(a.execute_request_with_tool_routing("a"), ToolResult)


# ── Routing behaviour ───────────────────────────────────────────────────


class TestRouting:
    def test_tool_request_created_correctly(self) -> None:
        a, router, _ = build()
        a.execute_request_with_tool_routing("a", arguments={"x": 1})
        req = router.requests[0]
        assert isinstance(req, ToolRequest)
        assert req.tool_name == "a"
        assert dict(req.arguments) == {"x": 1}

    def test_exact_request_reaches_router_and_tool(self) -> None:
        a, router, spy = build()
        a.execute_request_with_tool_routing("a", arguments={"x": 1})
        assert spy.received[0] is router.requests[0]

    def test_exact_result_returned(self) -> None:
        a, _, spy = build()
        assert a.execute_request_with_tool_routing("a") is spy.result

    def test_static_mock_tool(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m", output="hello"))
        assert a.execute_request_with_tool_routing("m") == ToolResult("m", "hello")

    def test_multiple_tools(self) -> None:
        a = Agent()
        for n in ("x", "y", "z"):
            a.tool_registry.register(StaticMockTool(name=n, output=f"out-{n}"))
        assert a.execute_request_with_tool_routing("y").output == "out-y"
        assert a.execute_request_with_tool_routing("z").output == "out-z"
        assert a.execute_request_with_tool_routing("x").output == "out-x"

    def test_router_called_exactly_once(self) -> None:
        a, router, _ = build()
        a.execute_request_with_tool_routing("a")
        assert len(router.requests) == 1

    def test_exact_tool_identity_preserved(self) -> None:
        a = Agent()
        registered = StaticMockTool(name="m")
        lookalike = StaticMockTool(name="m")
        a.tool_registry.register(registered)
        a.execute_request_with_tool_routing("m")
        assert registered.call_count == 1
        assert lookalike.call_count == 0

    def test_injected_router_is_used(self) -> None:
        a, router, _ = build()
        assert a.tool_router is router
        a.execute_request_with_tool_routing("a")
        assert router.requests

    def test_injected_registry_intact(self) -> None:
        a, _, spy = build()
        before = (a.tool_registry.names(), a.tool_registry.list_tools())
        a.execute_request_with_tool_routing("a")
        assert (a.tool_registry.names(), a.tool_registry.list_tools()) == before
        assert a.tool_registry.get("a") is spy

    def test_echo_tool_sees_arguments(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="e", echo=True))
        res = a.execute_request_with_tool_routing("e", arguments={"b": 2, "a": 1})
        assert res.output == "e(a=1, b=2)"

    def test_deterministic_repeat(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m", output="o"))
        r1 = a.execute_request_with_tool_routing("m", arguments={"k": 1})
        r2 = a.execute_request_with_tool_routing("m", arguments={"k": 1})
        assert r1 == r2


# ── Arguments ───────────────────────────────────────────────────────────


class TestArguments:
    def test_arguments_preserved(self) -> None:
        a, _, spy = build()
        a.execute_request_with_tool_routing("a", arguments={"city": "Mumbai", "n": 3})
        assert dict(spy.received[0].arguments) == {"city": "Mumbai", "n": 3}

    def test_caller_arguments_not_mutated(self) -> None:
        a, _, _ = build()
        args = {"k": 1}
        a.execute_request_with_tool_routing("a", arguments=args)
        assert args == {"k": 1}

    def test_caller_arguments_not_aliased(self) -> None:
        a, _, spy = build()
        args = {"k": 1}
        a.execute_request_with_tool_routing("a", arguments=args)
        args["k"] = 99
        assert dict(spy.received[0].arguments) == {"k": 1}

    def test_none_arguments_follow_tool_request_default(self) -> None:
        a, _, spy = build()
        a.execute_request_with_tool_routing("a")
        assert spy.received[0] == ToolRequest("a")
        assert isinstance(spy.received[0].arguments, MappingProxyType)
        assert dict(spy.received[0].arguments) == {}

    def test_explicit_none_same_as_omitted(self) -> None:
        a, _, spy = build()
        a.execute_request_with_tool_routing("a", arguments=None)
        assert spy.received[0] == ToolRequest("a")

    def test_read_only_mapping_accepted(self) -> None:
        a, _, spy = build()
        a.execute_request_with_tool_routing("a", arguments=MappingProxyType({"k": "v"}))
        assert dict(spy.received[0].arguments) == {"k": "v"}

    def test_request_validation_delegated_to_tool_request(self) -> None:
        a, router, _ = build()
        with pytest.raises(ValueError):
            a.execute_request_with_tool_routing("")
        with pytest.raises(ValueError):
            a.execute_request_with_tool_routing("a", arguments=["bad"])  # type: ignore[arg-type]
        assert router.requests == []  # validation failed before routing


# ── Errors ──────────────────────────────────────────────────────────────


class TestErrors:
    def test_unknown_tool_raises_tool_not_found(self) -> None:
        a = Agent()
        with pytest.raises(ToolNotFoundError, match="Tool not registered: nope"):
            a.execute_request_with_tool_routing("nope")

    def test_tool_not_found_type_unchanged(self) -> None:
        a = Agent()
        with pytest.raises(ToolNotFoundError) as info:
            a.execute_request_with_tool_routing("nope")
        assert type(info.value) is ToolNotFoundError

    def test_tool_exception_propagates_unchanged(self) -> None:
        class Custom(RuntimeError):
            pass

        class Failing:
            name = "f"
            description = "fails"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise Custom("boom")

        a = Agent()
        a.tool_registry.register(Failing())
        with pytest.raises(Custom, match="boom") as info:
            a.execute_request_with_tool_routing("f")
        assert type(info.value) is Custom

    def test_tool_error_propagates(self) -> None:
        class Failing:
            name = "f"
            description = "fails"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError("tool failed")

        a = Agent()
        a.tool_registry.register(Failing())
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_request_with_tool_routing("f")

    def test_method_has_no_exception_handling(self) -> None:
        for node in ast.walk(_method_node()):
            assert not isinstance(node, (ast.Try, ast.ExceptHandler))

    def test_no_fallback_to_legacy_on_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch") or "x")
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or True)
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch") or "x")
        a = Agent()
        with pytest.raises(ToolNotFoundError):
            a.execute_request_with_tool_routing("weather_report")
        assert called == []


# ── Isolation from the legacy path ──────────────────────────────────────


class TestLegacyIsolation:
    def test_new_method_does_not_call_skill_registry_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("agent.dispatch"))
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        assert called == []

    def test_new_method_does_not_call_skill_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(skill_dispatch_module, "build_dispatch_decision", lambda *a, **k: called.append("decision2"))
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        assert called == []

    def test_legacy_method_does_not_call_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a, router, _ = build()
        a.handle_request("fix the wifi")
        a.execute_request("fix the wifi")
        a.execute_request_with_skill_execution("fix the wifi")
        assert router.requests == []

    def test_legacy_skill_path_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched: list[str] = []
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda name, args, ctx=None: dispatched.append(name) or "ok")
        a, router, _ = build()
        _, decisions = a.execute_request_with_skill_execution("fix the wifi")
        assert dispatched
        assert all(d.would_dispatch for d in decisions)
        assert router.requests == []

    def test_handle_request_unchanged(self) -> None:
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        snap = a.handle_request("fix the wifi")
        ref = Agent().handle_request("fix the wifi")
        assert snap.session_id == ref.session_id
        assert snap.ready_task_ids == ref.ready_task_ids

    def test_execute_request_with_skill_execution_unchanged(self) -> None:
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        result, decisions = a.execute_request_with_skill_execution("fix the wifi")
        ref_result, ref_decisions = Agent().execute_request_with_skill_execution("fix the wifi")
        assert [d.tool_name for d in decisions] == [d.tool_name for d in ref_decisions]
        assert [d.would_dispatch for d in decisions] == [d.would_dispatch for d in ref_decisions]
        assert result.session_id == ref_result.session_id

    def test_routing_is_opt_in(self) -> None:
        a, router, _ = build()
        a.handle_request("fix the wifi")
        a.execute_request_with_learning("fix the wifi")
        assert router.requests == []
        a.execute_request_with_tool_routing("a")
        assert len(router.requests) == 1

    def test_no_automatic_skill_manifest_adaptation(self) -> None:
        m = SkillManifest(
            name="s", description="d",
            tools=[{"name": "unadapted_tool", "description": "x"}],
            handler=lambda n, args, ctx: "never",
        )
        a = Agent()
        with pytest.raises(ToolNotFoundError):
            a.execute_request_with_tool_routing("unadapted_tool")
        # Explicit adaptation by the caller is required.
        for t in adapt_skill_manifest(m):
            a.tool_registry.register(t)
        assert a.execute_request_with_tool_routing("unadapted_tool").output == "never"

    def test_adapted_skill_end_to_end(self) -> None:
        calls: list[tuple] = []
        m = SkillManifest(
            name="weather", description="d",
            tools=[{"name": "weather_report", "description": "x"}],
            handler=lambda n, args, ctx: calls.append((n, args, dict(ctx))) or "sunny",
        )
        a = Agent()
        (tool,) = adapt_skill_manifest(m, context={"ui": "UI"})
        a.tool_registry.register(tool)
        res = a.execute_request_with_tool_routing("weather_report", arguments={"city": "Mumbai"})
        assert res == ToolResult("weather_report", "sunny")
        assert calls == [("weather_report", {"city": "Mumbai"}, {"ui": "UI"})]

    def test_skill_registry_globals_unchanged(self) -> None:
        before = _skill_globals()
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        with pytest.raises(ToolNotFoundError):
            a.execute_request_with_tool_routing("missing")
        assert _skill_globals() == before

    def test_no_context_invented(self) -> None:
        sig = inspect.signature(getattr(Agent, METHOD))
        assert "ctx" not in sig.parameters
        assert "context" not in sig.parameters
        assert "project" not in sig.parameters
        src = ast.get_source_segment(open(AGENT_FILE, encoding="utf-8").read(), _method_node())
        assert "ctx" not in src.split('"""')[2]  # no ctx in the code body
        a, _, spy = build()
        a.execute_request_with_tool_routing("a")
        assert tuple(f for f in dir(spy.received[0]) if f in ("ctx", "context")) == ()


# ── State / concurrency ─────────────────────────────────────────────────


class TestState:
    def test_registry_not_modified_by_routing(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m"))
        before = a.tool_registry.names()
        a.execute_request_with_tool_routing("m")
        with pytest.raises(ToolNotFoundError):
            a.execute_request_with_tool_routing("zzz")
        assert a.tool_registry.names() == before
        assert a.tool_registry.count() == 1

    def test_no_agent_state_recorded(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m"))
        snap_before = a.snapshot()
        a.execute_request_with_tool_routing("m")
        assert a.snapshot() == snap_before
        for attr in ("_tool_history", "_last_tool_result", "tool_history"):
            assert not hasattr(a, attr), attr

    def test_no_global_state_mutation(self) -> None:
        before = {k: v for k, v in vars(agent_module).items() if not k.startswith("__")}
        a, _, _ = build()
        a.execute_request_with_tool_routing("a")
        after = {k: v for k, v in vars(agent_module).items() if not k.startswith("__")}
        assert before.keys() == after.keys()
        assert all(before[k] is after[k] for k in before)

    def test_concurrent_routing_independent_agents(self) -> None:
        agents = []
        for i in range(6):
            a = Agent()
            a.tool_registry.register(StaticMockTool(name="m", output=f"o{i}"))
            agents.append(a)
        outputs: dict[int, list[str]] = {i: [] for i in range(6)}
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            try:
                for _ in range(25):
                    out = agents[i].execute_request_with_tool_routing("m").output
                    with lock:
                        outputs[i].append(out)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors
        for i in range(6):
            assert outputs[i] == [f"o{i}"] * 50


# ── Public API / architecture ───────────────────────────────────────────


class TestArchitecture:
    def test_all_unchanged(self) -> None:
        assert set(agent_module.__all__) == {
            "Agent", "CoordinationSnapshot", "ContextManager", "ExecutionCoordinator",
            "ExecutionOrchestrator", "ExecutionPipeline", "ExecutionResult",
            "ExecutionSession", "HistoryManager", "KnowledgeManager", "LearningManager",
            "MemoryIndexManager", "PlanningEngine", "ReasoningManager",
            "ReflectionManager", "SkillDispatchDecision",
        }

    def test_backward_compatible_construction_and_methods(self) -> None:
        a = Agent()
        for name in (
            "handle_request", "handle_request_with_context", "execute_request",
            "execute_request_with_skill_check", "execute_request_with_dispatch_decision",
            "execute_request_with_skill_execution", "execute_request_with_memory_writeback",
            "execute_request_with_reflection", "execute_request_with_learning",
            "snapshot", "clear_all",
        ):
            assert callable(getattr(a, name)), name

    def test_agent_imports_tool_request_from_tool_interface(self) -> None:
        imported = {
            (node.module, n.name)
            for node in ast.walk(_agent_tree())
            if isinstance(node, ast.ImportFrom) and node.module
            for n in node.names
        }
        assert ("core.tool_interface", "ToolRequest") in imported
        assert ("core.tool_interface", "ToolResult") in imported
        modules = {m for m, _ in imported}
        for forbidden in (
            "core.skill_tool_adapter", "core.ai_provider_registry",
            "core.default_ai_provider_registry", "core.claude_provider",
            "core.openai_provider", "core.gemini_provider", "core.ollama_provider",
        ):
            assert forbidden not in modules, forbidden

    def test_method_only_uses_tool_request_and_router(self) -> None:
        node = _method_node()
        calls = {
            (c.func.id if isinstance(c.func, ast.Name) else c.func.attr)
            for c in ast.walk(node) if isinstance(c, ast.Call)
        }
        assert calls == {"ToolRequest", "route"}
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert attrs == {"_tool_router", "route"}
        for name in ast.walk(node):
            if isinstance(name, ast.Name):
                assert name.id not in {
                    "skill_dispatch", "is_registered", "build_dispatch_decision",
                    "adapt_skill_manifest", "ToolRegistry", "ToolRouter",
                }, name.id

    def test_no_second_routing_implementation(self) -> None:
        # Agent never touches the registry inside the method; ToolRouter does the lookup.
        node = _method_node()
        for a in ast.walk(node):
            if isinstance(a, ast.Attribute):
                assert a.attr not in {"_tool_registry", "get", "has", "register"}, a.attr

    def test_skill_registry_import_unchanged(self) -> None:
        for node in ast.walk(_agent_tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "core.skill_registry":
                assert sorted(n.name for n in node.names) == ["dispatch", "is_registered"]

    def test_legacy_modules_untouched(self) -> None:
        for rel in (
            "skill_registry.py", "skill_dispatch.py", "execution_pipeline.py",
            "execution_orchestrator.py", "planner.py", "tool_router.py",
            "tool_registry.py", "tool_interface.py", "skill_tool_adapter.py",
        ):
            with open(os.path.join(CORE_DIR, rel), encoding="utf-8") as f:
                src = f.read()
            assert METHOD not in src, rel
            # No module of the tool stack or legacy runtime imports Agent.
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("core.agent"), (rel, node.module)
                elif isinstance(node, ast.Import):
                    for n in node.names:
                        assert not n.name.startswith("core.agent"), (rel, n.name)
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            assert METHOD not in f.read()

    def test_fresh_interpreter_no_cycle(self) -> None:
        code = (
            "import core.tool_interface, core.tool_router, core.tool_registry; "
            "from core.agent import Agent; from core.tool_interface import StaticMockTool; "
            "a = Agent(); a.tool_registry.register(StaticMockTool(name='m', output='ok')); "
            "print(a.execute_request_with_tool_routing('m').output)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"
