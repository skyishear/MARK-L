"""Tests for v8.30 execution failure taxonomy
(``core.failure_taxonomy`` and the Agent-owned execution rule table).

Contract: a finite, stable ``FailureCategory`` (TRANSIENT / PERMANENT /
INVALID_INPUT / UNKNOWN); classification by exception **class only** (MRO,
most specific first) against caller-supplied rules; anything unmatched is
UNKNOWN. Execution rules (Agent): ``ToolNotFoundError`` -> PERMANENT,
``InvalidGoalError`` / ``PlanValidationError`` -> INVALID_INPUT; no
repository exception is documented as transient, so nothing is TRANSIENT.
Classification is a foundation only: no retry, no resume, no change to
execution, exception propagation or failure records.
"""

from __future__ import annotations

import ast
import dataclasses
import gc
import os
import weakref

import pytest

import core.agent as agent_module
import core.failure_taxonomy as taxonomy_module
from core import problem_solver
from core.agent import Agent
from core.execution_failure import ExecutionFailure
from core.failure_taxonomy import FailureCategory, classify_failure
from core.goal_manager import GoalStatus
from core.pipeline_run import ALLOWED_TRANSITIONS, PipelineRunStatus
from core.planner import InvalidGoalError, PlanValidationError
from core.planning_engine import PlanStatus
from core.tool_interface import StaticMockTool, ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolNotFoundError, ToolRouter

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "failure_taxonomy.py")
C = FailureCategory
classify = agent_module._classify_execution_failure  # noqa: SLF001
SECRET = "token=sk-live-123 timeout rate limit 503 temporarily unavailable"


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


class Hostile(Exception):
    """An exception whose text/args cannot be read without failing."""

    @property
    def args(self):  # type: ignore[override]
        raise AssertionError("args read")

    def __str__(self) -> str:
        raise AssertionError("str read")

    def __repr__(self) -> str:
        raise AssertionError("repr read")


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


# ── vocabulary ──────────────────────────────────────────────────────────


class TestVocabulary:
    def test_categories_and_stable_values(self) -> None:
        assert [(c.name, c.value) for c in C] == [
            ("TRANSIENT", "transient"), ("PERMANENT", "permanent"),
            ("INVALID_INPUT", "invalid_input"), ("UNKNOWN", "unknown")]

    def test_str_enum_convention(self) -> None:
        assert C("unknown") is C.UNKNOWN and C.PERMANENT == "permanent"


# ── mechanism ───────────────────────────────────────────────────────────


class TestClassifier:
    def test_deterministic(self) -> None:
        exc = ToolNotFoundError("x")
        assert {classify(exc) for _ in range(5)} == {C.PERMANENT}

    def test_independent_of_message(self) -> None:
        for msg in ("", SECRET, "invalid input", "permanent"):
            assert classify(ToolNotFoundError(msg)) is C.PERMANENT
            assert classify(RuntimeError(msg)) is C.UNKNOWN

    def test_never_reads_str_repr_or_args(self) -> None:
        assert classify_failure(Hostile(), {Hostile: C.PERMANENT}) is C.PERMANENT
        assert classify(Hostile()) is C.UNKNOWN

    def test_independent_of_traceback(self) -> None:
        bare = ToolNotFoundError("x")
        try:
            raise ToolNotFoundError("x")
        except ToolNotFoundError as caught:
            raised = caught
        assert raised.__traceback__ is not None
        assert classify(bare) is classify(raised) is C.PERMANENT

    def test_does_not_retain_exception(self) -> None:
        exc = ToolNotFoundError("x")
        ref = weakref.ref(exc)
        result = classify(exc)
        del exc
        gc.collect()
        assert ref() is None and result is C.PERMANENT

    def test_most_specific_rule_wins(self) -> None:
        class Base(Exception): ...
        class Child(Base): ...
        class GrandChild(Child): ...
        rules = {Base: C.PERMANENT, Child: C.INVALID_INPUT}
        assert classify_failure(Base(), rules) is C.PERMANENT
        assert classify_failure(Child(), rules) is C.INVALID_INPUT
        assert classify_failure(GrandChild(), rules) is C.INVALID_INPUT

    def test_every_category_representable_by_rules(self) -> None:
        # Mechanism only (test-local classes) -- not production semantics.
        class Local(Exception): ...
        for category in C:
            assert classify_failure(Local(), {Local: category}) is category

    def test_no_rules_is_unknown(self) -> None:
        assert classify_failure(ValueError(), {}) is C.UNKNOWN

    @pytest.mark.parametrize("exc, rules", [
        ("boom", {}),
        (ValueError(), [(ValueError, C.PERMANENT)]),
        (ValueError(), {"ValueError": C.PERMANENT}),
        (ValueError(), {int: C.PERMANENT}),
        (ValueError(), {ValueError: "permanent"}),
    ])
    def test_invalid_arguments(self, exc: object, rules: object) -> None:
        with pytest.raises(TypeError):
            classify_failure(exc, rules)  # type: ignore[arg-type]


