"""Tests for the Agent tool-dispatch chain (v8.17 decisions, v8.18 execution)."""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.agent as agent_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
from core.agent import Agent
from core.execution_result import ExecutionResult
from core.tool_dispatch import ToolDispatchDecision
from core.tool_interface import StaticMockTool, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")
METHOD = "execute_request_with_tool_dispatch"


def _method_node(name: str = METHOD) -> ast.FunctionDef:
    with open(AGENT_FILE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("method not found")


def _skill_globals() -> tuple[dict, dict]:
    return dict(skill_registry._skills), dict(skill_registry._tool_index)  # noqa: SLF001


class SpyRouter(ToolRouter):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(registry)
        self.requests: list[ToolRequest] = []

    def route(self, request: ToolRequest) -> ToolResult:
        self.requests.append(request)
        return super().route(request)


class TestSignatureAndShape:
    def test_signature_mirrors_legacy_chain(self) -> None:
        new = inspect.signature(getattr(Agent, METHOD))
        legacy = inspect.signature(Agent.execute_request_with_skill_execution)
        assert list(new.parameters) == list(legacy.parameters) == ["self", "goal", "project", "metadata"]
        assert new.parameters["project"].kind is inspect.Parameter.KEYWORD_ONLY
        assert new.parameters["metadata"].default is None

    def test_returns_three_tuple(self) -> None:
        out = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert isinstance(out, tuple) and len(out) == 3
        result, decisions, results = out
        assert isinstance(result, ExecutionResult)
        assert isinstance(decisions, tuple)
        assert isinstance(results, tuple)


class TestDecisions:
    def test_one_decision_per_ready_descriptor(self) -> None:
        a = Agent()
        plan = a.planning.plan("step one then step two")
        ready = a.coordinate_execution(a.create_execution_session(plan)).ready_descriptors
        _, decisions, _ = a.execute_request_with_tool_dispatch("step one then step two")
        assert len(decisions) == len(ready) == 1
        assert decisions[0].task_id == ready[0].task_id
        assert decisions[0].tool_name == ready[0].work_item.problem

    def test_decision_type(self) -> None:
        _, decisions, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert all(isinstance(d, ToolDispatchDecision) for d in decisions)

    def test_unregistered_tool_skips(self) -> None:
        _, decisions, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].tool_name == "fix the wifi"
        assert decisions[0].would_dispatch is False
        assert decisions[0].action == "skip"

    def test_registered_tool_would_dispatch(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        _, decisions, _ = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].would_dispatch is True
        assert decisions[0].action == "dispatch"

    def test_gated_by_agent_tool_registry(self) -> None:
        reg = ToolRegistry()
        reg.register(StaticMockTool(name="fix the wifi"))
        a = Agent(tool_registry=reg)
        _, decisions, _ = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].would_dispatch is True

    def test_not_gated_by_skill_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(skill_registry, "is_registered", lambda n: True)
        _, decisions, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].would_dispatch is False

    def test_project_in_decision_context(self) -> None:
        _, decisions, _ = Agent().execute_request_with_tool_dispatch("fix the wifi", project="mark_l")
        assert dict(decisions[0].context) == {"project": "mark_l"}

    def test_none_project_in_context(self) -> None:
        _, decisions, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert dict(decisions[0].context) == {"project": None}

    def test_deterministic_for_same_goal(self) -> None:
        a, b = Agent(), Agent()
        _, d1, _ = a.execute_request_with_tool_dispatch("fix the wifi")
        _, d2, _ = b.execute_request_with_tool_dispatch("fix the wifi")
        assert d1 == d2


class TestExecutionResultConsistency:
    def test_result_matches_legacy_chain(self) -> None:
        legacy_result, _ = Agent().execute_request_with_skill_execution("fix the wifi")
        tool_result, _, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert tool_result.session_id == legacy_result.session_id
        assert tool_result.plan_id == legacy_result.plan_id
        assert tool_result.progress == legacy_result.progress
        assert tool_result.success == legacy_result.success

    def test_result_from_same_session_type(self) -> None:
        result, _, _ = Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert type(result).__name__ == "ExecutionResult"
        assert result.progress.total == 1


class SpyTool:
    def __init__(self, name: str, output: str = "spied") -> None:
        self.name = name
        self.description = "spy"
        self.received: list[ToolRequest] = []
        self.result = ToolResult(name, output)

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.received.append(request)
        return self.result


class FailingTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fails"
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        raise RuntimeError(f"simulated tool failure: {request.tool_name}")


class Desc:
    """Minimal stand-in for a coordinator ready descriptor."""

    def __init__(self, task_id: str, problem: str) -> None:
        self.task_id = task_id
        self.work_item = type("W", (), {"problem": problem})()


def agent_with(*tools: object) -> tuple[Agent, SpyRouter]:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    router = SpyRouter(reg)
    return Agent(tool_registry=reg, tool_router=router), router


