"""Tests for v8.33 bounded in-run retry (owner policy O5, locked).

O5: only TRANSIENT failures (type-based: ``TransientToolError``) are retried;
at most 2 retries (3 invocations per step, hard bound); no delay; the step
stays ACTIVE during retry; the FINAL attempt's exception is re-raised
unchanged; exactly one failure writeback after exhaustion, none for
intermediate failures; UNKNOWN is never retried. Only the lifecycle path and
``resume_failed_run`` opt in; every other path routes exactly once.
"""

from __future__ import annotations

import ast
import inspect
import time

import pytest

import core.agent as agent_module
import core.failure_taxonomy as taxonomy_module
from core import problem_solver
from core.agent import Agent
from core.agent.learning_manager import LearningCategory
from core.failure_taxonomy import FailureCategory, classify_failure
from core.goal_manager import GoalStatus
from core.pipeline_run import ALLOWED_TRANSITIONS, PipelineRunStatus
from core.planning_engine import PlanStatus
from core.tool_catalog import ToolSpec
from core.tool_interface import ToolError, ToolRequest, ToolResult, TransientToolError
from core.tool_router import ToolNotFoundError, ToolRouter

G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
C = FailureCategory
THREE = "step one then step two then step three"
SECRET = "api_key=SECRET-9f2c /home/alice/private.txt"


class Scripted:
    """Returns / raises the scripted outcomes in order; records every call."""

    def __init__(self, name: str, *outcomes: object, observer=None) -> None:
        self.name = name
        self.description = "d"
        self.outcomes = list(outcomes)
        self.calls = 0
        self.results: list[ToolResult] = []
        self.observer = observer

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        if self.observer is not None:
            self.observer()
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, BaseException):
            raise outcome
        result = ToolResult(request.tool_name, f"{self.name} {outcome}")
        self.results.append(result)
        return result


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


def steps(a: Agent) -> list[PlanStatus]:
    return [s.status for s in a.planning_engine.list_plans()[-1].steps]


def failures(memory: list) -> list[str]:
    return [m[0][2] for m in memory if m[0][2].startswith("FAILED")]


def run_single(*outcomes: object):
    tool = Scripted("fix the wifi", *outcomes)
    a = agent_with(tool)
    return a, tool


# ── taxonomy ────────────────────────────────────────────────────────────


class TestTaxonomy:
    def test_transient_signal_is_explicit_and_type_based(self) -> None:
        classify = agent_module._classify_execution_failure  # noqa: SLF001
        assert classify(TransientToolError(SECRET)) is C.TRANSIENT
        assert issubclass(TransientToolError, ToolError)

        class MyTransient(TransientToolError): ...
        assert classify(MyTransient()) is C.TRANSIENT

    @pytest.mark.parametrize("exc", [ToolError("x"), RuntimeError(), TimeoutError(), ConnectionError(),
                                     OSError(), ValueError(), KeyboardInterrupt()])
    def test_everything_else_is_not_transient(self, exc: BaseException) -> None:
        assert agent_module._classify_execution_failure(exc) is not C.TRANSIENT  # noqa: SLF001

    def test_classification_never_reads_text(self) -> None:
        class Hostile(TransientToolError):
            @property
            def args(self):  # type: ignore[override]
                raise AssertionError("args read")

            def __str__(self) -> str:
                raise AssertionError("str read")

            def __repr__(self) -> str:
                raise AssertionError("repr read")

        assert agent_module._classify_execution_failure(Hostile()) is C.TRANSIENT  # noqa: SLF001

    def test_taxonomy_leaf_unchanged(self) -> None:
        assert [c.value for c in C] == ["transient", "permanent", "invalid_input", "unknown"]
        assert classify_failure(ValueError(), {}) is C.UNKNOWN
        assert taxonomy_module.__all__ == ["FailureCategory", "classify_failure"]


# ── lifecycle path: the O5 matrix ───────────────────────────────────────