# ── execution rules (Agent-owned) ───────────────────────────────────────


class TestExecutionRules:
    def test_tool_not_found_is_permanent(self) -> None:
        router = ToolRouter(ToolRegistry())
        with pytest.raises(ToolNotFoundError) as info:
            router.route(ToolRequest(tool_name="missing", arguments={}))
        assert classify(info.value) is C.PERMANENT

    def test_invalid_goal_is_invalid_input(self) -> None:
        with pytest.raises(InvalidGoalError) as info:
            Agent().planning.plan("   ")
        assert classify(info.value) is C.INVALID_INPUT

    def test_plan_validation_is_invalid_input(self) -> None:
        assert classify(PlanValidationError("cycle")) is C.INVALID_INPUT

    def test_subclasses_follow_their_documented_parent(self) -> None:
        class MyNotFound(ToolNotFoundError): ...
        class MyBadGoal(InvalidGoalError): ...
        assert classify(MyNotFound()) is C.PERMANENT and classify(MyBadGoal()) is C.INVALID_INPUT

    @pytest.mark.parametrize("exc", [ToolError("x"), ToolError(SECRET)])
    def test_tool_error_is_unknown(self, exc: BaseException) -> None:
        # ToolError has no structured category (v8.11); it is not reclassified.
        assert classify(exc) is C.UNKNOWN

    def test_tool_error_subclass_is_unknown(self) -> None:
        class FlakyToolError(ToolError): ...
        assert classify(FlakyToolError()) is C.UNKNOWN

    @pytest.mark.parametrize("exc", [
        Exception(), RuntimeError(), ValueError(), TypeError(), KeyError("k"), OSError(),
        TimeoutError(), ConnectionError(), KeyboardInterrupt(), SystemExit(),
    ])
    def test_generic_exceptions_are_unknown_never_transient(self, exc: BaseException) -> None:
        assert classify(exc) is C.UNKNOWN

    def test_only_the_explicit_signal_maps_to_transient(self) -> None:
        # v8.33: ``TransientToolError`` is the one TRANSIENT class; every other
        # known execution exception (incl. timeout-looking built-ins) is not.
        from core.tool_interface import TransientToolError

        assert classify(TransientToolError(SECRET)) is C.TRANSIENT
        known = [ToolNotFoundError(), InvalidGoalError(), PlanValidationError(), ToolError(),
                 ValueError(), TypeError(), KeyError(), RuntimeError(), TimeoutError(), ConnectionError()]
        assert C.TRANSIENT not in {classify(e) for e in known}


AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")


# ── foundation only: no behaviour change ────────────────────────────────