def force_ready(monkeypatch: pytest.MonkeyPatch, agent: Agent, *problems: str) -> None:
    """Stub the coordinator step to expose several ready descriptors while
    keeping planning/session/decision/router logic real."""
    descs = tuple(Desc(f"t{i}", pr) for i, pr in enumerate(problems, 1))
    coord = type("Coord", (), {"ready_descriptors": descs})()
    monkeypatch.setattr(agent, "coordinate_execution", lambda session: coord)


class TestExecutionChain:
    def test_registered_tool_dispatches_through_router(self) -> None:
        spy = SpyTool("fix the wifi")
        a, router = agent_with(spy)
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].would_dispatch is True
        assert len(router.requests) == 1
        assert len(spy.received) == 1
        assert results == (spy.result,)

    def test_unregistered_tool_skips_router(self) -> None:
        a, router = agent_with()
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "skip"
        assert router.requests == []
        assert results == ()

    def test_exact_tool_request_arguments(self) -> None:
        spy = SpyTool("fix the wifi")
        a, router = agent_with(spy)
        a.execute_request_with_tool_dispatch("fix the wifi", project="p")
        req = router.requests[0]
        assert isinstance(req, ToolRequest)
        assert req.tool_name == "fix the wifi"
        assert dict(req.arguments) == {"problem": "fix the wifi"}
        assert "project" not in req.arguments  # legacy ctx is not smuggled in
        assert spy.received[0] is req

    def test_exact_tool_result_identity(self) -> None:
        spy = SpyTool("fix the wifi")
        a, _ = agent_with(spy)
        _, _, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert results[0] is spy.result

    def test_result_from_router_not_reconstructed(self) -> None:
        a = Agent()
        mock = StaticMockTool(name="fix the wifi", output="ok")
        a.tool_registry.register(mock)
        _, _, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert results == (ToolResult("fix the wifi", "ok"),)
        assert mock.call_count == 1

    def test_single_ready_descriptor_from_real_planner(self) -> None:
        a, router = agent_with(SpyTool("alpha", "A"), SpyTool("beta", "B"))
        _, decisions, results = a.execute_request_with_tool_dispatch("alpha")
        assert [d.tool_name for d in decisions] == ["alpha"]
        assert [r.output for r in results] == ["A"]
        assert [r.tool_name for r in router.requests] == ["alpha"]

    def test_multiple_ready_descriptors_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, router = agent_with(SpyTool("one", "1"), SpyTool("two", "2"), SpyTool("three", "3"))
        force_ready(monkeypatch, a, "one", "two", "three")
        _, decisions, results = a.execute_request_with_tool_dispatch("anything")
        assert [d.task_id for d in decisions] == ["t1", "t2", "t3"]
        assert [r.output for r in results] == ["1", "2", "3"]
        assert [r.tool_name for r in router.requests] == ["one", "two", "three"]

    def test_mixed_skip_dispatch_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, router = agent_with(SpyTool("one", "1"), SpyTool("three", "3"))
        force_ready(monkeypatch, a, "one", "two", "three")
        _, decisions, results = a.execute_request_with_tool_dispatch("anything")
        assert [d.action for d in decisions] == ["dispatch", "skip", "dispatch"]
        assert [r.output for r in results] == ["1", "3"]
        assert [r.tool_name for r in router.requests] == ["one", "three"]

    def test_router_exception_propagates_unchanged(self) -> None:
        failing = FailingTool("fix the wifi")
        a, _ = agent_with(failing)
        with pytest.raises(RuntimeError, match="simulated tool failure: fix the wifi") as info:
            a.execute_request_with_tool_dispatch("fix the wifi")
        assert type(info.value) is RuntimeError
        assert failing.calls == 1

    def test_stops_after_first_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        failing = FailingTool("one")
        later = SpyTool("two")
        a, router = agent_with(failing, later)
        force_ready(monkeypatch, a, "one", "two")
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch("anything")
        assert failing.calls == 1
        assert later.received == []
        assert [r.tool_name for r in router.requests] == ["one"]

    def test_failure_after_success_discards_partial_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = SpyTool("one", "1")
        failing = FailingTool("two")
        a, _ = agent_with(first, failing)
        force_ready(monkeypatch, a, "one", "two")
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch("anything")
        assert len(first.received) == 1  # ran, but no partial tuple is returned

    def test_router_used_not_registry_directly(self) -> None:
        # v8.29: the v8.19 body lives in ``_run_tool_dispatch_chain``.
        node = _method_node("_run_tool_dispatch_chain")
        attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        assert "route" in attrs
        assert not attrs & {"get", "invoke", "list_tools", "register", "has"}

    def test_registry_not_modified_by_routing(self) -> None:
        a, _ = agent_with(SpyTool("fix the wifi"))
        before = (a.tool_registry.names(), a.tool_registry.list_tools())
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert (a.tool_registry.names(), a.tool_registry.list_tools()) == before

    def test_decisions_and_request_not_mutated(self) -> None:
        spy = SpyTool("fix the wifi")
        a, router = agent_with(spy)
        _, decisions, _ = a.execute_request_with_tool_dispatch("fix the wifi", project="p")
        assert decisions[0].action == "dispatch"
        assert dict(decisions[0].context) == {"project": "p"}
        assert dict(router.requests[0].arguments) == {"problem": "fix the wifi"}

    def test_injected_router_only_gate_is_agent_registry(self) -> None:
        own = ToolRegistry()
        own.register(SpyTool("fix the wifi"))
        router = SpyRouter(own)
        a = Agent(tool_router=router)  # Agent registry fresh and empty
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi")
        assert decisions[0].action == "skip"
        assert router.requests == []
        assert results == ()

    def test_repeated_calls_isolated(self) -> None:
        a, _ = agent_with(SpyTool("fix the wifi"))
        _, _, r1 = a.execute_request_with_tool_dispatch("fix the wifi")
        _, _, r2 = a.execute_request_with_tool_dispatch("fix the wifi")
        assert r1 == r2 and r1 is not r2

    def test_concurrent_agents_independent(self) -> None:
        import threading

        outputs: dict[int, list[str]] = {}
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            try:
                a = Agent()
                a.tool_registry.register(StaticMockTool(name="fix the wifi", output=f"o{i}"))
                outs = [a.execute_request_with_tool_dispatch("fix the wifi")[2][0].output for _ in range(10)]
                with lock:
                    outputs[i] = outs
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert not errors
        assert all(outputs[i] == [f"o{i}"] * 10 for i in range(6))

    def test_adapted_skill_end_to_end(self) -> None:
        from core.skill_registry import SkillManifest
        from core.skill_tool_adapter import adapt_skill_manifest

        calls: list[tuple] = []
        m = SkillManifest(
            name="wifi", description="d",
            tools=[{"name": "fix the wifi", "description": "x"}],
            handler=lambda n, args, ctx: calls.append((n, args, dict(ctx))) or "fixed",
        )
        a = Agent()
        for t in adapt_skill_manifest(m, context={"ui": "UI"}):
            a.tool_registry.register(t)
        _, decisions, results = a.execute_request_with_tool_dispatch("fix the wifi", project="p")
        assert decisions[0].action == "dispatch"
        assert results == (ToolResult("fix the wifi", "fixed"),)
        assert calls == [("fix the wifi", {"problem": "fix the wifi"}, {"ui": "UI"})]


