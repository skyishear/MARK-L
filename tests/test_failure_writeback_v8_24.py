"""Tests for v8.28 failure writeback on the v8.24 projection-writeback path
(``Agent.execute_projection_with_writeback``), and v8.27 compatibility.

Contract: a failed v8.24 execution attempt (FAILED ``PipelineRun``) gets
exactly one structured failure writeback through the shared v8.27 writer
(Memory -> Reflection -> Learning), built from a v8.28 ``ExecutionFailure``
(exception type name only); the failed stage is the last dispatched one;
the original exception always propagates; no success record for a failed
attempt (unchanged v8.24 behaviour); pre-run failures write nothing;
v8.20 / v8.22 / v8.23 unchanged; no status change.
"""

from __future__ import annotations

import pytest

import core.agent as agent_module
from core import problem_solver
from core.agent import Agent
from core.agent.learning_manager import LearningCategory
from core.goal_manager import GoalStatus
from core.pipeline_run import ALLOWED_TRANSITIONS, PipelineRunStatus
from core.planner import InvalidGoalError
from core.planning_engine import PlanStatus
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
THREE = "step one then step two then step three"
SECRET = "api_key=SECRET-9f2c /home/alice/private.txt"


class Failing:
    def __init__(self, name: str, exc: BaseException) -> None:
        self.name = name
        self.description = "fails"
        self.exc = exc
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        raise self.exc


class Counting(StaticMockTool):
    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        return super().invoke(request)


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


def fail_step_two(method: str = "execute_projection_with_writeback", exc: BaseException | None = None):
    exc = exc or ToolError(SECRET)
    three = Counting("step three")
    a = agent_with(StaticMockTool(name="step one"), Failing("step two", exc), three)
    with pytest.raises(type(exc)) as info:
        getattr(a, method)(THREE)
    assert info.value is exc
    return a, exc, three


def records(a: Agent, memory: list) -> tuple:
    return (
        [(m[0], m[1]) for m in memory],
        [(r.subject, r.what_worked, r.what_failed, r.completion_summary, r.confidence_level,
          {k: v for k, v in r.metadata.items() if k not in {"run_id", "goal_id", "plan_id", "task_id"}})
         for r in a.reflection.get_all()],
        [(r.category, r.subject, r.detail, r.occurrence_count,
          {k: v for k, v in r.metadata.items() if k not in {"run_id", "goal_id", "plan_id", "task_id"}})
         for r in a.learning.get_all()],
    )


# ── v8.24 failure writeback ─────────────────────────────────────────────