class TestNoBehaviourChange:
    def test_non_lifecycle_paths_never_classify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # v8.33: only the lifecycle path (and resume) consumes the classifier,
        # for bounded retry; every other path is unchanged.
        calls: list[object] = []
        monkeypatch.setattr(agent_module, "_classify_execution_failure", lambda e: calls.append(e) or C.UNKNOWN)
        for method in ("execute_request_with_tool_dispatch_writeback", "execute_projection_with_writeback",
                       "execute_projection_with_run_status", "execute_projection_with_tool_dispatch"):
            a = Agent()
            a.tool_registry.register(Failing("fix the wifi", ToolError("x")))
            with pytest.raises(ToolError):
                getattr(a, method)("fix the wifi")
        assert calls == []

    @pytest.mark.parametrize("method", [
        "execute_request_with_tool_dispatch_writeback", "execute_projection_with_writeback",
        "execute_projection_with_lifecycle"])
    @pytest.mark.parametrize("exc", [ToolError("x"), ToolNotFoundError("x"), TimeoutError()])
    def test_no_retry_single_invocation(self, method: str, exc: BaseException) -> None:
        a = Agent()
        tool = Failing("fix the wifi", exc)
        a.tool_registry.register(tool)
        with pytest.raises(type(exc)) as info:
            getattr(a, method)("fix the wifi")
        assert info.value is exc and tool.calls == 1

    def test_no_retry_or_resume_surface(self) -> None:
        for name in dir(Agent):
            low = name.lower()
            if name in {"resume_failed_run", "_prepare_resume", "_route_with_transient_retry"}:  # v8.32 / v8.33 sanctioned
                continue
            assert not any(w in low for w in ("retry", "resume", "attempt", "backoff")), name
        assert not hasattr(ToolRouter, "retry") and not hasattr(ToolRouter, "classify")

    def test_router_behaviour_unchanged(self) -> None:
        registry = ToolRegistry()
        registry.register(StaticMockTool(name="t"))
        router = ToolRouter(registry)
        assert router.route(ToolRequest(tool_name="t", arguments={})).tool_name == "t"
        with pytest.raises(ToolNotFoundError):
            router.route(ToolRequest(tool_name="nope", arguments={}))

    def test_execution_failure_unchanged(self) -> None:
        assert [f.name for f in dataclasses.fields(ExecutionFailure)] == [
            "exception_type", "run_id", "tool_name", "project"]

    def test_failure_records_unchanged_on_all_three_paths(self, memory: list) -> None:
        expected = ("FAILED | problem: fix the wifi | cause: controlled_tool_dispatch_failure"
                    " | solution: fix the wifi | outcome: failed:ToolError")
        keys = ["run_id", "goal_id", "plan_id", "task_id", "project", "exception_type"]
        for method in ("execute_projection_with_lifecycle", "execute_projection_with_writeback",
                       "execute_request_with_tool_dispatch_writeback"):
            memory.clear()
            a = Agent()
            a.tool_registry.register(Failing("fix the wifi", ToolError("x")))
            with pytest.raises(ToolError):
                getattr(a, method)("fix the wifi")
            assert [m[0][2] for m in memory] == [expected], method
            for rec in (a.reflection.get_all()[0], a.learning.get_all()[0]):
                assert list(rec.metadata) == keys, method
            # No failure category leaks into the records (metadata or text).
            for rec in (a.reflection.get_all()[0], a.learning.get_all()[0]):
                assert not {"category", "failure_category"} & set(rec.metadata), method
            texts = [m[0][2] for m in memory] + [a.reflection.get_all()[0].completion_summary,
                                                  a.learning.get_all()[0].detail]
            assert not any(c.value in t for t in texts for c in C), method

    def test_no_new_status_values(self) -> None:
        assert [s.value for s in GoalStatus] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in PlanStatus] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in PipelineRunStatus] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def test_stdlib_only_imports(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom):
                assert node.module in {"__future__", "enum", "typing"}, node.module
            elif isinstance(node, ast.Import):
                raise AssertionError(node.names[0].name)
        assert taxonomy_module.__all__ == ["FailureCategory", "classify_failure"]

    def test_no_module_state_and_minimal_surface(self) -> None:
        tree = _tree()
        assigns = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))]
        assert [t.id for n in assigns for t in n.targets] == ["__all__"]
        assert [n.name for n in tree.body if isinstance(n, ast.ClassDef)] == ["FailureCategory"]
        assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)] == ["classify_failure"]

    def test_classifier_reads_only_the_class(self) -> None:
        fn = next(n for n in _tree().body if isinstance(n, ast.FunctionDef))
        body = [n for stmt in fn.body for n in ast.walk(stmt)]
        attrs = {n.attr for n in body if isinstance(n, ast.Attribute)}
        called = {c.func.id for c in body if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert not {"args", "__traceback__", "__str__", "__repr__", "__cause__", "__context__"} & attrs
        assert not {"str", "repr", "format", "print", "open"} & called
        assert not [n for n in body if isinstance(n, (ast.Try, ast.While))]

    def test_no_provider_router_or_policy_coupling(self) -> None:
        tree = _tree()
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})
        for token in ("ToolRouter", "ToolNotFoundError", "AIService", "PipelineRun", "retry",
                      "sleep", "MemoryEngine", "ReflectionManager", "LearningManager"):
            assert token not in idents, token
        assert "tool_router" not in open(MODULE_PATH, encoding="utf-8").read()  # v8.14 boundary

    def test_only_agent_imports_it(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "failure_taxonomy.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "failure_taxonomy" not in f.read(), name
        src = open(AGENT_FILE, encoding="utf-8").read()
        assert "from core.failure_taxonomy import FailureCategory, classify_failure" in src

    def test_agent_public_api_unchanged(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "FailureCategory" not in agent_module.__all__
