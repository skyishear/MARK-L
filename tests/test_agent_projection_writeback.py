"""Tests for v8.24 Projection-Run Writeback
(``Agent.execute_projection_with_writeback``)."""

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
from core.pipeline_run import PipelineRun, PipelineRunStatus
from core.plan_projection import PlanProjection
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")
METHOD = "execute_projection_with_writeback"


def _method_node() -> ast.FunctionDef:
    with open(AGENT_FILE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == METHOD:
            return node
    raise AssertionError("method not found")


@pytest.fixture
def stub_remember(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    writes: list[tuple] = []
    monkeypatch.setattr(problem_solver, "remember", lambda *a, **k: writes.append((a, k)) or "id")
    return writes


class Failing:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fails"

    def invoke(self, request: ToolRequest) -> ToolResult:
        raise RuntimeError("simulated tool failure")


def agent_with(*names: str, output: str = "fixed") -> Agent:
    a = Agent()
    for n in names:
        a.tool_registry.register(StaticMockTool(name=n, output=output))
    return a


class TestContract:
    def test_signature_and_shape(self) -> None:
        params = inspect.signature(getattr(Agent, METHOD)).parameters
        assert list(params) == ["self", "goal", "project"]
        a = agent_with("fix the wifi")
        projection, run, decisions, results = a.execute_projection_with_writeback("fix the wifi")
        assert isinstance(projection, PlanProjection) and isinstance(run, PipelineRun)
        assert run.status is PipelineRunStatus.COMPLETED
        assert results == (ToolResult("fix the wifi", "fixed"),)

    def test_same_output_as_run_status_path(self) -> None:
        a, b = agent_with("fix the wifi"), agent_with("fix the wifi")
        p1, r1, d1, t1 = a.execute_projection_with_writeback("fix the wifi")
        p2, r2, d2, t2 = b.execute_projection_with_run_status("fix the wifi")
        assert (d1, t1, r1.status) == (d2, t2, r2.status)

    def test_runs_the_v8_23_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # v8.28: v8.24 runs the v8.23 body (``project_request`` + the shared
        # ``_run_projected_pipeline``) directly instead of through the public
        # v8.23 method, so the failed stage is known for failure writeback.
        # Pinned: exactly one projection and one shared run per call, and
        # results identical to the v8.23 method for the same inputs.
        a = agent_with("fix the wifi")
        calls: list[str] = []
        for name in ("project_request", "_run_projected_pipeline"):
            original = getattr(a, name)
            monkeypatch.setattr(a, name, lambda *x, _o=original, _n=name, **k: calls.append(_n) or _o(*x, **k))
        a.execute_projection_with_writeback("fix the wifi")
        assert calls == ["project_request", "_run_projected_pipeline"]
        b, c = agent_with("step one", "step two"), agent_with("step one", "step two")
        _, r1, d1, t1 = b.execute_projection_with_writeback("step one then step two", project="p")
        _, r2, d2, t2 = c.execute_projection_with_run_status("step one then step two", project="p")
        assert (d1, t1, r1.status, set(r1.metadata)) == (d2, t2, r2.status, set(r2.metadata))


class TestWrites:
    def test_exactly_one_write_per_layer_per_dispatch(self, stub_remember: list) -> None:
        a = agent_with("step one", "step two")
        a.execute_projection_with_writeback("step one then step two")
        assert len(stub_remember) == 2
        assert a.reflection_engine.count() == 2
        assert len(a.learning.get_all()) == 2

    def test_memory_write_content(self, stub_remember: list) -> None:
        agent_with("fix the wifi").execute_projection_with_writeback("fix the wifi", project="p")
        args, kwargs = stub_remember[0]
        value = kwargs.get("value") or args[2]
        assert "SOLVED" in value and "cause: controlled_tool_dispatch" in value
        assert "problem: fix the wifi" in value
        assert kwargs.get("project", args[3] if len(args) > 3 else None) == "p"

    def test_reflection_content(self) -> None:
        a = agent_with("fix the wifi", output="signal restored")
        _, _, decisions, _ = a.execute_projection_with_writeback("fix the wifi")
        (rec,) = a.reflection.get_all()
        assert rec.subject == decisions[0].task_id
        assert rec.what_worked == "controlled_tool_dispatch:fix the wifi"
        assert "signal restored" in rec.completion_summary
        assert rec.confidence_level == 1.0

    def test_learning_content_includes_run_id(self) -> None:
        a = agent_with("fix the wifi", output="signal restored")
        _, run, decisions, _ = a.execute_projection_with_writeback("fix the wifi", project="p")
        (rec,) = a.learning.get_all()
        assert rec.subject == "fix the wifi"
        assert rec.metadata == {"task_id": decisions[0].task_id, "project": "p",
                                "output": "signal restored", "run_id": run.id}

    def test_layer_order_and_pairing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        order: list[str] = []
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="step one", output="O1"))
        a.tool_registry.register(StaticMockTool(name="step three", output="O3"))
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("M") or "id")
        orig_r, orig_l = a.reflection.add_reflection, a.learning.record_successful_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("R") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_successful_pattern", lambda **k: order.append("L") or orig_l(**k))
        _, _, decisions, results = a.execute_projection_with_writeback("step one then step two then step three")
        assert [d.action for d in decisions] == ["dispatch", "skip", "dispatch"]
        assert order == ["M", "M", "R", "R", "L", "L"]
        recs = a.learning.get_all()
        assert [r.metadata["output"] for r in recs] == ["O1", "O3"] == [r.output for r in results]

    def test_writes_after_run_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with("fix the wifi")
        seen: list[PipelineRunStatus] = []
        monkeypatch.setattr(problem_solver, "remember",
                            lambda *x, **k: seen.append(a.pipeline_run_manager.list_runs()[0].status) or "id")
        a.execute_projection_with_writeback("fix the wifi")
        assert seen == [PipelineRunStatus.COMPLETED]