class TestV824FailureWriteback:
    def test_exactly_one_record_per_layer(self, memory: list) -> None:
        a, _, _ = fail_step_two()
        assert len(memory) == 1 and a.reflection_engine.count() == 1
        (rec,) = a.learning.get_all()
        assert rec.category is LearningCategory.FAILED_PATTERN and rec.occurrence_count == 1

    def test_structured_content(self, memory: list) -> None:
        a, _, _ = fail_step_two()
        run = a.pipeline_run_manager.list_runs()[0]
        plan = a.planning_engine.list_plans()[0]
        goal = a.goal_manager.list_goals()[0]
        failed = plan.steps[1]  # Step.id == legacy task id == decision.task_id
        meta = {"run_id": run.id, "goal_id": goal.id, "plan_id": plan.id,
                "task_id": failed.id, "project": None, "exception_type": "ToolError"}
        ((args, kwargs),) = memory
        assert args == ("problems_solutions", "step_two",
                        "FAILED | problem: step two | cause: controlled_tool_dispatch_failure"
                        " | solution: step two | outcome: failed:ToolError")
        assert kwargs == {"importance": 3, "confidence": 0.5, "project": None, "source": "solver"}
        (ref,) = a.reflection.get_all()
        assert (ref.subject, ref.what_failed, ref.what_worked, ref.confidence_level) == (
            failed.id, "controlled_tool_dispatch:step two", "", 0.0)
        assert ref.completion_summary == "Execution attempt failed (ToolError) under controlled tool dispatch."
        assert ref.metadata == meta
        (learn,) = a.learning.get_all()
        assert (learn.subject, learn.detail) == (
            "step two", "Execution attempt failed (ToolError) under controlled tool dispatch.")
        assert learn.metadata == meta

    def test_run_id_is_the_v8_23_run(self) -> None:
        a, _, _ = fail_step_two()
        (run,) = a.pipeline_run_manager.list_runs()
        assert run.status is R.FAILED
        assert a.learning.get_all()[0].metadata["run_id"] == run.id
        assert run.pipeline_reference == a.pipeline_engine.list_pipelines()[0].id

    def test_project_recorded(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            a.execute_projection_with_writeback("fix the wifi", project="home")
        assert memory[0][1]["project"] == "home"
        assert a.learning.get_all()[0].metadata["project"] == "home"

    def test_order_memory_reflection_learning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        order: list[str] = []
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("memory") or "id")
        orig_r, orig_l = a.reflection.add_reflection, a.learning.record_failed_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("reflection") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_failed_pattern", lambda **k: order.append("learning") or orig_l(**k))
        with pytest.raises(ToolError):
            a.execute_projection_with_writeback("fix the wifi")
        assert order == ["memory", "reflection", "learning"]

    def test_writeback_after_run_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        seen: list[object] = []
        monkeypatch.setattr(problem_solver, "remember",
                            lambda *x, **k: seen.append(a.pipeline_run_manager.list_runs()[0].status) or "id")
        with pytest.raises(ToolError):
            a.execute_projection_with_writeback("fix the wifi")
        assert seen == [R.FAILED]

    def test_exception_text_never_persisted(self, memory: list) -> None:
        a, _, _ = fail_step_two(exc=RuntimeError({"token": "tok-123"}, SECRET))
        dumped = repr((memory, a.reflection.get_all(), a.learning.get_all()))
        for fragment in ("SECRET-9f2c", "api_key", "/home/alice", "tok-123", "Traceback"):
            assert fragment not in dumped, fragment
        assert a.learning.get_all()[0].metadata["exception_type"] == "RuntimeError"

    def test_single_writeback_per_attempt(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        calls: list[object] = []
        original = a._record_failure_outcome  # noqa: SLF001
        monkeypatch.setattr(a, "_record_failure_outcome", lambda *x, **k: calls.append(k) or original(*x, **k))
        with pytest.raises(ToolError):
            a.execute_projection_with_writeback("fix the wifi")
        assert len(calls) == 1 and len(memory) == 1

    def test_each_attempt_writes_once(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        for _ in range(2):
            with pytest.raises(ToolError):
                a.execute_projection_with_writeback("fix the wifi")
        assert len(memory) == 2 and a.reflection_engine.count() == 2
        assert a.learning.get_all()[0].occurrence_count == 2  # existing merge semantics


class TestStages:
    def test_earlier_stages_keep_existing_behaviour_no_success_record(self, memory: list) -> None:
        # Unchanged v8.24 behaviour: success writeback runs only for a COMPLETED
        # run, so stages that succeeded before the failure get no success record.
        a, _, _ = fail_step_two()
        assert not [m for m in memory if m[0][2].startswith("SOLVED")]
        assert not [r for r in a.reflection.get_all() if r.what_worked]
        assert not [r for r in a.learning.get_all() if r.category is LearningCategory.SUCCESSFUL_PATTERN]

    def test_failed_stage_is_the_subject(self) -> None:
        a, _, _ = fail_step_two()
        assert a.learning.get_all()[0].subject == "step two"

    def test_later_stages_never_dispatched_or_recorded(self, memory: list) -> None:
        a, _, three = fail_step_two()
        assert three.calls == 0
        dumped = repr((memory, a.reflection.get_all(), a.learning.get_all()))
        assert "step three" not in dumped and "step_three" not in dumped

    def test_skipped_stage_before_failure_is_not_the_failed_stage(self) -> None:
        a = agent_with(Failing("step two", ToolError("x")))  # step one unregistered -> skipped
        with pytest.raises(ToolError):
            a.execute_projection_with_writeback(THREE)
        assert a.learning.get_all()[0].subject == "step two"


class TestOriginalExceptionWins:
    @pytest.mark.parametrize("layer", ["memory", "reflection", "learning", "lookup"])
    def test_failing_writeback_does_not_mask(self, layer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = ToolError("original")
        a = agent_with(Failing("fix the wifi", exc))

        def boom(*x, **k):
            raise ValueError("writeback broke")

        target = {"memory": (problem_solver, "remember"),
                  "reflection": (a.reflection, "add_reflection"),
                  "learning": (a.learning, "record_failed_pattern"),
                  "lookup": (agent_module, "normalize_execution_failure")}[layer]
        monkeypatch.setattr(*target, boom)
        with pytest.raises(ToolError) as info:
            a.execute_projection_with_writeback("fix the wifi")
        assert info.value is exc
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED

    def test_interrupt_propagates_and_is_recorded(self, memory: list) -> None:
        a, _, _ = fail_step_two(exc=KeyboardInterrupt())
        assert a.learning.get_all()[0].metadata["exception_type"] == "KeyboardInterrupt"


class TestNotExecutionFailures:
    def test_projection_failure_no_writeback(self, memory: list) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(InvalidGoalError):
            a.execute_projection_with_writeback("   ")
        assert memory == [] and a.reflection_engine.count() == 0 and a.pipeline_run_manager.count() == 0

    def test_failure_before_run_running_no_writeback(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        exc = ValueError("setup")
        monkeypatch.setattr(agent_module, "build_stage_dispatch_decisions",
                            lambda *x, **k: (_ for _ in ()).throw(exc))
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(ValueError) as info:
            a.execute_projection_with_writeback("fix the wifi")
        assert info.value is exc
        assert a.pipeline_run_manager.list_runs()[0].status is R.CREATED
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []


# ── unchanged behaviour ─────────────────────────────────────────────────


class TestUnchanged:
    def test_v8_24_success_unchanged(self, memory: list) -> None:
        tools = ("step one", "step two")
        a = agent_with(*(StaticMockTool(name=n) for n in tools))
        b = agent_with(*(StaticMockTool(name=n) for n in tools))
        _, r1, d1, t1 = a.execute_projection_with_writeback(THREE, project="p")
        first = list(memory)
        memory.clear()
        _, r2, d2, t2 = b.execute_projection_with_lifecycle(THREE, project="p")
        # Same success records as the lifecycle path (itself pinned to v8.24).
        assert first == memory and (d1, t1) == (d2, t2) and r1.status is R.COMPLETED
        assert [m[0][2].split(" |")[0] for m in first] == ["SOLVED", "SOLVED"]
        assert {r.category for r in a.learning.get_all()} == {LearningCategory.SUCCESSFUL_PATTERN}

    def test_v8_24_all_skipped_writes_nothing(self, memory: list) -> None:
        a = Agent()
        _, run, _, _ = a.execute_projection_with_writeback(THREE)
        assert run.status is R.COMPLETED and memory == [] and a.learning.get_all() == []

    def test_v8_27_and_v8_24_failure_records_share_one_shape(self, memory: list) -> None:
        a, _, _ = fail_step_two("execute_projection_with_lifecycle")
        lifecycle = records(a, memory)
        memory.clear()
        b, _, _ = fail_step_two("execute_projection_with_writeback")
        assert records(b, memory) == lifecycle

    def test_v8_27_fallback_unchanged(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        # Lifecycle still derives the failed stage from the ACTIVE step: when the
        # step write fails first, the record falls back to the goal (v8.27).
        monkeypatch.setattr(agent_module, "reflect_step_reached",
                            lambda *x, **k: (_ for _ in ()).throw(RuntimeError("store")))
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(RuntimeError):
            a.execute_projection_with_lifecycle("fix the wifi")
        (ref,) = a.reflection.get_all()
        assert ref.subject == a.goal_manager.list_goals()[0].id and ref.metadata["task_id"] is None

    @pytest.mark.parametrize("method", ["execute_projection_with_tool_dispatch",
                                        "execute_projection_with_run_status"])
    def test_v8_22_v8_23_still_write_nothing(self, method: str, memory: list) -> None:
        a = agent_with(StaticMockTool(name="step one"), Failing("step two", ToolError("x")))
        with pytest.raises(ToolError):
            getattr(a, method)(THREE)
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_v8_20_failure_is_a_single_v8_29_record(self, memory: list) -> None:
        # v8.28 left v8.20 untouched; v8.29 gives it exactly one failure
        # record (full contract: tests/test_failure_writeback_v8_20.py).
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(memory) == 1 and a.reflection_engine.count() == 1
        assert a.learning.get_all()[0].metadata["run_id"] is None

    def test_statuses_unchanged_by_v8_24_failure(self) -> None:
        a, _, _ = fail_step_two()
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED
        assert a.goal_manager.list_goals()[0].status is G.DRAFT  # v8.24 never transitions
        plan = a.planning_engine.list_plans()[0]
        assert plan.status is P.DRAFT and [s.status for s in plan.steps] == [P.DRAFT] * 3

    def test_no_new_status_values(self) -> None:
        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5

    def test_dispatch_log_only_set_by_v8_24(self) -> None:
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(agent_module))
        setters = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for c in ast.walk(fn) if isinstance(c, ast.Call)
                   and getattr(c.func, "attr", None) == "_run_projected_pipeline"
                   and any(k.arg == "dispatched" for k in c.keywords)}
        assert setters == {"execute_projection_with_writeback"}
        sig = inspect.signature(Agent._run_projected_pipeline)
        assert sig.parameters["dispatched"].default is None

    def test_public_api_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
