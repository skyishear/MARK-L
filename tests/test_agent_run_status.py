"""Tests for v8.23 Pipeline Run Status Recording
(``Agent.execute_projection_with_run_status``)."""

from __future__ import annotations

import ast
import inspect
import os

import pytest

import core.agent as agent_module
import core.skill_dispatch as skill_dispatch_module
import core.skill_registry as skill_registry
from core.agent import Agent
from core.pipeline_engine import PipelineEngine
from core.pipeline_run import PipelineRun, PipelineRunManager, PipelineRunStatus
from core.plan_projection import PlanProjection
from core.planner import InvalidGoalError
from core.tool_dispatch import ToolDispatchDecision
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")
METHOD = "execute_projection_with_run_status"
S = PipelineRunStatus


def _method_node(name: str = METHOD) -> ast.FunctionDef:
    with open(AGENT_FILE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("method not found")


# v8.25 extracted the run body into this shared private helper; the
# structural guarantees below are pinned on it.
HELPER = "_run_projected_pipeline"


class SpyManager(PipelineRunManager):
    """Records every status transition in order."""

    def __init__(self, engine: PipelineEngine | None = None) -> None:
        super().__init__(engine)
        self.transitions: list[tuple[str, S]] = []

    def update_run(self, run_id: str, *, status=None, metadata=None) -> PipelineRun:
        rec = super().update_run(run_id, status=status, metadata=metadata)
        if status is not None:
            self.transitions.append((run_id, rec.status))
        return rec


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise self.exc


def build(*tools: object) -> tuple[Agent, SpyManager]:
    a0 = Agent()  # borrow default wiring shape: manager must be wired to the engine
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    engine = a0.pipeline_engine
    manager = SpyManager(engine)
    a = Agent(
        goal_manager=a0.goal_manager, planning_engine=a0.planning_engine,
        task_graph=a0.task_graph, execution_planner=a0.execution_planner,
        pipeline_engine=engine, pipeline_run_manager=manager, tool_registry=reg,
    )
    return a, manager


class TestContract:
    def test_signature_and_shape(self) -> None:
        params = inspect.signature(getattr(Agent, METHOD)).parameters
        assert list(params) == ["self", "goal", "project"]
        a, _ = build()
        out = a.execute_projection_with_run_status("fix the wifi")
        assert len(out) == 4
        projection, run, decisions, results = out
        assert isinstance(projection, PlanProjection)
        assert isinstance(run, PipelineRun)
        assert all(isinstance(d, ToolDispatchDecision) for d in decisions)
        assert isinstance(results, tuple)

    def test_decisions_and_results_match_v8_22(self) -> None:
        a, _ = build(StaticMockTool(name="step one", output="1"))
        _, _, d1, r1 = a.execute_projection_with_run_status("step one then step two")
        _, d2, r2 = a.execute_projection_with_tool_dispatch("step one then step two")
        assert d1 == d2 and r1 == r2


class TestStatusSequence:
    def test_success_sequence(self) -> None:
        a, m = build(StaticMockTool(name="fix the wifi"))
        _, run, _, results = a.execute_projection_with_run_status("fix the wifi")
        assert [s for _, s in m.transitions] == [S.RUNNING, S.COMPLETED]
        assert run.status is S.COMPLETED
        assert len(results) == 1

    def test_run_references_projected_pipeline(self) -> None:
        a, m = build()
        projection, run, _, _ = a.execute_projection_with_run_status("fix the wifi", project="p")
        assert run.pipeline_reference == projection.pipeline_id
        assert m.get_run(run.id) is run
        assert dict(run.metadata) == {"project": "p", "goal_id": projection.goal_id, "mapping_id": projection.mapping_id}

    def test_run_created_in_created_state(self) -> None:
        a, m = build()
        _, run, _, _ = a.execute_projection_with_run_status("fix the wifi")
        assert m.transitions[0] == (run.id, S.RUNNING)  # first transition is CREATED -> RUNNING
        assert m.count() == 1

    def test_all_skipped_completes(self) -> None:
        a, m = build()
        _, run, decisions, results = a.execute_projection_with_run_status("step one then step two")
        assert all(d.action == "skip" for d in decisions) and results == ()
        assert run.status is S.COMPLETED
        assert [s for _, s in m.transitions] == [S.RUNNING, S.COMPLETED]

    def test_running_set_before_first_route(self) -> None:
        a, m = build()
        seen: list[S] = []

        class Peek:
            name = "fix the wifi"
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                seen.append(m.list_runs()[0].status)
                return ToolResult(request.tool_name, "ok")

        a.tool_registry.register(Peek())
        a.execute_projection_with_run_status("fix the wifi")
        assert seen == [S.RUNNING]

    def test_failure_marks_failed_and_reraises_same_exception(self) -> None:
        exc = RuntimeError("boom")
        a, m = build(Failing("fix the wifi", exc))
        with pytest.raises(RuntimeError) as info:
            a.execute_projection_with_run_status("fix the wifi")
        assert info.value is exc
        assert [s for _, s in m.transitions] == [S.RUNNING, S.FAILED]
        assert m.list_runs()[0].status is S.FAILED

    def test_tool_error_marks_failed(self) -> None:
        a, m = build(Failing("fix the wifi", ToolError("tool failed")))
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_projection_with_run_status("fix the wifi")
        assert m.list_runs()[0].status is S.FAILED

    def test_failure_after_success_stops_and_marks_failed(self) -> None:
        first = StaticMockTool(name="step one")
        a, m = build(first, Failing("step two", KeyError("k")))
        with pytest.raises(KeyError):
            a.execute_projection_with_run_status("step one then step two")
        assert first.call_count == 1
        assert m.list_runs()[0].status is S.FAILED

    def test_no_run_when_projection_fails(self) -> None:
        a, m = build()
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_run_status("   ")
        assert m.count() == 0

    def test_repeated_calls_create_independent_runs(self) -> None:
        a, m = build(StaticMockTool(name="fix the wifi"))
        _, r1, _, _ = a.execute_projection_with_run_status("fix the wifi")
        _, r2, _, _ = a.execute_projection_with_run_status("fix the wifi")
        assert r1.id != r2.id and r1.pipeline_reference != r2.pipeline_reference
        assert [r.status for r in m.list_runs()] == [S.COMPLETED, S.COMPLETED]

    def test_default_agent_uses_its_own_manager(self) -> None:
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="fix the wifi"))
        _, run, _, _ = a.execute_projection_with_run_status("fix the wifi")
        assert a.pipeline_run_manager.get_run(run.id) is run
        assert run.status is S.COMPLETED