class TestNoWrites:
    def test_skipped_writes_nothing(self, stub_remember: list) -> None:
        a = Agent()
        _, run, _, _ = a.execute_projection_with_writeback("fix the wifi")
        assert run.status is PipelineRunStatus.COMPLETED
        assert stub_remember == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_failure_writes_one_failure_record_and_run_failed(self, stub_remember: list) -> None:
        # v8.28 (owner-authorized expansion): a failed attempt now writes
        # exactly one structured failure record per layer and still no
        # success record (full contract: tests/test_failure_writeback_v8_24.py).
        a = Agent()
        a.tool_registry.register(StaticMockTool(name="step one"))
        a.tool_registry.register(Failing("step two"))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_writeback("step one then step two")
        assert len(stub_remember) == 1 and stub_remember[0][0][2].startswith("FAILED |")
        assert a.reflection_engine.count() == 1
        assert [r.category for r in a.learning.get_all()] == ["failed_pattern"]
        assert a.pipeline_run_manager.list_runs()[0].status is PipelineRunStatus.FAILED

    def test_tool_error_propagates(self) -> None:
        class F:
            name = "fix the wifi"
            description = "d"

            def invoke(self, request: ToolRequest) -> ToolResult:
                raise ToolError("tool failed")

        a = Agent()
        a.tool_registry.register(F())
        with pytest.raises(ToolError, match="tool failed"):
            a.execute_projection_with_writeback("fix the wifi")

    def test_projection_failure_writes_nothing(self, stub_remember: list) -> None:
        from core.planner import InvalidGoalError

        a = agent_with("fix the wifi")
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_writeback("  ")
        assert stub_remember == [] and a.pipeline_run_manager.count() == 0


