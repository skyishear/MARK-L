"""Tests for v8.27 Execution Failure Writeback
(``Agent._record_failure_outcome`` on the ``execute_projection_with_lifecycle``
path).

Contract (owner decision after the v8.26 audit): exactly one structured
failure writeback per failed execution attempt, through the existing
Memory -> Reflection -> Learning APIs; only structured data (exception type
name + record references), never exception text; the original exception
always propagates and a failing writeback never masks it; statuses are
unchanged; projection / pre-run failures are not execution failures; no
retry / resume.
"""

from __future__ import annotations

import ast
import os

import pytest

import core.agent as agent_module
from core import problem_solver
from core.agent import Agent
from core.agent.learning_manager import LearningCategory
from core.goal_manager import GoalStatus
from core.pipeline_run import PipelineRunStatus
from core.planner import InvalidGoalError
from core.planning_engine import PlanStatus
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
AGENT_FILE = os.path.join(ROOT, "core", "agent", "__init__.py")
G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
THREE = "step one then step two then step three"
SECRET = "api_key=SECRET-9f2c /home/alice/private.txt"


def _agent_tree() -> ast.Module:
    with open(AGENT_FILE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _method(name: str) -> ast.FunctionDef:
    for node in ast.walk(_agent_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        raise self.exc


@pytest.fixture(autouse=True)
def memory(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    writes: list[tuple] = []
    monkeypatch.setattr(problem_solver, "remember", lambda *a, **k: writes.append((a, k)) or "id")
    return writes


def agent_with(*tools: object) -> Agent:
    a = Agent()
    for t in tools:
        a.tool_registry.register(t)
    return a


def fail_at_step_two(exc: BaseException | None = None) -> tuple[Agent, BaseException]:
    exc = exc or ToolError(SECRET)
    a = agent_with(StaticMockTool(name="step one"), Failing("step two", exc),
                   StaticMockTool(name="step three"))
    with pytest.raises(type(exc)) as info:
        a.execute_projection_with_lifecycle(THREE)
    assert info.value is exc
    return a, exc


def everything_written(a: Agent, memory: list[tuple]) -> str:
    return repr((memory, a.reflection.get_all(), a.learning.get_all()))


# ── success path unchanged ──────────────────────────────────────────────


class TestSuccessUnchanged:
    def test_success_writes_only_success_records(self, memory: list) -> None:
        a = agent_with(StaticMockTool(name="step one"), StaticMockTool(name="step two"))
        a.execute_projection_with_lifecycle("step one then step two")
        assert [m[0][2].split(" |")[0] for m in memory] == ["SOLVED", "SOLVED"]
        assert all(r.what_failed == "" for r in a.reflection.get_all())
        assert {r.category for r in a.learning.get_all()} == {LearningCategory.SUCCESSFUL_PATTERN}

    def test_success_writeback_identical_to_v8_24(self, memory: list) -> None:
        tools = ("step one", "step two")
        a = agent_with(*(StaticMockTool(name=n) for n in tools))
        b = agent_with(*(StaticMockTool(name=n) for n in tools))
        a.execute_projection_with_lifecycle(THREE)
        first = list(memory)
        memory.clear()
        b.execute_projection_with_writeback(THREE)
        assert first == memory
        strip = lambda recs: [(r.subject, r.what_worked, r.what_failed, r.confidence_level) for r in recs]  # noqa: E731
        assert strip(a.reflection.get_all()) == strip(b.reflection.get_all())
        assert [(r.category, r.subject) for r in a.learning.get_all()] == [
            (r.category, r.subject) for r in b.learning.get_all()]

    def test_all_skipped_no_failure_writeback(self, memory: list) -> None:
        a = Agent()
        _, run, _, _ = a.execute_projection_with_lifecycle(THREE)
        assert run.status is R.COMPLETED
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []


# ── exactly one structured failure writeback ────────────────────────────


class TestFailureWriteback:
    def test_exactly_one_record_per_layer(self, memory: list) -> None:
        a, _ = fail_at_step_two()
        assert len(memory) == 1
        assert a.reflection_engine.count() == 1 and len(a.reflection.get_all()) == 1
        (rec,) = a.learning.get_all()
        assert rec.category is LearningCategory.FAILED_PATTERN and rec.occurrence_count == 1

    def test_no_success_record_for_stages_completed_before_failure(self, memory: list) -> None:
        a, _ = fail_at_step_two()
        assert not any(m[0][2].startswith("SOLVED") for m in memory)
        assert not [r for r in a.learning.get_all() if r.category is LearningCategory.SUCCESSFUL_PATTERN]

    def test_structured_content(self, memory: list) -> None:
        a, _ = fail_at_step_two()
        run = a.pipeline_run_manager.list_runs()[0]
        plan = a.planning_engine.list_plans()[0]
        goal = a.goal_manager.list_goals()[0]
        failing = plan.steps[1]
        expected_meta = {
            "run_id": run.id, "goal_id": goal.id, "plan_id": plan.id,
            "task_id": failing.id, "project": None, "exception_type": "ToolError",
        }
        ((args, kwargs),) = memory
        assert args == ("problems_solutions", "step_two",
                        "FAILED | problem: step two | cause: controlled_tool_dispatch_failure"
                        " | solution: step two | outcome: failed:ToolError")
        assert kwargs == {"importance": 3, "confidence": 0.5, "project": None, "source": "solver"}
        (ref,) = a.reflection.get_all()
        assert ref.subject == failing.id
        assert ref.what_failed == "controlled_tool_dispatch:step two" and ref.what_worked == ""
        assert ref.confidence_level == 0.0
        assert ref.completion_summary == "Execution attempt failed (ToolError) under controlled tool dispatch."
        assert ref.metadata == expected_meta
        (learn,) = a.learning.get_all()
        assert learn.subject == "step two"
        assert learn.detail == "Execution attempt failed (ToolError) under controlled tool dispatch."
        assert learn.metadata == expected_meta

    def test_project_recorded(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi", project="home")
        assert memory[0][1]["project"] == "home"
        assert a.learning.get_all()[0].metadata["project"] == "home"

    def test_exception_text_never_persisted(self, memory: list) -> None:
        a, _ = fail_at_step_two()
        dumped = everything_written(a, memory)
        for fragment in ("SECRET-9f2c", "api_key", "/home/alice", "private.txt", "Traceback"):
            assert fragment not in dumped, fragment

    def test_exception_args_payload_never_persisted(self, memory: list) -> None:
        exc = RuntimeError({"token": "tok-123"}, "password=hunter2")
        a, _ = fail_at_step_two(exc)
        dumped = everything_written(a, memory)
        assert "tok-123" not in dumped and "hunter2" not in dumped
        assert a.learning.get_all()[0].metadata["exception_type"] == "RuntimeError"

    def test_writeback_order_memory_reflection_learning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        order: list[str] = []
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("memory") or "id")
        orig_r, orig_l = a.reflection.add_reflection, a.learning.record_failed_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("reflection") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_failed_pattern", lambda **k: order.append("learning") or orig_l(**k))
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert order == ["memory", "reflection", "learning"]

    def test_writeback_after_run_failed_and_steps_final(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", ToolError("x")))
        seen: list[tuple] = []

        def remember(*x, **k):
            seen.append((a.pipeline_run_manager.list_runs()[0].status,
                         [s.status for s in a.planning_engine.list_plans()[0].steps]))
            return "id"

        monkeypatch.setattr(problem_solver, "remember", remember)
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle(THREE)
        assert seen == [(R.FAILED, [P.COMPLETED, P.ACTIVE, P.DRAFT])]

    def test_single_writeback_although_two_layers_observe(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        calls: list[object] = []
        original = a._record_failure_outcome  # noqa: SLF001
        monkeypatch.setattr(a, "_record_failure_outcome", lambda *x, **k: calls.append(x) or original(*x, **k))
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        # The run helper's handler observed it too (run FAILED), yet one writeback.
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED
        assert len(calls) == 1 and len(memory) == 1

    def test_each_attempt_writes_once(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        for _ in range(2):
            with pytest.raises(ToolError):
                a.execute_projection_with_lifecycle("fix the wifi")
        assert len(memory) == 2 and a.reflection_engine.count() == 2
        (rec,) = a.learning.get_all()  # existing (category, subject) merge
        assert rec.occurrence_count == 2

    def test_unknown_failing_step_falls_back_to_goal(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        # The step write itself fails before the step becomes ACTIVE.
        exc = RuntimeError("store down")
        monkeypatch.setattr(agent_module, "reflect_step_reached", lambda *x, **k: (_ for _ in ()).throw(exc))
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(RuntimeError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc
        goal = a.goal_manager.list_goals()[0]
        (ref,) = a.reflection.get_all()
        assert ref.subject == goal.id and ref.metadata["task_id"] is None
        assert ref.what_failed == "controlled_tool_dispatch:unknown stage"
        assert a.learning.get_all()[0].subject == goal.title
        assert "problem: fix the wifi" in memory[0][0][2]

    def test_interrupt_is_recorded_and_propagates(self, memory: list) -> None:
        a, exc = fail_at_step_two(KeyboardInterrupt())
        assert a.learning.get_all()[0].metadata["exception_type"] == "KeyboardInterrupt"
        assert len(memory) == 1


# ── original exception wins ─────────────────────────────────────────────


class TestOriginalExceptionWins:
    def test_original_exception_identity(self) -> None:
        fail_at_step_two()

    @pytest.mark.parametrize("layer", ["memory", "reflection", "learning"])
    def test_failing_writeback_does_not_mask(self, layer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("original")))

        def boom(*x, **k):
            raise ValueError("writeback broke")

        target = {"memory": (problem_solver, "remember"),
                  "reflection": (a.reflection, "add_reflection"),
                  "learning": (a.learning, "record_failed_pattern")}[layer]
        monkeypatch.setattr(*target, boom)
        with pytest.raises(ToolError, match="original") as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert not isinstance(info.value, ValueError)
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED

    def test_writes_stop_at_the_failing_layer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: (_ for _ in ()).throw(ValueError()))
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert a.learning.get_all() == []  # non-atomic, documented: memory already written

    def test_failing_state_lookup_does_not_mask(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("original")))
        monkeypatch.setattr(a.pipeline_run_manager, "list_runs", lambda *x, **k: (_ for _ in ()).throw(KeyError("gone")))
        with pytest.raises(ToolError, match="original"):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert memory == []


# ── execution state stays authoritative ─────────────────────────────────


class TestStateAuthoritative:
    def test_statuses_after_failure(self) -> None:
        a, _ = fail_at_step_two()
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED
        assert a.goal_manager.list_goals()[0].status is G.ACTIVE
        plan = a.planning_engine.list_plans()[0]
        assert plan.status is P.ACTIVE
        assert [s.status for s in plan.steps] == [P.COMPLETED, P.ACTIVE, P.DRAFT]

    def test_writeback_makes_no_status_transition(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        events: list[str] = []
        called = {"writeback": False}
        original = a._record_failure_outcome  # noqa: SLF001

        def wrapped(*x, **k):
            called["writeback"] = True
            return original(*x, **k)

        for store, name in ((a.goal_manager, "update_goal"), (a.planning_engine, "update_plan"),
                            (a.pipeline_run_manager, "update_run")):
            orig = getattr(store, name)
            monkeypatch.setattr(store, name, lambda *x, _o=orig, _n=name, **k: (
                events.append(_n) if called["writeback"] else None) or _o(*x, **k))
        monkeypatch.setattr(a, "_record_failure_outcome", wrapped)
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert called["writeback"] and events == []


# ── non-execution failures and other paths ──────────────────────────────


class TestNotExecutionFailures:
    def test_projection_failure_no_writeback(self, memory: list) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_lifecycle("   ")
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_failure_before_run_started_no_writeback(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        exc = ValueError("setup")
        monkeypatch.setattr(agent_module, "build_stage_dispatch_decisions", lambda *x, **k: (_ for _ in ()).throw(exc))
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(ValueError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc
        assert a.pipeline_run_manager.list_runs()[0].status is R.CREATED
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_lifecycle_start_failure_no_writeback(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        monkeypatch.setattr(agent_module, "reflect_execution_started", lambda *x, **k: (_ for _ in ()).throw(KeyError("k")))
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(KeyError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert memory == [] and a.pipeline_run_manager.count() == 0

    @pytest.mark.parametrize("method", [
        "execute_projection_with_tool_dispatch",
        "execute_projection_with_run_status",
        # v8.24 (execute_projection_with_writeback) writes failures since
        # v8.28 -- see tests/test_failure_writeback_v8_24.py.
    ])
    def test_v8_22_and_v8_23_failure_write_nothing(self, method: str, memory: list) -> None:
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", ToolError("x")))
        with pytest.raises(ToolError):
            getattr(a, method)(THREE)
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []
        assert [s.status for s in a.planning_engine.list_plans()[0].steps] == [P.DRAFT] * 3


# ── no retry / resume, no new statuses, architecture ────────────────────


class TestArchitecture:
    def test_failing_tool_invoked_exactly_once(self) -> None:
        tool = Failing("fix the wifi", ToolError("x"))
        a = agent_with(tool)
        with pytest.raises(ToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 1 and a.pipeline_run_manager.count() == 1

    def test_no_retry_or_resume_surface(self) -> None:
        for name in dir(Agent):
            low = name.lower()
            assert not any(w in low for w in ("retry", "resume", "reexecut", "re_execut", "attempt")), name

    def test_status_vocabularies_unchanged(self) -> None:
        from core.pipeline_run import ALLOWED_TRANSITIONS

        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5

    def test_writeback_never_reads_exception_text(self) -> None:
        # v8.28: the exception is handed only to the shared normalizer, which
        # reads nothing but ``type(exc).__name__`` (pinned in
        # tests/test_execution_failure.py).
        node = _method("_record_failure_outcome")
        uses = [n for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == "exc"]
        norm_calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)
                      and isinstance(c.func, ast.Name) and c.func.id == "normalize_execution_failure"
                      and c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "exc"]
        assert len(uses) == len(norm_calls) == 1  # only ``normalize_execution_failure(exc, ...)``
        body = [n for stmt in node.body for n in ast.walk(stmt)]  # excludes signature annotations
        names = {n.id for n in body if isinstance(n, ast.Name)}
        attrs = {n.attr for n in body if isinstance(n, ast.Attribute)}
        assert not {"str", "repr", "traceback", "format_exc"} & names
        assert not {"args", "__traceback__", "__str__", "format_exc"} & attrs

    def test_writeback_uses_only_existing_apis_and_no_transitions(self) -> None:
        node = _method("_record_failure_outcome")
        calls = {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert {"record_problem_outcome", "add_reflection", "record_failed_pattern"} <= calls
        assert not calls & {"update_goal", "update_plan", "update_run", "route", "create_run",
                            "record_successful_pattern", "reflect_step_completed"}

    def test_writeback_suppresses_only_exception_subclasses(self) -> None:
        node = _method("_record_failure_outcome")
        (h,) = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
        assert isinstance(h.type, ast.Name) and h.type.id == "Exception"
        assert not [n for n in ast.walk(h) if isinstance(n, ast.Raise)]

    def test_only_lifecycle_and_v8_24_methods_write_failures(self) -> None:
        # v8.28 extended failure writeback to the v8.24 path (owner-authorized).
        callers = set()
        for fn in ast.walk(_agent_tree()):
            if isinstance(fn, ast.FunctionDef):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "_record_failure_outcome":
                        callers.add(fn.name)
        assert callers == {"execute_projection_with_lifecycle", "execute_projection_with_writeback"}

    def test_no_new_module_or_public_api(self) -> None:
        assert len(agent_module.__all__) == 16
        assert not os.path.exists(os.path.join(ROOT, "core", "failure_writeback.py"))
