"""Tests for v8.15 Agent ↔ Tool Bridge."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import threading

import pytest

import core.agent as agent_module
import core.skill_registry as skill_registry
from core.agent import Agent
from core.execution_orchestrator import ExecutionOrchestrator
from core.execution_pipeline import ExecutionPipeline
from core.planner import PlanningEngine as LegacyPlanningEngine
from core.skill_registry import SkillManifest
from core.skill_tool_adapter import adapt_skill_manifest
from core.tool_interface import StaticMockTool, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolNotFoundError, ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")

EXPECTED_ALL = {
    "Agent", "CoordinationSnapshot", "ContextManager", "ExecutionCoordinator",
    "ExecutionOrchestrator", "ExecutionPipeline", "ExecutionResult",
    "ExecutionSession", "HistoryManager", "KnowledgeManager", "LearningManager",
    "MemoryIndexManager", "PlanningEngine", "ReasoningManager",
    "ReflectionManager", "SkillDispatchDecision",
}
LEGACY_EXECUTION_FILES = (
    "execution_pipeline.py", "execution_orchestrator.py", "execution_session.py",
    "execution_coordinator.py", "execution_result.py", "execution_progress.py",
    "execution_event.py", "planner.py", "skill_registry.py", "skill_dispatch.py",
)


def _agent_tree() -> ast.Module:
    with open(AGENT_FILE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _skill_globals() -> tuple[dict, dict]:
    return dict(skill_registry._skills), dict(skill_registry._tool_index)  # noqa: SLF001


# ── Default composition ─────────────────────────────────────────────────


class TestDefaults:
    def test_default_tool_registry_created(self) -> None:
        a = Agent()
        assert isinstance(a.tool_registry, ToolRegistry)

    def test_default_tool_router_created(self) -> None:
        a = Agent()
        assert isinstance(a.tool_router, ToolRouter)

    def test_router_receives_agent_registry(self) -> None:
        a = Agent()
        assert a.tool_router.registry is a.tool_registry

    def test_default_registry_empty(self) -> None:
        a = Agent()
        assert a.tool_registry.count() == 0
        assert a.tool_registry.names() == ()

    def test_fresh_instances_per_agent(self) -> None:
        a, b = Agent(), Agent()
        assert a.tool_registry is not b.tool_registry
        assert a.tool_router is not b.tool_router

    def test_params_default_to_none_and_are_last(self) -> None:
        params = inspect.signature(Agent.__init__).parameters
        names = list(params)
        assert names[-2:] == ["tool_registry", "tool_router"]
        for n in ("tool_registry", "tool_router"):
            assert params[n].default is None
            assert params[n].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    def test_existing_parameter_order_preserved(self) -> None:
        names = list(inspect.signature(Agent.__init__).parameters)
        expected_prefix = [
            "self", "history", "context", "knowledge", "learning", "memory_index",
            "reflection", "reasoning", "planning", "execution_orchestrator",
            "execution_pipeline", "ai_service", "conversation_history",
            "memory_engine", "reflection_engine", "goal_manager", "planning_engine",
            "task_graph", "execution_planner", "pipeline_engine", "pipeline_run_manager",
        ]
        assert names[: len(expected_prefix)] == expected_prefix


# ── Injection ───────────────────────────────────────────────────────────


class TestInjection:
    def test_injected_registry_identity(self) -> None:
        reg = ToolRegistry()
        a = Agent(tool_registry=reg)
        assert a.tool_registry is reg

    def test_injected_registry_wires_default_router(self) -> None:
        reg = ToolRegistry()
        a = Agent(tool_registry=reg)
        assert isinstance(a.tool_router, ToolRouter)
        assert a.tool_router.registry is reg

    def test_injected_router_identity(self) -> None:
        router = ToolRouter(ToolRegistry())
        a = Agent(tool_router=router)
        assert a.tool_router is router

    def test_injected_router_only_no_reconciliation(self) -> None:
        own = ToolRegistry()
        router = ToolRouter(own)
        a = Agent(tool_router=router)
        # Router keeps its own registry; Agent's registry is independently fresh.
        assert a.tool_router is router
        assert a.tool_router.registry is own
        assert isinstance(a.tool_registry, ToolRegistry)
        assert a.tool_registry is not own

    def test_both_injected_preserved_exactly(self) -> None:
        reg = ToolRegistry()
        other = ToolRegistry()
        router = ToolRouter(other)
        a = Agent(tool_registry=reg, tool_router=router)
        assert a.tool_registry is reg
        assert a.tool_router is router
        assert a.tool_router.registry is other  # not rewired to reg

    def test_neither_injected(self) -> None:
        a = Agent()
        assert a.tool_router.registry is a.tool_registry

    def test_shared_injected_registry_between_agents(self) -> None:
        reg = ToolRegistry()
        a, b = Agent(tool_registry=reg), Agent(tool_registry=reg)
        a.tool_registry.register(StaticMockTool(name="shared"))
        assert b.tool_registry.has("shared")
        assert b.tool_router.route(ToolRequest("shared")).tool_name == "shared"

    def test_shared_injected_router_between_agents(self) -> None:
        router = ToolRouter(ToolRegistry())
        a, b = Agent(tool_router=router), Agent(tool_router=router)
        assert a.tool_router is b.tool_router

    def test_wrong_types_rejected_by_underlying_constructors(self) -> None:
        # Agent passes the injected registry straight into ToolRouter, whose
        # own validation applies when no router is injected.
        with pytest.raises(TypeError):
            Agent(tool_registry=object())  # type: ignore[arg-type]

    def test_mixed_with_legacy_and_foundation_injection(self) -> None:
        reg = ToolRegistry()
        orch = ExecutionOrchestrator([])
        a = Agent(execution_orchestrator=orch, tool_registry=reg)
        assert a.execution_orchestrator is orch
        assert a.tool_registry is reg


# ── Properties ──────────────────────────────────────────────────────────


class TestProperties:
    def test_read_only_properties(self) -> None:
        a = Agent()
        for name in ("tool_registry", "tool_router"):
            prop = inspect.getattr_static(Agent, name)
            assert isinstance(prop, property), name
            assert prop.fset is None and prop.fdel is None, name
            with pytest.raises(AttributeError):
                setattr(a, name, None)

    def test_properties_return_stored_instances(self) -> None:
        a = Agent()
        assert a.tool_registry is a.tool_registry
        assert a.tool_router is a.tool_router
        assert a.tool_router is a._tool_router  # noqa: SLF001

    def test_no_tool_operations_on_agent(self) -> None:
        a = Agent()
        for attr in (
            "register_tool", "route", "route_tool", "invoke_tool", "tools",
            "adapt_skills", "discover_tools", "tool_dispatch",
        ):
            assert not hasattr(a, attr), attr


# ── Bridge usability ────────────────────────────────────────────────────


class TestBridgeUsage:
    def test_register_through_exposed_registry(self) -> None:
        a = Agent()
        t = StaticMockTool(name="m")
        a.tool_registry.register(t)
        assert a.tool_registry.get("m") is t

    def test_route_through_agent_bridge(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="m", output="hello"))
        assert a.tool_router.route(ToolRequest("m")) == ToolResult("m", "hello")

    def test_exact_tool_identity_preserved(self) -> None:
        a = Agent()
        t = StaticMockTool(name="m")
        a.tool_registry.register(t)
        a.tool_router.route(ToolRequest("m"))
        assert t.call_count == 1
        assert a.tool_registry.get("m") is t

    def test_unknown_tool_raises_from_router(self) -> None:
        a = Agent()
        with pytest.raises(ToolNotFoundError):
            a.tool_router.route(ToolRequest("nope"))

    def test_explicit_skill_adaptation_works_through_bridge(self) -> None:
        m = SkillManifest(
            name="s", description="d",
            tools=[{"name": "bridge_tool", "description": "x"}],
            handler=lambda n, args, ctx: "adapted",
        )
        a = Agent()
        for t in adapt_skill_manifest(m):
            a.tool_registry.register(t)
        assert a.tool_router.route(ToolRequest("bridge_tool")).output == "adapted"


# ── Behavioural freeze ──────────────────────────────────────────────────


class _SpyRouter(ToolRouter):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(registry)
        self.calls = 0

    def route(self, request: ToolRequest) -> ToolResult:  # pragma: no cover - must never run
        self.calls += 1
        return super().route(request)


class TestBehaviouralFreeze:
    def test_handle_request_unchanged(self) -> None:
        a = Agent()
        snap = a.handle_request("fix the wifi")
        ref = Agent().handle_request("fix the wifi")
        assert snap.session_id == ref.session_id
        assert snap.ready_task_ids == ref.ready_task_ids

    def test_execute_request_chain_does_not_call_router(self) -> None:
        spy = _SpyRouter(ToolRegistry())
        a = Agent(tool_router=spy)
        a.handle_request("fix the wifi")
        a.execute_request("fix the wifi")
        a.execute_request_with_skill_check("fix the wifi")
        a.execute_request_with_dispatch_decision("fix the wifi")
        a.execute_request_with_skill_execution("fix the wifi")
        assert spy.calls == 0

    def test_execute_request_does_not_touch_tool_registry(self) -> None:
        a = Agent()
        a.execute_request_with_skill_execution("fix the wifi")
        assert a.tool_registry.count() == 0

    def test_legacy_skill_dispatch_still_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dispatched: list[str] = []
        import core.skill_dispatch as skill_dispatch_module
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda name: True)
        monkeypatch.setattr(
            agent_module, "skill_dispatch",
            lambda name, args, ctx=None: dispatched.append(name) or "ok",
        )
        spy = _SpyRouter(ToolRegistry())
        a = Agent(tool_router=spy)
        _, decisions = a.execute_request_with_skill_execution("fix the wifi")
        assert dispatched  # legacy path invoked
        assert all(d.would_dispatch for d in decisions)
        assert spy.calls == 0  # router untouched

    def test_router_source_not_referenced_by_request_methods(self) -> None:
        tree = _agent_tree()
        for node in ast.walk(tree):
            # v8.16 execute_request_with_tool_routing and v8.17+
            # execute_request_with_tool_dispatch are the only opt-in
            # methods allowed to consult the tool registry/router.
            if isinstance(node, ast.FunctionDef) and node.name not in (
                "__init__", "execute_request_with_tool_routing",
                "execute_request_with_tool_dispatch",
                "execute_projection_with_tool_dispatch",  # v8.22
                "execute_projection_with_run_status",  # v8.23
                "_run_projected_pipeline",  # v8.25 helper shared by v8.23/v8.25
                "_run_tool_dispatch_chain",  # v8.29 helper shared by v8.19/v8.20
                "_prepare_resume",  # v8.32 resume validation: rebuilds decisions (no routing)
                "_route_with_transient_retry",  # v8.33 bounded retry around ToolRouter.route
            ):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute):
                        # The stored refs are read only by their own property
                        # accessors; no request-handling method touches them
                        # or calls ``route``.
                        if sub.attr == "_tool_router":
                            assert node.name == "tool_router", node.name
                        if sub.attr == "_tool_registry":
                            assert node.name == "tool_registry", node.name
                        assert sub.attr != "route", node.name

    def test_construction_does_not_mutate_skill_globals(self) -> None:
        before = _skill_globals()
        Agent()
        Agent(tool_registry=ToolRegistry())
        assert _skill_globals() == before

    def test_no_automatic_skill_discovery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(skill_registry, "discover_skills", lambda *a, **k: called.append("d"))
        monkeypatch.setattr(skill_registry, "register_skill", lambda m: called.append("r"))
        Agent()
        assert called == []

    def test_no_automatic_skill_adaptation(self) -> None:
        # Registered legacy skills are NOT mirrored into the tool registry.
        a = Agent()
        assert a.tool_registry.count() == 0
        for name in [s["name"] for s in skill_registry.list_skills()]:
            assert not a.tool_registry.has(name)

    def test_snapshot_unchanged(self) -> None:
        a = Agent()
        snap = a.snapshot()
        assert set(snap) == {
            "history", "context", "knowledge", "learning",
            "memory_index_count", "reflection", "reasoning",
        }
        assert "tool_registry" not in snap and "tool_router" not in snap

    def test_clear_all_does_not_touch_tool_registry(self) -> None:
        a = Agent()
        t = StaticMockTool(name="keep")
        a.tool_registry.register(t)
        a.clear_all()
        assert a.tool_registry.get("keep") is t
        assert a.tool_registry.count() == 1

    def test_legacy_defaults_intact(self) -> None:
        a = Agent()
        assert isinstance(a.planning, LegacyPlanningEngine)
        assert isinstance(a.execution_orchestrator, ExecutionOrchestrator)
        assert isinstance(a.execution_pipeline, ExecutionPipeline)
        assert a.execution_orchestrator.snapshot() == ()
        assert a.execution_pipeline.ready_task_ids() == ()

    def test_existing_construction_patterns_compatible(self) -> None:
        Agent()
        Agent(planning=LegacyPlanningEngine())
        Agent(execution_orchestrator=ExecutionOrchestrator([]))
        Agent(tool_registry=ToolRegistry(), planning=LegacyPlanningEngine())


# ── Public API / architecture ───────────────────────────────────────────


class TestPublicAPI:
    def test_all_unchanged(self) -> None:
        assert set(agent_module.__all__) == EXPECTED_ALL
        for n in ("ToolRegistry", "ToolRouter", "ToolNotFoundError"):
            assert n not in agent_module.__all__

    def test_agent_imports_exactly_two_new_modules(self) -> None:
        imported = {
            (node.module, n.name)
            for node in ast.walk(_agent_tree())
            if isinstance(node, ast.ImportFrom) and node.module
            for n in node.names
        }
        assert ("core.tool_registry", "ToolRegistry") in imported
        assert ("core.tool_router", "ToolRouter") in imported
        modules = {m for m, _ in imported}
        # core.tool_interface is admitted since v8.16 (ToolRequest/ToolResult
        # for the opt-in routing method); the adapter stays forbidden.
        assert ("core.tool_interface", "ToolRequest") in imported
        for forbidden in (
            "core.skill_tool_adapter",
            "core.ai_provider_registry", "core.default_ai_provider_registry",
            "core.claude_provider", "core.openai_provider",
            "core.gemini_provider", "core.ollama_provider",
        ):
            assert forbidden not in modules, forbidden

    def test_skill_registry_import_unchanged(self) -> None:
        # The pre-existing legacy import stays exactly as it was; nothing
        # new is imported from skill_registry for the bridge.
        for node in ast.walk(_agent_tree()):
            if isinstance(node, ast.ImportFrom) and node.module == "core.skill_registry":
                assert sorted(n.name for n in node.names) == ["dispatch", "is_registered"]

    def test_tool_modules_do_not_import_agent(self) -> None:
        for rel in ("tool_registry.py", "tool_router.py", "tool_interface.py", "skill_tool_adapter.py"):
            with open(os.path.join(CORE_DIR, rel), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("core.agent"), (rel, node.module)
                elif isinstance(node, ast.Import):
                    for n in node.names:
                        assert not n.name.startswith("core.agent"), (rel, n.name)

    def test_router_does_not_import_skill_registry(self) -> None:
        with open(os.path.join(CORE_DIR, "tool_router.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "skill" not in node.module, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert "skill" not in n.name, n.name

    def test_no_module_level_singleton(self) -> None:
        for node in _agent_tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else [node.target.id] if isinstance(node.target, ast.Name) else []
                )
                assert targets == ["__all__"], targets
        for name, value in vars(agent_module).items():
            assert not isinstance(value, (ToolRegistry, ToolRouter)), name

    def test_legacy_modules_untouched_by_bridge(self) -> None:
        for rel in LEGACY_EXECUTION_FILES:
            with open(os.path.join(CORE_DIR, rel), encoding="utf-8") as f:
                src = f.read()
            for token in ("tool_registry", "tool_router", "ToolRegistry", "ToolRouter"):
                assert token not in src, (rel, token)
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            assert "tool_router" not in f.read()

    def test_no_circular_import_in_fresh_interpreter(self) -> None:
        code = (
            "import core.tool_router, core.tool_registry, core.tool_interface, "
            "core.skill_tool_adapter; import core.agent; "
            "a = core.agent.Agent(); print(a.tool_router.registry is a.tool_registry)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT,
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "True"

    def test_concurrent_construction_independent(self) -> None:
        agents: list[Agent] = []
        lock = threading.Lock()

        def build() -> None:
            a = Agent()
            with lock:
                agents.append(a)

        threads = [threading.Thread(target=build) for _ in range(16)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert len(agents) == 16
        assert len({id(a.tool_registry) for a in agents}) == 16
        assert all(a.tool_router.registry is a.tool_registry for a in agents)