class TestInjection:
    def test_manager_wired_to_other_engine_fails_loudly(self) -> None:
        foreign = PipelineRunManager(PipelineEngine(__import__("core.execution_planner", fromlist=["ExecutionPlanner"]).ExecutionPlanner()))
        a = Agent(pipeline_run_manager=foreign)
        with pytest.raises(ValueError, match="not found in wired PipelineEngine"):
            a.execute_projection_with_run_status("fix the wifi")
        assert foreign.count() == 0
        # Projection already happened (non-atomic, documented) but no run exists.
        assert a.pipeline_engine.count() == 1

    def test_unwired_manager_accepts_run(self) -> None:
        loose = PipelineRunManager()
        a = Agent(pipeline_run_manager=loose)
        _, run, _, _ = a.execute_projection_with_run_status("fix the wifi")
        assert loose.get_run(run.id) is run


class TestIsolation:
    def test_no_legacy_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or False)
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        a, _ = build(StaticMockTool(name="fix the wifi"))
        monkeypatch.setattr(a, "coordinate_execution", lambda s: called.append("coordinate"))
        a.execute_projection_with_run_status("fix the wifi")
        assert called == []

    def test_no_writeback(self) -> None:
        a, _ = build(StaticMockTool(name="fix the wifi"))
        a.execute_projection_with_run_status("fix the wifi")
        assert a.memory_engine.count() == 0 and a.reflection_engine.count() == 0
        assert a.snapshot()["learning"] == []

    def test_other_paths_create_no_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: True)
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a, m = build(StaticMockTool(name="fix the wifi"))
        a.execute_request_with_learning("fix the wifi")
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        a.execute_projection_with_tool_dispatch("fix the wifi")
        assert m.count() == 0

    def test_registry_not_modified(self) -> None:
        a, _ = build(StaticMockTool(name="fix the wifi"))
        before = a.tool_registry.names()
        a.execute_projection_with_run_status("fix the wifi")
        assert a.tool_registry.names() == before


class TestArchitecture:
    def test_method_reraises_unchanged(self) -> None:
        node = _method_node(HELPER)
        handlers = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
        assert len(handlers) == 1
        (h,) = handlers
        assert isinstance(h.type, ast.Name) and h.type.id == "BaseException"
        assert h.name is None  # exception not bound/re-wrapped
        raises = [n for n in ast.walk(h) if isinstance(n, ast.Raise)]
        assert len(raises) == 1 and raises[0].exc is None  # bare ``raise``
        calls = {c.func.attr for c in ast.walk(h) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert calls == {"update_run"}

    def test_method_calls(self) -> None:
        node = _method_node()
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"project_request", HELPER}
        helper = _method_node(HELPER)
        hcalls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                  for c in ast.walk(helper) if isinstance(c, ast.Call)}
        assert hcalls == {"get_pipeline", "KeyError", "create_run",
                          "build_stage_dispatch_decisions", "update_run", "ToolRequest",
                          "route", "append", "tuple"}
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
            n.id for n in ast.walk(helper) if isinstance(n, ast.Name)}
        for forbidden in ("skill_dispatch", "is_registered", "build_dispatch_decision",
                          "record_problem_outcome", "gather_context"):
            assert forbidden not in names, forbidden

    def test_only_allowed_transitions_used(self) -> None:
        node = _method_node(HELPER)
        statuses = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name) and n.value.id == "PipelineRunStatus"}
        assert statuses == {"RUNNING", "COMPLETED", "FAILED"}

    def test_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "PipelineRun" not in agent_module.__all__

    def test_no_new_agent_modules(self) -> None:
        with open(AGENT_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = {(n.module, a.name) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module for a in n.names}
        assert ("core.pipeline_run", "PipelineRun") in names
        assert ("core.pipeline_run", "PipelineRunStatus") in names
        modules = {m for m, _ in names}
        assert "core.stage_dispatch" in modules and "core.plan_projection" in modules