class TestRetryMatrix:
    def test_first_attempt_succeeds_no_retry(self, memory: list) -> None:
        a, tool = run_single("ok")
        _, run, _, results = a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 1 and run.status is R.COMPLETED
        assert results == (tool.results[0],) and failures(memory) == []

    def test_transient_then_success(self, memory: list) -> None:
        a, tool = run_single(TransientToolError(SECRET), "ok")
        _, run, _, results = a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 2 and run.status is R.COMPLETED
        assert len(results) == 1 and results[0] is tool.results[0]  # the real result, not synthetic
        assert steps(a) == [P.COMPLETED] and failures(memory) == []
        assert [m[0][2].split(" | ")[0] for m in memory] == ["SOLVED"]

    def test_two_transients_then_success(self, memory: list) -> None:
        a, tool = run_single(TransientToolError(), TransientToolError(), "ok")
        _, run, _, results = a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 3 and run.status is R.COMPLETED
        assert results[0] is tool.results[0] and steps(a) == [P.COMPLETED] and failures(memory) == []

    def test_three_transients_exhaust(self, memory: list) -> None:
        final = TransientToolError(SECRET)
        a, tool = run_single(TransientToolError("1"), TransientToolError("2"), final, "never")
        with pytest.raises(TransientToolError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is final and tool.calls == 3
        assert a.pipeline_run_manager.list_runs()[0].status is R.FAILED
        assert steps(a) == [P.ACTIVE]
        assert failures(memory) == ["FAILED | problem: fix the wifi | cause: controlled_tool_dispatch_failure"
                                    " | solution: fix the wifi | outcome: failed:TransientToolError"]
        assert a.reflection_engine.count() == 1
        (rec,) = a.learning.get_all()
        assert rec.category is LearningCategory.FAILED_PATTERN and rec.metadata["exception_type"] == "TransientToolError"

    @pytest.mark.parametrize("exc", [ToolNotFoundError("permanent"), ToolError("unknown"), RuntimeError("unknown")])
    def test_non_transient_first_failure_not_retried(self, exc: BaseException, memory: list) -> None:
        a, tool = run_single(exc, "ok")
        with pytest.raises(type(exc)) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc and tool.calls == 1 and len(failures(memory)) == 1

    def test_invalid_input_first_failure_not_retried(self, memory: list) -> None:
        from core.planner import PlanValidationError

        exc = PlanValidationError("bad")
        a, tool = run_single(exc, "ok")
        assert agent_module._classify_execution_failure(exc) is C.INVALID_INPUT  # noqa: SLF001
        with pytest.raises(PlanValidationError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is exc and tool.calls == 1

    def test_transient_transient_permanent(self, memory: list) -> None:
        final = ToolNotFoundError("gone")
        a, tool = run_single(TransientToolError(), TransientToolError(), final, "never")
        with pytest.raises(ToolNotFoundError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is final and tool.calls == 3
        assert failures(memory) == ["FAILED | problem: fix the wifi | cause: controlled_tool_dispatch_failure"
                                    " | solution: fix the wifi | outcome: failed:ToolNotFoundError"]

    def test_transient_then_permanent_stops(self, memory: list) -> None:
        final = ToolError("unknown category")
        a, tool = run_single(TransientToolError(), final, "never")
        with pytest.raises(ToolError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is final and tool.calls == 2 and len(failures(memory)) == 1
        assert a.learning.get_all()[0].metadata["exception_type"] == "ToolError"

    def test_interrupt_never_retried(self) -> None:
        a, tool = run_single(KeyboardInterrupt(), "ok")
        with pytest.raises(KeyboardInterrupt):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 1


# ── hard bound, identity, no delay ──────────────────────────────────────


class TestBound:
    def test_fourth_invocation_impossible_even_if_everything_were_transient(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(agent_module, "_classify_execution_failure", lambda exc: C.TRANSIENT)
        a, tool = run_single(*(RuntimeError(str(i)) for i in range(10)))
        with pytest.raises(RuntimeError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 3 and str(info.value) == "2"  # the third attempt's own exception

    @pytest.mark.parametrize("script", [
        (TransientToolError(),) * 5,
        (TransientToolError(), TransientToolError(), "ok"),
        (TransientToolError(), ToolError()),
        ("ok",),
    ])
    def test_at_most_three_invocations_per_step(self, script: tuple) -> None:
        a, tool = run_single(*script)
        try:
            a.execute_projection_with_lifecycle("fix the wifi")
        except ToolError:
            pass
        assert 1 <= tool.calls <= 3

    def test_no_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("slept")))
        a, tool = run_single(TransientToolError(), TransientToolError(), "ok")
        a.execute_projection_with_lifecycle("fix the wifi")
        assert tool.calls == 3


# ── lifecycle semantics during retry ────────────────────────────────────


class TestLifecycleDuringRetry:
    def test_step_stays_active_across_attempts(self) -> None:
        seen: list[list[PlanStatus]] = []
        a = Agent()
        tool = Scripted("fix the wifi", TransientToolError(), TransientToolError(), "ok",
                        observer=lambda: seen.append(steps(a)))
        a.tool_registry.register(tool)
        a.execute_projection_with_lifecycle("fix the wifi")
        assert seen == [[P.ACTIVE]] * 3 and steps(a) == [P.COMPLETED]

    def test_step_writes_one_active_one_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, _ = run_single(TransientToolError(), "ok")
        writes: list[tuple] = []
        orig = a.planning_engine.update_plan
        monkeypatch.setattr(a.planning_engine, "update_plan", lambda pid, **k: writes.append(
            tuple(s.status for s in k["steps"]) if "steps" in k else ("plan", k.get("status"))) or orig(pid, **k))
        a.execute_projection_with_lifecycle("fix the wifi")
        assert writes == [("plan", P.ACTIVE), (P.ACTIVE,), (P.COMPLETED,), ("plan", P.COMPLETED)]

    def test_exhaustion_leaves_later_steps_draft(self, memory: list) -> None:
        one = Scripted("step one", "ok")
        two = Scripted("step two", TransientToolError(), TransientToolError(), TransientToolError())
        three = Scripted("step three", "ok")
        a = agent_with(one, two, three)
        with pytest.raises(TransientToolError):
            a.execute_projection_with_lifecycle(THREE)
        assert steps(a) == [P.COMPLETED, P.ACTIVE, P.DRAFT] and three.calls == 0
        assert (one.calls, two.calls) == (1, 3)
        assert a.goal_manager.list_goals()[0].status is G.ACTIVE
        assert a.planning_engine.list_plans()[0].status is P.ACTIVE
        assert len(failures(memory)) == 1 and "problem: step two" in failures(memory)[0]

    def test_retry_in_middle_stage_then_rest(self, memory: list) -> None:
        one, two, three = Scripted("step one"), Scripted("step two", TransientToolError()), Scripted("step three")
        a = agent_with(one, two, three)
        _, run, _, results = a.execute_projection_with_lifecycle(THREE)
        assert (one.calls, two.calls, three.calls) == (1, 2, 1)
        assert [r.output for r in results] == ["step one ok", "step two ok", "step three ok"]
        assert run.status is R.COMPLETED and a.pipeline_run_manager.count() == 1
        assert failures(memory) == [] and len([m for m in memory if m[0][2].startswith("SOLVED")]) == 3

    def test_no_writeback_before_final_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[str] = []
        a = Agent()
        tool = Scripted("fix the wifi", TransientToolError(), TransientToolError(), TransientToolError(),
                        observer=lambda: events.append("invoke"))
        a.tool_registry.register(tool)
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: events.append("memory") or "id")
        orig_r = a.reflection.add_reflection
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: events.append("reflection") or orig_r(**k))
        orig_l = a.learning.record_failed_pattern
        monkeypatch.setattr(a.learning, "record_failed_pattern", lambda **k: events.append("learning") or orig_l(**k))
        with pytest.raises(TransientToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert events == ["invoke", "invoke", "invoke", "memory", "reflection", "learning"]

    def test_run_transitions_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, _ = run_single(TransientToolError(), "ok")
        events: list[object] = []
        orig = a.pipeline_run_manager.update_run
        monkeypatch.setattr(a.pipeline_run_manager, "update_run",
                            lambda rid, **k: events.append(k.get("status")) or orig(rid, **k))
        a.execute_projection_with_lifecycle("fix the wifi")
        assert events == [R.RUNNING, R.COMPLETED]

    @pytest.mark.parametrize("layer", ["memory", "reflection", "learning"])
    def test_writeback_failure_cannot_mask_final_exception(self, layer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        final = TransientToolError("final")
        a, tool = run_single(TransientToolError(), TransientToolError(), final)

        def boom(*x, **k):
            raise ValueError("writeback broke")

        target = {"memory": (problem_solver, "remember"),
                  "reflection": (a.reflection, "add_reflection"),
                  "learning": (a.learning, "record_failed_pattern")}[layer]
        monkeypatch.setattr(*target, boom)
        with pytest.raises(TransientToolError) as info:
            a.execute_projection_with_lifecycle("fix the wifi")
        assert info.value is final and tool.calls == 3

    def test_final_record_has_no_exception_text(self, memory: list) -> None:
        a, _ = run_single(TransientToolError(SECRET), TransientToolError(SECRET), TransientToolError(SECRET))
        with pytest.raises(TransientToolError):
            a.execute_projection_with_lifecycle("fix the wifi")
        assert "SECRET-9f2c" not in repr((memory, a.reflection.get_all(), a.learning.get_all()))


# ── v8.32 resume ────────────────────────────────────────────────────────


class TestResume:
    def _failed(self, *two_outcomes: object):
        one, two, three = Scripted("step one"), Scripted("step two", *two_outcomes), Scripted("step three")
        a = agent_with(one, two, three)
        with pytest.raises(BaseException):
            a.execute_projection_with_lifecycle(THREE)
        a.tool_catalog.register(ToolSpec("step two", "d", {"type": "object"}, idempotent=True))
        return a, (one, two, three), a.pipeline_run_manager.list_runs()[0]

    def test_resumed_step_retries_within_one_new_run(self, memory: list) -> None:
        # Original attempt: ToolError (not transient) -> 1 call, FAILED.
        a, (one, two, three), old = self._failed(ToolError("x"), TransientToolError(), "ok")
        assert two.calls == 1
        memory.clear()
        _, new, _, results = a.resume_failed_run(old.id)
        assert two.calls == 3 and one.calls == 1 and three.calls == 1
        assert new.status is R.COMPLETED and a.pipeline_run_manager.count() == 2
        assert steps(a) == [P.COMPLETED] * 3 and failures(memory) == []
        assert [r.output for r in results] == ["step two ok", "step three ok"]

    def test_resumed_exhaustion_one_failure_record(self, memory: list) -> None:
        final = TransientToolError("final")
        a, (_, two, three), old = self._failed(ToolError("x"), TransientToolError(), TransientToolError(), final)
        memory.clear()
        with pytest.raises(TransientToolError) as info:
            a.resume_failed_run(old.id)
        new = a.pipeline_run_manager.list_runs()[-1]
        assert info.value is final and two.calls == 4  # 1 original + 3 in the resumed attempt
        assert a.pipeline_run_manager.count() == 2 and new.status is R.FAILED
        assert steps(a) == [P.COMPLETED, P.ACTIVE, P.DRAFT] and three.calls == 0
        assert len(failures(memory)) == 1
        assert a.learning.get_all()[-1].metadata["run_id"] == new.id

    def test_original_attempt_retries_before_failing(self) -> None:
        a, (_, two, _), old = self._failed(TransientToolError(), TransientToolError(), TransientToolError())
        assert two.calls == 3 and old.status is R.FAILED


# ── other paths unchanged ───────────────────────────────────────────────


class TestOtherPathsUnchanged:
    @pytest.mark.parametrize("method", ["execute_projection_with_tool_dispatch",
                                        "execute_projection_with_run_status",
                                        "execute_projection_with_writeback",
                                        "execute_request_with_tool_dispatch",
                                        "execute_request_with_tool_dispatch_writeback"])
    def test_transient_failure_routed_once(self, method: str) -> None:
        a, tool = run_single(TransientToolError(), "ok")
        with pytest.raises(TransientToolError):
            getattr(a, method)("fix the wifi")
        assert tool.calls == 1

    def test_router_does_not_retry(self) -> None:
        from core.tool_registry import ToolRegistry

        registry = ToolRegistry()
        tool = registry.register(Scripted("t", TransientToolError(), "ok"))
        with pytest.raises(TransientToolError):
            ToolRouter(registry).route(ToolRequest("t", {}))
        assert tool.calls == 1 and not hasattr(ToolRouter, "retry")

    def test_status_vocabularies(self) -> None:
        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5


class TestArchitecture:
    def _node(self, name: str) -> ast.FunctionDef:
        return next(n for n in ast.walk(ast.parse(inspect.getsource(agent_module)))
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_retry_bound_is_a_literal_three(self) -> None:
        src = inspect.getsource(Agent._route_with_transient_retry)
        assert "max_attempts = 3" in src and "range(1, max_attempts + 1)" in src
        node = self._node("_route_with_transient_retry")
        assert not [n for n in ast.walk(node) if isinstance(n, ast.While)]
        calls = {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"range", "route", "_classify_execution_failure", "AssertionError"}

    def test_only_lifecycle_and_resume_opt_in(self) -> None:
        tree = ast.parse(inspect.getsource(agent_module))
        setters = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for c in ast.walk(fn) if isinstance(c, ast.Call)
                   and getattr(c.func, "attr", None) == "_run_projected_pipeline"
                   and any(k.arg == "retry_transient" for k in c.keywords)}
        assert setters == {"execute_projection_with_lifecycle", "resume_failed_run"}
        assert inspect.signature(Agent._run_projected_pipeline).parameters["retry_transient"].default is False

    def test_no_state_sleep_or_async(self) -> None:
        node = self._node("_route_with_transient_retry")
        idents = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
        assert not {"sleep", "time", "asyncio", "Thread", "queue"} & idents
        assert not [n for n in ast.walk(node) if isinstance(n, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef))]

    def test_public_api_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert len(inspect.signature(Agent.__init__).parameters) == 23
        assert list(inspect.signature(Agent.resume_failed_run).parameters) == ["self", "run_id"]
        assert list(inspect.signature(Agent.execute_projection_with_lifecycle).parameters) == [
            "self", "goal", "project"]