class TestLegacyIsolation:
    def test_no_skill_registry_or_dispatch_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or False)
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(agent_module, "gather_context", lambda **k: called.append("gather") or {})
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert called == []

    def test_legacy_chain_does_not_call_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        router = SpyRouter(ToolRegistry())
        a = Agent(tool_router=router)
        a.execute_request_with_skill_execution("fix the wifi")
        a.execute_request_with_learning("fix the wifi")
        assert router.requests == []

    def test_legacy_chain_unchanged(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch("fix the wifi")
        result, decisions = a.execute_request_with_skill_execution("fix the wifi")
        ref_result, ref_decisions = Agent().execute_request_with_skill_execution("fix the wifi")
        assert result.session_id == ref_result.session_id
        assert [d.would_dispatch for d in decisions] == [d.would_dispatch for d in ref_decisions]

    def test_skill_globals_unchanged(self) -> None:
        before = _skill_globals()
        Agent().execute_request_with_tool_dispatch("fix the wifi")
        assert _skill_globals() == before

    def test_registry_not_modified(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        before = a.tool_registry.names()
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert a.tool_registry.names() == before

    def test_no_memory_writeback(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert a.memory_engine.count() == 0
        assert a.reflection_engine.count() == 0
        assert a.snapshot()["learning"] == []


class TestArchitecture:
    def test_method_uses_only_sanctioned_calls(self) -> None:
        # v8.29: the public method only delegates to the extracted body.
        public = _method_node()
        assert {getattr(c.func, "attr", None) for c in ast.walk(public)
                if isinstance(c, ast.Call)} == {"_run_tool_dispatch_chain"}
        node = _method_node("_run_tool_dispatch_chain")
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        for forbidden in (
            "skill_dispatch", "is_registered", "build_dispatch_decision",
            "gather_context", "adapt_skill_manifest", "record_problem_outcome",
        ):
            assert forbidden not in names, forbidden
        assert "build_tool_dispatch_decision" in names
        assert "build_result_from_session" in names
        for n in ast.walk(node):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))

    def test_all_unchanged(self) -> None:
        assert "ToolDispatchDecision" not in agent_module.__all__
        assert len(agent_module.__all__) == 16
