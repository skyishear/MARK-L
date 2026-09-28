"""Tests for v8.29 failure writeback on the v8.20 tool-chain path
(``Agent.execute_request_with_tool_dispatch_writeback``).

Contract: an exception raised by ``ToolRouter.route`` for the in-flight
decision (the v8.20 execution boundary) gets exactly one structured failure
writeback through the shared writer (Memory -> Reflection -> Learning),
built from a v8.28 ``ExecutionFailure`` with ``run_id=None`` (no
``PipelineRun`` exists on this path; nothing is invented) and
``goal_id`` / ``plan_id`` ``None``; the original exception always
propagates; failures before any routing write nothing; no success record
for a failed attempt; v8.19 results and every other path unchanged.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

import core.agent as agent_module
from core import problem_solver
from core.agent import Agent
from core.agent.learning_manager import LearningCategory
from core.execution_failure import ExecutionFailure, normalize_execution_failure
from core.goal_manager import GoalStatus
from core.pipeline_run import ALLOWED_TRANSITIONS, PipelineRunStatus
from core.planner import InvalidGoalError
from core.planning_engine import PlanStatus
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult

G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
SECRET = "api_key=SECRET-9f2c /home/alice/private.txt"
META_KEYS = ["run_id", "goal_id", "plan_id", "task_id", "project", "exception_type"]


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


class Desc:
    def __init__(self, task_id: str, problem: str) -> None:
        self.task_id = task_id
        self.work_item = type("W", (), {"problem": problem})()


def force_ready(monkeypatch: pytest.MonkeyPatch, agent: Agent, *problems: str) -> None:
    descs = tuple(Desc(f"t{i}", pr) for i, pr in enumerate(problems, 1))
    monkeypatch.setattr(agent, "coordinate_execution",
                        lambda session: type("Coord", (), {"ready_descriptors": descs})())


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


def fail_two_of_three(monkeypatch: pytest.MonkeyPatch, exc: BaseException | None = None, project=None):
    exc = exc or ToolError(SECRET)
    three = Counting("three")
    a = agent_with(StaticMockTool(name="one"), Failing("two", exc), three)
    force_ready(monkeypatch, a, "one", "two", "three")
    with pytest.raises(type(exc)) as info:
        a.execute_request_with_tool_dispatch_writeback("g", project=project)
    assert info.value is exc
    return a, exc, three


# ── exactly one structured failure writeback ────────────────────────────


class TestFailureWriteback:
    def test_exactly_one_record_per_layer(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a, _, _ = fail_two_of_three(monkeypatch)
        assert len(memory) == 1 and a.reflection_engine.count() == 1
        (rec,) = a.learning.get_all()
        assert rec.category is LearningCategory.FAILED_PATTERN and rec.occurrence_count == 1

    def test_exact_content(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a, _, _ = fail_two_of_three(monkeypatch, project="home")
        meta = {"run_id": None, "goal_id": None, "plan_id": None, "task_id": "t2",
                "project": "home", "exception_type": "ToolError"}
        ((args, kwargs),) = memory
        assert args == ("problems_solutions", "two",
                        "FAILED | problem: two | cause: controlled_tool_dispatch_failure"
                        " | solution: two | outcome: failed:ToolError")
        assert kwargs == {"importance": 3, "confidence": 0.5, "project": "home", "source": "solver"}
        (ref,) = a.reflection.get_all()
        assert (ref.subject, ref.what_failed, ref.what_worked, ref.confidence_level) == (
            "t2", "controlled_tool_dispatch:two", "", 0.0)
        assert ref.completion_summary == "Execution attempt failed (ToolError) under controlled tool dispatch."
        assert ref.metadata == meta and list(ref.metadata) == META_KEYS
        (learn,) = a.learning.get_all()
        assert (learn.subject, learn.detail) == (
            "two", "Execution attempt failed (ToolError) under controlled tool dispatch.")
        assert learn.metadata == meta and list(learn.metadata) == META_KEYS

    def test_run_goal_plan_ids_are_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, _, _ = fail_two_of_three(monkeypatch)
        meta = a.learning.get_all()[0].metadata
        assert meta["run_id"] is None and meta["goal_id"] is None and meta["plan_id"] is None
        assert a.pipeline_run_manager.count() == 0  # no PipelineRun introduced

    def test_same_shape_as_v8_27_and_v8_28(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a, _, _ = fail_two_of_three(monkeypatch)
        b = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            b.execute_projection_with_writeback("fix the wifi")
        r20, r24 = a.reflection.get_all()[0], b.reflection.get_all()[0]
        assert list(r20.metadata) == list(r24.metadata) == META_KEYS
        assert memory[0][1] == memory[1][1] | {"project": None}
        assert (r20.what_worked, r20.confidence_level) == (r24.what_worked, r24.confidence_level)

    def test_exception_type_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class CustomToolBoom(ToolError):
            pass

        a, _, _ = fail_two_of_three(monkeypatch, CustomToolBoom(SECRET))
        assert a.learning.get_all()[0].metadata["exception_type"] == "CustomToolBoom"

    @pytest.mark.parametrize("exc", [
        ToolError(SECRET),
        RuntimeError({"token": "tok-123"}, "password=hunter2"),
    ])
    def test_no_message_repr_args_or_traceback(self, exc: BaseException, monkeypatch: pytest.MonkeyPatch,
                                               memory: list) -> None:
        a, _, _ = fail_two_of_three(monkeypatch, exc)
        dumped = repr((memory, a.reflection.get_all(), a.learning.get_all()))
        for fragment in ("SECRET-9f2c", "api_key", "/home/alice", "tok-123", "hunter2", "Traceback",
                         repr(exc)):
            assert fragment not in dumped, fragment

    def test_failure_value_never_retains_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[ExecutionFailure] = []

        def spy(exc, **k):
            f = normalize_execution_failure(exc, **k)
            seen.append(f)
            return f

        monkeypatch.setattr(agent_module, "normalize_execution_failure", spy)
        _, exc, _ = fail_two_of_three(monkeypatch)
        (f,) = seen
        assert f == ExecutionFailure("ToolError", None, "two", None)
        assert not any(v is exc for v in dataclasses.astuple(f))

    def test_order_memory_reflection_learning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        order: list[str] = []
        monkeypatch.setattr(problem_solver, "remember", lambda *x, **k: order.append("memory") or "id")
        orig_r, orig_l = a.reflection.add_reflection, a.learning.record_failed_pattern
        monkeypatch.setattr(a.reflection, "add_reflection", lambda **k: order.append("reflection") or orig_r(**k))
        monkeypatch.setattr(a.learning, "record_failed_pattern", lambda **k: order.append("learning") or orig_l(**k))
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert order == ["memory", "reflection", "learning"]

    def test_single_writeback_per_attempt(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        calls: list[object] = []
        original = a._record_failure_outcome  # noqa: SLF001
        monkeypatch.setattr(a, "_record_failure_outcome", lambda *x, **k: calls.append(x) or original(*x, **k))
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(calls) == 1 and calls[0][0] is None and len(memory) == 1

    def test_each_attempt_writes_once(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        for _ in range(2):
            with pytest.raises(ToolError):
                a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert len(memory) == 2 and a.reflection_engine.count() == 2
        assert a.learning.get_all()[0].occurrence_count == 2  # existing merge semantics

    def test_interrupt_propagates_and_is_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, _, _ = fail_two_of_three(monkeypatch, KeyboardInterrupt())
        assert a.learning.get_all()[0].metadata["exception_type"] == "KeyboardInterrupt"


class TestStages:
    def test_failed_stage_named_and_earlier_success_not_recorded(self, monkeypatch: pytest.MonkeyPatch,
                                                                 memory: list) -> None:
        a, _, _ = fail_two_of_three(monkeypatch)
        assert a.learning.get_all()[0].subject == "two"
        assert not [m for m in memory if m[0][2].startswith("SOLVED")]
        assert not [r for r in a.reflection.get_all() if r.what_worked]

    def test_later_stages_never_dispatched_or_recorded(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a, _, three = fail_two_of_three(monkeypatch)
        assert three.calls == 0
        assert "three" not in repr((memory, a.reflection.get_all(), a.learning.get_all()))

    def test_skipped_decision_is_not_the_failed_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a = agent_with(Failing("two", ToolError("x")))  # "one" unregistered -> skipped
        force_ready(monkeypatch, a, "one", "two")
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch_writeback("g")
        assert a.learning.get_all()[0].subject == "two"


class TestOriginalExceptionWins:
    @pytest.mark.parametrize("layer", ["memory", "reflection", "learning", "normalize"])
    def test_failing_writeback_does_not_mask(self, layer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = ToolError("original")
        a = agent_with(Failing("fix the wifi", exc))

        def boom(*x, **k):
            raise ValueError("writeback broke")

        target = {"memory": (problem_solver, "remember"),
                  "reflection": (a.reflection, "add_reflection"),
                  "learning": (a.learning, "record_failed_pattern"),
                  "normalize": (agent_module, "normalize_execution_failure")}[layer]
        monkeypatch.setattr(*target, boom)
        with pytest.raises(ToolError) as info:
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert info.value is exc


class TestNotExecutionFailures:
    def test_planning_failure_no_writeback(self, memory: list) -> None:
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(InvalidGoalError):
            a.execute_request_with_tool_dispatch_writeback("   ")
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    @pytest.mark.parametrize("stage", ["create_execution_session", "coordinate_execution"])
    def test_pre_routing_failure_no_writeback(self, stage: str, monkeypatch: pytest.MonkeyPatch,
                                              memory: list) -> None:
        exc = ValueError("setup")
        a = agent_with(StaticMockTool(name="fix the wifi"))
        monkeypatch.setattr(a, stage, lambda *x, **k: (_ for _ in ()).throw(exc))
        with pytest.raises(ValueError) as info:
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert info.value is exc
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    def test_decision_building_failure_no_writeback(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        monkeypatch.setattr(agent_module, "build_tool_dispatch_decision",
                            lambda *x, **k: (_ for _ in ()).throw(ValueError("decide")))
        a = agent_with(StaticMockTool(name="fix the wifi"))
        with pytest.raises(ValueError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert memory == []

    def test_request_construction_failure_after_success_no_writeback(self, monkeypatch: pytest.MonkeyPatch,
                                                                     memory: list) -> None:
        # A failure raised outside ``route`` (here: building the second
        # request) is not an execution failure, even after a successful route.
        a = agent_with(StaticMockTool(name="one"), StaticMockTool(name="two"))
        force_ready(monkeypatch, a, "one", "two")
        real = agent_module.ToolRequest

        def request(**k):
            if k["tool_name"] == "two":
                raise ValueError("bad request")
            return real(**k)

        monkeypatch.setattr(agent_module, "ToolRequest", request)
        with pytest.raises(ValueError):
            a.execute_request_with_tool_dispatch_writeback("g")
        assert memory == [] and a.learning.get_all() == []

    def test_zero_ready_descriptors_write_nothing(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = Agent()
        force_ready(monkeypatch, a)
        a.execute_request_with_tool_dispatch_writeback("g")
        assert memory == []


# ── unchanged behaviour ─────────────────────────────────────────────────


class TestUnchanged:
    def test_v8_20_success_unchanged(self, monkeypatch: pytest.MonkeyPatch, memory: list) -> None:
        a = agent_with(StaticMockTool(name="one"), StaticMockTool(name="two"))
        b = agent_with(StaticMockTool(name="one"), StaticMockTool(name="two"))
        force_ready(monkeypatch, a, "one", "two")
        force_ready(monkeypatch, b, "one", "two")
        r1, d1, t1 = a.execute_request_with_tool_dispatch_writeback("g", project="p")
        r2, d2, t2 = b.execute_request_with_tool_dispatch("g", project="p")
        assert (r1.session_id, d1, t1) == (r2.session_id, d2, t2)
        assert [m[0][2] for m in memory] == [
            "SOLVED | problem: one | cause: controlled_tool_dispatch | solution: one | outcome: success",
            "SOLVED | problem: two | cause: controlled_tool_dispatch | solution: two | outcome: success"]
        assert [(r.category, r.subject, r.metadata) for r in a.learning.get_all()] == [
            (LearningCategory.SUCCESSFUL_PATTERN, "one", {"task_id": "t1", "project": "p", "output": t1[0].output}),
            (LearningCategory.SUCCESSFUL_PATTERN, "two", {"task_id": "t2", "project": "p", "output": t1[1].output}),
        ]

    def test_v8_19_plain_dispatch_still_writes_nothing(self, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch("fix the wifi")
        assert memory == [] and a.reflection_engine.count() == 0 and a.learning.get_all() == []

    @pytest.mark.parametrize("method", ["execute_projection_with_tool_dispatch",
                                        "execute_projection_with_run_status"])
    def test_v8_22_v8_23_still_write_nothing(self, method: str, memory: list) -> None:
        a = agent_with(Failing("fix the wifi", ToolError("x")))
        with pytest.raises(ToolError):
            getattr(a, method)("fix the wifi")
        assert memory == [] and a.reflection_engine.count() == 0

    def test_v8_27_and_v8_28_records_keep_their_ids(self, memory: list) -> None:
        for method in ("execute_projection_with_lifecycle", "execute_projection_with_writeback"):
            a = agent_with(Failing("fix the wifi", ToolError("x")))
            with pytest.raises(ToolError):
                getattr(a, method)("fix the wifi")
            meta = a.learning.get_all()[0].metadata
            assert meta["run_id"] == a.pipeline_run_manager.list_runs()[0].id
            assert meta["goal_id"] == a.goal_manager.list_goals()[0].id
            assert meta["plan_id"] == a.planning_engine.list_plans()[0].id

    def test_no_new_status_values(self) -> None:
        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5

    def test_failing_tool_routed_once_no_retry(self) -> None:
        tool = Failing("fix the wifi", ToolError("x"))
        a = agent_with(tool)
        with pytest.raises(ToolError):
            a.execute_request_with_tool_dispatch_writeback("fix the wifi")
        assert tool.calls == 1
        for name in dir(Agent):
            if name in {"resume_failed_run", "_prepare_resume", "_route_with_transient_retry"}:  # v8.32 / v8.33 sanctioned
                continue
            assert not any(w in name.lower() for w in ("retry", "resume", "attempt")), name


class TestArchitecture:
    def test_public_signatures_unchanged(self) -> None:
        for name in ("execute_request_with_tool_dispatch", "execute_request_with_tool_dispatch_writeback"):
            params = list(inspect.signature(getattr(Agent, name)).parameters)
            assert params == ["self", "goal", "project", "metadata"], name

    def test_routing_log_only_set_by_v8_20(self) -> None:
        tree = ast.parse(inspect.getsource(agent_module))
        setters = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for c in ast.walk(fn) if isinstance(c, ast.Call)
                   and getattr(c.func, "attr", None) == "_run_tool_dispatch_chain"
                   and any(k.arg == "routing" for k in c.keywords)}
        assert setters == {"execute_request_with_tool_dispatch_writeback"}
        assert inspect.signature(Agent._run_tool_dispatch_chain).parameters["routing"].default is None

    def test_single_shared_writer(self) -> None:
        tree = ast.parse(inspect.getsource(agent_module))
        writers = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                   for c in ast.walk(fn) if isinstance(c, ast.Call)
                   and getattr(c.func, "attr", None) == "record_failed_pattern"}
        assert writers == {"_record_failure_outcome"}

    def test_public_api_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