class TestIsolation:
    def test_no_legacy_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: called.append("dispatch"))
        monkeypatch.setattr(agent_module, "is_registered", lambda n: called.append("is_registered") or False)
        monkeypatch.setattr(agent_module, "build_dispatch_decision", lambda *a, **k: called.append("decision"))
        monkeypatch.setattr(skill_registry, "dispatch", lambda *a, **k: called.append("reg.dispatch"))
        agent_with("fix the wifi").execute_projection_with_writeback("fix the wifi")
        assert called == []

    def test_other_paths_unchanged(self, monkeypatch: pytest.MonkeyPatch, stub_remember: list) -> None:
        monkeypatch.setattr(skill_dispatch_module, "is_registered", lambda n: n == "fix the wifi")
        monkeypatch.setattr(agent_module, "skill_dispatch", lambda *a, **k: "ok")
        a = agent_with("fix the wifi")
        a.execute_request_with_learning("fix the wifi")
        assert len(stub_remember) == 1 and "controlled_skill_execution" in (stub_remember[0][1].get("value") or stub_remember[0][0][2])
        a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(stub_remember) == 2
        a.execute_projection_with_run_status("fix the wifi")
        assert len(stub_remember) == 2  # v8.23 path still writes nothing
        assert a.pipeline_run_manager.count() == 1

    def test_skill_globals_untouched(self) -> None:
        before = (dict(skill_registry._skills), dict(skill_registry._tool_index))  # noqa: SLF001
        agent_with("fix the wifi").execute_projection_with_writeback("fix the wifi")
        assert (dict(skill_registry._skills), dict(skill_registry._tool_index)) == before  # noqa: SLF001

    def test_no_goal_or_plan_status_transition(self) -> None:
        from core.goal_manager import GoalStatus
        from core.planning_engine import PlanStatus

        a = agent_with("fix the wifi")
        projection, _, _, _ = a.execute_projection_with_writeback("fix the wifi")
        assert a.goal_manager.get_goal(projection.goal_id).status is GoalStatus.DRAFT
        assert a.planning_engine.get_plan(projection.plan_id).status is PlanStatus.DRAFT


class TestArchitecture:
    def test_method_uses_only_existing_write_apis(self) -> None:
        # v8.25 extracted the write loops into ``_record_tool_outcomes``;
        # the method is glue over it and the writes are pinned on the helper.
        node = _method_node()
        calls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                 for c in ast.walk(node) if isinstance(c, ast.Call)}
        # v8.28: the v8.23 body is run directly (see test_runs_the_v8_23_body).
        assert calls == {"project_request", "_run_projected_pipeline",
                         "_record_failure_outcome", "_record_tool_outcomes"}
        # v8.28: exactly one handler -- around the run only -- performing the
        # failure writeback and re-raising the original exception unchanged.
        (h,) = [x for x in ast.walk(node) if isinstance(x, ast.ExceptHandler)]
        assert isinstance(h.type, ast.Name) and h.type.id == "BaseException"
        raises = [x for x in ast.walk(h) if isinstance(x, ast.Raise)]
        assert len(raises) == 1 and raises[0].exc is None
        assert {getattr(c.func, "attr", None) for c in ast.walk(h) if isinstance(c, ast.Call)} == {
            "_record_failure_outcome"}
        (t,) = [x for x in ast.walk(node) if isinstance(x, ast.Try)]
        assert {getattr(c.func, "attr", None) for s in t.body for c in ast.walk(s)
                if isinstance(c, ast.Call)} == {"_run_projected_pipeline"}
        assert not t.finalbody and not t.orelse
        with open(AGENT_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        helper = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "_record_tool_outcomes")
        hcalls = {c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None)
                  for c in ast.walk(helper) if isinstance(c, ast.Call)}
        assert hcalls == {"record_problem_outcome", "add_reflection",
                          "record_successful_pattern", "tuple", "zip"}
        for n in (node, helper):
            attrs = {a.attr for a in ast.walk(n) if isinstance(a, ast.Attribute)}
            assert not attrs & {"_tool_router", "_tool_registry", "route", "update_run", "create_run",
                                "update_goal", "update_plan"}
        for x in ast.walk(helper):
            assert not isinstance(x, (ast.Try, ast.ExceptHandler))

    def test_no_new_agent_imports(self) -> None:
        with open(AGENT_FILE, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert "core.stage_dispatch" in modules and "core.plan_projection" in modules
        assert len([m for m in modules if m.startswith("core.")]) == 39  # v8.24: 34; v8.25 added core.lifecycle_reflection; v8.26 core.step_lifecycle; v8.28 core.execution_failure; v8.30 core.failure_taxonomy; v8.32 core.tool_catalog

    def test_all_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
