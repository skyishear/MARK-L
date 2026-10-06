"""Tests for v8.20 Tool-chain writeback
(``Agent.execute_request_with_tool_dispatch_writeback``)."""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.agent as agent_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
from core import problem_solver
from core.agent import Agent
from core.execution_result import ExecutionResult
from core.tool_dispatch import ToolDispatchDecision
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")
METHOD = "execute_request_with_tool_dispatch_writeback"


def _method_node() -> ast.FunctionDef:
    with open(AGENT_FILE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == METHOD:
            return node
    raise AssertionError("method not found")


class Desc:
    def __init__(self, task_id: str, problem: str) -> None:
        self.task_id = task_id
        self.work_item = type("W", (), {"problem": problem})()


def force_ready(monkeypatch: pytest.MonkeyPatch, agent: Agent, *problems: str) -> None:
    descs = tuple(Desc(f"t{i}", pr) for i, pr in enumerate(problems, 1))
    monkeypatch.setattr(
        agent, "coordinate_execution",
        lambda session: type("Coord", (), {"ready_descriptors": descs})(),
    )


class Failing:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fails"

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise RuntimeError("simulated tool failure")


@pytest.fixture
def stub_remember(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Mirror the legacy writeback tests: observe ``remember`` without a
    real write."""
    writes: list[tuple] = []

    def fake(*args, **kwargs):
        writes.append((args, kwargs))
        return "stub-id"

    monkeypatch.setattr(problem_solver, "remember", fake)
    return writes


def agent_with_tool(name: str = "fix the wifi", output: str = "fixed") -> Agent:
    a = Agent()
    a.tool_registry.register(StaticMockTool(name=name, output=output))
    return a


# ── Contract ────────────────────────────────────────────────────────────


class TestContract:
    def test_signature_mirrors_chain(self) -> None:
        new = inspect.signature(getattr(Agent, METHOD))
        base = inspect.signature(Agent.execute_request_with_tool_dispatch)
        assert list(new.parameters) == list(base.parameters)
        assert new.return_annotation == base.return_annotation

    def test_returns_v8_19_contract_unchanged(self) -> None:
        a = agent_with_tool()
        result, decisions, results = a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert isinstance(result, ExecutionResult)
        assert all(isinstance(d, ToolDispatchDecision) for d in decisions)
        assert results == (ToolResult("fix the wifi", "fixed"),)

    def test_same_output_as_plain_dispatch(self) -> None:
        a, b = agent_with_tool(), agent_with_tool()
        r1, d1, t1 = a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        r2, d2, t2 = b.execute_request_with_tool_dispatch("fix the wifi")
        assert (r1.session_id, d1, t1) == (r2.session_id, d2, t2)

    def test_runs_the_v8_19_chain_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # v8.29: v8.20 runs the v8.19 body (the shared ``_run_tool_dispatch_chain``)
        # directly instead of through the public v8.19 method, so the failed
        # stage is observable. Pinned: exactly one chain run per call, and
        # results identical to the v8.19 method (checked just above).
        a = agent_with_tool()
        calls: list[str] = []
        original = a._run_tool_dispatch_chain  # noqa: SLF001

        def spy(goal, *, project=None, metadata=None, routing=None):
            calls.append(goal)
            return original(goal, project=project, metadata=metadata, routing=routing)

        monkeypatch.setattr(a, "_run_tool_dispatch_chain", spy)
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert calls == ["fix the wifi"]


# ── Memory writeback (v5.2 mirror) ──────────────────────────────────────


class TestMemoryWriteback:
    def test_exactly_one_write_per_dispatch(self, stub_remember: list) -> None:
        agent_with_tool().execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(stub_remember) == 1

    def test_write_content_mirrors_legacy_with_tool_cause(self, stub_remember: list) -> None:
        agent_with_tool().execute_request_with_tool_dispatch_writeback("fix the wifi", project="p")
        args, kwargs = stub_remember[0]
        value = kwargs.get("value") or (args[2] if len(args) > 2 else "")
        assert "SOLVED" in value
        assert "problem: fix the wifi" in value
        assert "cause: controlled_tool_dispatch" in value
        assert "solution: fix the wifi" in value
        assert kwargs.get("project", args[3] if len(args) > 3 else None) == "p"

    def test_skipped_performs_no_write(self, stub_remember: list) -> None:
        Agent().execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert stub_remember == []

    def test_failed_performs_one_failure_write(self, stub_remember: list) -> None:
        # v8.29 (owner-authorized): a failed attempt writes exactly one structured
        # failure record per layer and still no success record.
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi"))
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(stub_remember) == 1 and stub_remember[0][0][2].startswith("FAILED |")

    def test_write_lands_in_agent_memory_engine(self) -> None:
        a = agent_with_tool()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.memory_engine.count() == 1

    def test_one_write_per_dispatched_decision(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one"))
        a.tool_registry.register(StaticMockTool(name="three"))
        force_ready(monkeypatch, a, "one", "two", "three")
        a.execute_request_with_tool_dispatch_writeback("g")
        assert len(stub_remember) == 2


# ── Reflection (v5.3 mirror) ────────────────────────────────────────────


class TestReflection:
    def test_exactly_one_reflection_per_dispatch(self) -> None:
        a = agent_with_tool()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.reflection_engine.count() == 1

    def test_reflection_content(self) -> None:
        a = agent_with_tool(output="signal restored")
        _, decisions, _ = a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        (rec,) = a.reflection.get_all()
        assert rec.subject == decisions[0].task_id
        assert rec.what_worked == "controlled_tool_dispatch:fix the wifi"
        assert "Tool 'fix the wifi' executed successfully" in rec.completion_summary
        assert "signal restored" in rec.completion_summary
        assert rec.confidence_level == 1.0

    def test_skipped_creates_no_reflection(self) -> None:
        a = Agent()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.reflection_engine.count() == 0

    def test_failed_creates_one_failure_reflection(self) -> None:
        # v8.29 (owner-authorized): a failed attempt writes exactly one structured
        # failure record per layer and still no success record.
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi"))
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        (ref,) = a.reflection.get_all()
        assert ref.what_failed and not ref.what_worked and ref.confidence_level == 0.0

    def test_reflection_after_memory_writeback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []
        a = agent_with_tool()
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("memory") or "id")
        orig = a.reflection.add_reflection
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("reflection") or orig(**k))
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert order == ["memory", "reflection"]


# ── Learning (v5.4 mirror) ──────────────────────────────────────────────


class TestLearning:
    def test_exactly_one_learning_record_per_dispatch(self) -> None:
        a = agent_with_tool()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(a.learning.get_all()) == 1

    def test_learning_content_includes_tool_output(self) -> None:
        a = agent_with_tool(output="signal restored")
        _, decisions, _ = a.execute_request_with_tool_dispatch_writeback("fix the wifi", project="p")
        (rec,) = a.learning.get_all()
        assert rec.subject == "fix the wifi"
        assert "controlled tool dispatch" in rec.detail
        assert rec.metadata == {
            "task_id": decisions[0].task_id, "project": "p", "output": "signal restored",
        }

    def test_skipped_produces_no_learning(self) -> None:
        a = Agent()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.learning.get_all() == []

    def test_failed_produces_one_failed_pattern(self) -> None:
        # v8.29 (owner-authorized): a failed attempt writes exactly one structured
        # failure record per layer and still no success record.
        a = Agent()
        a.tool_registry.register(Failing("fix the wifi"))
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert [r.category for r in a.learning.get_all()] == ["failed_pattern"]

    def test_learning_after_reflection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []
        a = agent_with_tool()
        orig_r = a.reflection.add_reflection
        orig_l = a.learning.record_successful_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("reflection") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_successful_pattern", lambda **k: order.append("learning") or orig_l(**k))
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert order == ["reflection", "learning"]


# ── Layering / ordering / pairing ───────────────────────────────────────


class TestLayering:
    def test_layer_order_memory_then_reflection_then_learning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one"))
        a.tool_registry.register(StaticMockTool(name="two"))
        force_ready(monkeypatch, a, "one", "two")
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("M") or "id")
        orig_r, orig_l = a.reflection.add_reflection, a.learning.record_successful_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("R") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_successful_pattern", lambda **k: order.append("L") or orig_l(**k))
        a.execute_request_with_tool_dispatch_writeback("g")
        # All memory writes, then all reflections, then all learning — as in v5.2→v5.4 layering.
        assert order == ["M", "M", "R", "R", "L", "L"]

    def test_results_paired_with_dispatched_decisions_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one", output="O1"))
        a.tool_registry.register(StaticMockTool(name="three", output="O3"))
        force_ready(monkeypatch, a, "one", "two", "three")
        _, decisions, results = a.execute_request_with_tool_dispatch_writeback("g")
        recs = a.learning.get_all()
        assert [r.subject for r in recs] == ["one", "three"]
        assert [r.metadata["output"] for r in recs] == ["O1", "O3"]
        assert [r.metadata["task_id"] for r in recs] == ["t1", "t3"]
        assert [x.output for x in results] == ["O1", "O3"]

    def test_writes_happen_after_all_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []

        class Recording:
            def __init__(self, name: str) -> None:
                self.name = name
                self.description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                order.append(f"route:{request.tool_name}")
                return ToolResult(request.tool_name, "ok")

        a = Agent()
        a.tool_registry.register(Recording("one"))
        a.tool_registry.register(Recording("two"))
        force_ready(monkeypatch, a, "one", "two")
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("memory") or "id")
        a.execute_request_with_tool_dispatch_writeback("g")
        assert order == ["route:one", "route:two", "memory", "memory"]

    def test_failure_mid_chain_writes_only_the_failure(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        # v8.29 (owner-authorized): a failed attempt writes exactly one structured
        # failure record per layer and still no success record.
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="one"))
        a.tool_registry.register(Failing("two"))
        force_ready(monkeypatch, a, "one", "two")
        with pytest.raises(RuntimeError):
            a.execute_request_with_tool_dispatch_writeback("g")
        assert [m[0][2] for m in stub_remember] == [
            "FAILED | problem: two | cause: controlled_tool_dispatch_failure | solution: two"
            " | outcome: failed:RuntimeError"]
        assert a.reflection_engine.count() == 1
        assert [(r.category, r.subject) for r in a.learning.get_all()] == [("failed_pattern", "two")]

    def test_tool_error_propagates_unchanged(self) -> None:
        class F:
            name = "fix the wifi"
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError("tool failed")

        a = Agent()
        a.tool_registry.register(F())
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")

    def test_repeated_calls_accumulate_records(self) -> None:
        a = agent_with_tool()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.reflection_engine.count() == 2
        # LearningManager.observe() de-duplicates the same subject into one
        # record with an updated observation (existing legacy behaviour).
        assert len(a.learning.get_all()) == 1
        assert a.memory_engine.count() >= 1

    def test_zero_ready_descriptors_write_nothing(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        a = agent_with_tool()
        force_ready(monkeypatch, a)
        _, decisions, results = a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert decisions == () and results == ()
        assert stub_remember == [] and a.reflection_engine.count() == 0


# ── Legacy isolation ────────────────────────────────────────────────────


class TestLegacyIsolation:
    def test_no_legacy_skill_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or False)
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(agent_module, "gather_context", lambda **k: called.append("gather") or {})
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        agent_with_tool().execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert called == []

    def test_legacy_writeback_chain_unchanged(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: n == "fix the wifi")
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a = Agent()
        a.execute_request_with_learning("fix the wifi")
        assert len(stub_remember) == 1
        args, kwargs = stub_remember[0]
        value = kwargs.get("value") or args[2]
        assert "cause: controlled_skill_execution" in value
        assert a.reflection_engine.count() == 1
        assert len(a.learning.get_all()) == 1
        assert a.learning.get_all()[0].metadata == {"task_id": a.learning.get_all()[0].metadata["task_id"], "project": None}

    def test_legacy_chain_does_not_call_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class SpyRouter(ToolRouter):
            def __init__(self, r: ToolRegistry) -> None:
                super().__init__(r)
                self.calls = 0

            def route(self, request: ToolRequest) -> ToolResult:
                self.calls += 1
                return super().route(request)

        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        router = SpyRouter(ToolRegistry())
        a = Agent(tool_router=router)
        a.execute_request_with_learning("fix the wifi")
        assert router.calls == 0

    def test_skill_globals_unchanged(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        agent_with_tool().execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001

    def test_tool_registry_not_modified(self) -> None:
        a = agent_with_tool()
        before = a.tool_registry.names()
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert a.tool_registry.names() == before

    def test_plain_dispatch_still_writes_nothing(self) -> None:
        a = agent_with_tool()
        a.execute_request_with_tool_dispatch("fix the wifi")
        assert a.memory_engine.count() == 0
        assert a.reflection_engine.count() == 0
        assert a.learning.get_all() == []


# ── Architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_method_uses_only_existing_write_apis(self) -> None:
        node = _method_node()
        calls = set()
        for c in ast.walk(node):
            if isinstance(c, ast.Call):
                calls.add(c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None))
        # v8.29: the v8.19 body is run through the shared helper, and the
        # shared failure writer is the only other new call.
        assert {"_run_tool_dispatch_chain", "_record_failure_outcome", "record_problem_outcome",
                "add_reflection", "record_successful_pattern"} <= calls
        for forbidden in ("route", "get", "register", "skill_dispatch", "build_dispatch_decision",
                          "gather_context", "remember", "ToolRequest"):
            assert forbidden not in calls, forbidden
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert not attrs & {"_tool_router", "_tool_registry", "tool_router", "tool_registry"}
        # v8.29: exactly one handler -- around the chain only -- performing the
        # failure writeback and re-raising the original exception unchanged.
        (h,) = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
        assert isinstance(h.type, ast.Name) and h.type.id == "BaseException"
        raises = [n for n in ast.walk(h) if isinstance(n, ast.Raise)]
        assert len(raises) == 1 and raises[0].exc is None
        assert {getattr(c.func, "attr", None) for c in ast.walk(h) if isinstance(c, ast.Call)} == {
            "_record_failure_outcome"}
        (t,) = [n for n in ast.walk(node) if isinstance(n, ast.Try)]
        assert {getattr(c.func, "attr", None) for s in t.body for c in ast.walk(s)
                if isinstance(c, ast.Call)} == {"_run_tool_dispatch_chain"}
        assert not t.finalbody and not t.orelse

    def test_no_new_imports_in_agent(self) -> None:
        with open(AGENT_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert modules == {
            "__future__", "datetime", "types", "typing",
            "core.agent.context_manager", "core.agent.history_manager",
            "core.agent.knowledge_manager", "core.agent.learning_manager",
            "core.agent.memory_index_manager", "core.agent.reasoning_manager",
            "core.agent.reflection_manager", "core.ai_provider", "core.ai_service",
            "core.conversation_history", "core.memory_engine", "core.problem_solver",
            "core.reflection_engine", "core.execution_coordinator",
            "core.execution_orchestrator", "core.execution_pipeline",
            "core.execution_result", "core.execution_session", "core.planner",
            "core.planner_execution_orchestrator_adapter", "core.skill_dispatch",
            "core.skill_registry", "core.execution_planner", "core.goal_manager",
            "core.pipeline_engine", "core.pipeline_run", "core.planning_engine",
            "core.task_graph", "core.tool_dispatch", "core.tool_interface",
            "core.plan_projection", "core.stage_dispatch", "core.lifecycle_reflection",
            "core.step_lifecycle",
            "core.execution_failure",
            "core.failure_taxonomy",
            "core.tool_catalog",
            "core.memory_context",
            "core.tool_registry", "core.tool_router",
            "core.tool_runtime",  # v8.39
            "core.live_tools",  # v8.41
            "core.production_memory",  # v8.42
            "core.live_run_record",  # v8.43
        }

    def test_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "ToolDispatchDecision" not in agent_module.__all__

    def test_execute_request_family_complete(self) -> None:
        names = [n for n in dir(Agent) if n.startswith("execute_request")]
        assert METHOD in names
        for legacy in (
            "execute_request", "execute_request_with_skill_check",
            "execute_request_with_dispatch_decision", "execute_request_with_skill_execution",
            "execute_request_with_memory_writeback", "execute_request_with_reflection",
            "execute_request_with_learning", "execute_request_with_tool_routing",
            "execute_request_with_tool_dispatch",
        ):
            assert legacy in names
