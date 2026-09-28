"""Tests for v8.32 ``Agent.resume_failed_run`` (owner decisions O4 / O6 / O7).

A FAILED lifecycle attempt is resumed as a NEW ``PipelineRun`` on the SAME
pipeline: COMPLETED steps skipped (no new success writeback, O7), ARCHIVED
steps skipped and never re-checked (O6), the failed ACTIVE step re-dispatched
only if its ``ToolSpec`` is ``idempotent=True`` (O4; otherwise refused before
any run is created), DRAFT steps executed normally. The failed run is never
modified. Lifecycle, step, failure-writeback and exception semantics are the
existing v8.25-v8.29 ones.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import core.agent as agent_module
from core import problem_solver
from core.agent import Agent
from core.agent.learning_manager import LearningCategory
from core.goal_manager import GoalStatus
from core.pipeline_run import ALLOWED_TRANSITIONS, PipelineRunStatus
from core.planning_engine import PlanStatus
from core.tool_catalog import ToolCatalog, ToolSpec
from core.tool_interface import ToolError, ToolRequest, ToolResult
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

G, P, R = GoalStatus, PlanStatus, PipelineRunStatus
FOUR = "step one then step two then step three then step four"
NAMES = ("step one", "step two", "step three", "step four")
SECRET = "api_key=SECRET-9f2c /home/alice/private.txt"


class Tool:
    """Controllable tool: records calls in a shared log; raises while ``fail`` is set."""

    def __init__(self, name: str, log: list[str], fail: BaseException | None = None) -> None:
        self.name = name
        self.description = "d"
        self.log = log
        self.fail = fail
        self.calls = 0

    def invoke(self, request: ToolRequest) -> ToolResult:
        self.calls += 1
        self.log.append(self.name)
        if self.fail is not None:
            raise self.fail
        return ToolResult(request.tool_name, f"{self.name} ok")


@pytest.fixture(autouse=True)
def memory(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    writes: list[tuple] = []
    monkeypatch.setattr(problem_solver, "remember", lambda *a, **k: writes.append((a, k)) or "id")
    return writes


def idempotent(a: Agent, name: str, flag: bool = True) -> None:
    a.tool_catalog.register(ToolSpec(name, "d", {"type": "object"}, idempotent=flag))


def failed_attempt(exc: BaseException | None = None, *, register=NAMES, project=None):
    """Original lifecycle attempt: A COMPLETED, B fails (ACTIVE), C / D DRAFT."""
    log: list[str] = []
    a = Agent()
    tools = {n: Tool(n, log) for n in NAMES}
    tools["step two"].fail = exc or ToolError(SECRET)
    for n in register:
        a.tool_registry.register(tools[n])
    with pytest.raises(type(tools["step two"].fail)):
        a.execute_projection_with_lifecycle(FOUR, project=project)
    (run,) = a.pipeline_run_manager.list_runs()
    return a, tools, log, run


def steps(a: Agent) -> list[PlanStatus]:
    return [s.status for s in a.planning_engine.list_plans()[0].steps]


def goal_plan(a: Agent) -> tuple[GoalStatus, PlanStatus]:
    return a.goal_manager.list_goals()[0].status, a.planning_engine.list_plans()[0].status


def snapshot(a: Agent) -> tuple:
    return (a.pipeline_run_manager.list_runs(), steps(a), goal_plan(a),
            len(a.reflection.get_all()), len(a.learning.get_all()))


# ── successful resume ───────────────────────────────────────────────────


class TestSuccessfulResume:
    def test_original_attempt_state(self) -> None:
        a, _, log, run = failed_attempt()
        assert run.status is R.FAILED and log == ["step one", "step two"]
        assert steps(a) == [P.COMPLETED, P.ACTIVE, P.DRAFT, P.DRAFT]
        assert goal_plan(a) == (G.ACTIVE, P.ACTIVE)

    def test_resume_completes_everything(self) -> None:
        a, tools, log, old = failed_attempt(project="home")
        tools["step two"].fail = None
        idempotent(a, "step two")
        log.clear()
        projection, new, decisions, results = a.resume_failed_run(old.id)
        assert log == ["step two", "step three", "step four"]  # pipeline order, A skipped
        assert tools["step one"].calls == 1 and tools["step two"].calls == 2
        assert new.status is R.COMPLETED and new.id != old.id
        assert steps(a) == [P.COMPLETED] * 4
        assert goal_plan(a) == (G.COMPLETED, P.COMPLETED)
        assert [d.tool_name for d in decisions] == ["step two", "step three", "step four"]
        assert [r.output for r in results] == ["step two ok", "step three ok", "step four ok"]
        assert projection.pipeline_id == old.pipeline_reference

    def test_new_run_same_pipeline_and_metadata(self) -> None:
        a, tools, _, old = failed_attempt(project="home")
        tools["step two"].fail = None
        idempotent(a, "step two")
        _, new, _, _ = a.resume_failed_run(old.id)
        assert a.pipeline_run_manager.count() == 2
        assert new.pipeline_reference == old.pipeline_reference
        assert len(a.pipeline_engine.list_pipelines()) == 1 and len(a.execution_planner.list_execution_plans()) == 1
        assert dict(new.metadata) == {"project": "home", "goal_id": old.metadata["goal_id"],
                                      "mapping_id": old.metadata["mapping_id"], "resumes_run_id": old.id}

    def test_original_run_unchanged(self) -> None:
        a, tools, _, old = failed_attempt()
        before = a.pipeline_run_manager.get_run(old.id)
        tools["step two"].fail = None
        idempotent(a, "step two")
        a.resume_failed_run(old.id)
        after = a.pipeline_run_manager.get_run(old.id)
        assert after is before and after.status is R.FAILED
        assert (after.updated_at, dict(after.metadata)) == (before.updated_at, dict(before.metadata))

    def test_new_run_running_and_step_active_before_dispatch(self) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        idempotent(a, "step two")
        seen: list[tuple] = []
        original = tools["step three"].invoke

        def peek(request: ToolRequest) -> ToolResult:
            seen.append((a.pipeline_run_manager.list_runs()[-1].status, steps(a)))
            return original(request)

        tools["step three"].invoke = peek  # type: ignore[method-assign]
        a.resume_failed_run(old.id)
        assert seen == [(R.RUNNING, [P.COMPLETED, P.COMPLETED, P.ACTIVE, P.DRAFT])]

    def test_run_transitions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        idempotent(a, "step two")
        events: list[tuple] = []
        orig = a.pipeline_run_manager.update_run
        monkeypatch.setattr(a.pipeline_run_manager, "update_run",
                            lambda rid, **k: events.append((rid, k.get("status"))) or orig(rid, **k))
        _, new, _, _ = a.resume_failed_run(old.id)
        assert events == [(new.id, R.RUNNING), (new.id, R.COMPLETED)]

    def test_uses_existing_lifecycle_reflection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        idempotent(a, "step two")
        called: list[str] = []
        orig = agent_module.reflect_execution_completed
        monkeypatch.setattr(agent_module, "reflect_execution_completed",
                            lambda *x, **k: called.append("completed") or orig(*x, **k))
        a.resume_failed_run(old.id)
        assert called == ["completed"]

    def test_success_writeback_only_for_newly_executed_stages(self, memory: list) -> None:
        a, tools, _, old = failed_attempt()
        memory.clear()
        reflections = len(a.reflection.get_all())
        tools["step two"].fail = None
        idempotent(a, "step two")
        _, new, _, _ = a.resume_failed_run(old.id)
        assert [m[0][2].split(" | ")[:2] for m in memory] == [
            ["SOLVED", "problem: step two"], ["SOLVED", "problem: step three"], ["SOLVED", "problem: step four"]]
        assert len(a.reflection.get_all()) - reflections == 3
        succ = [r for r in a.learning.get_all() if r.category is LearningCategory.SUCCESSFUL_PATTERN]
        assert sorted(r.subject for r in succ) == ["step four", "step three", "step two"]
        assert all(r.metadata["run_id"] == new.id for r in succ)

    def test_all_remaining_draft_unregistered_are_archived(self) -> None:
        a, tools, _, old = failed_attempt(register=("step one", "step two"))
        tools["step two"].fail = None
        idempotent(a, "step two")
        _, new, decisions, results = a.resume_failed_run(old.id)
        assert new.status is R.COMPLETED and len(results) == 1
        assert steps(a) == [P.COMPLETED, P.COMPLETED, P.ARCHIVED, P.ARCHIVED]

    def test_decisions_rebuilt_from_current_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # step four's tool is registered only after the failure: the rebuilt
        # decisions dispatch it (DRAFT is normal unfinished work).
        a, tools, log, old = failed_attempt(register=("step one", "step two", "step three"))
        a.tool_registry.register(tools["step four"])
        tools["step two"].fail = None
        idempotent(a, "step two")
        built: list[tuple] = []
        orig = agent_module.build_stage_dispatch_decisions
        monkeypatch.setattr(agent_module, "build_stage_dispatch_decisions",
                            lambda *x, **k: built.append(orig(*x, **k)) or built[-1])
        _, _, decisions, _ = a.resume_failed_run(old.id)
        assert built and all(d in built[-1] for d in decisions)
        assert tools["step four"].calls == 1 and steps(a)[3] is P.COMPLETED


# ── O6: ARCHIVED stays ARCHIVED ─────────────────────────────────────────


class TestArchived:
    def test_archived_never_rechecked_or_dispatched(self, memory: list) -> None:
        a, tools, log, old = failed_attempt(register=("step two", "step three", "step four"))
        assert steps(a) == [P.ARCHIVED, P.ACTIVE, P.DRAFT, P.DRAFT]
        a.tool_registry.register(tools["step one"])  # tool becomes available later
        tools["step two"].fail = None
        idempotent(a, "step two")
        memory.clear()
        _, _, decisions, _ = a.resume_failed_run(old.id)
        assert tools["step one"].calls == 0
        assert steps(a) == [P.ARCHIVED, P.COMPLETED, P.COMPLETED, P.COMPLETED]
        assert "step one" not in [d.tool_name for d in decisions]
        assert not any("problem: step one" in m[0][2] for m in memory)


# ── O4: failed ACTIVE step ──────────────────────────────────────────────


class TestO4Blocking:
    @pytest.mark.parametrize("setup", ["non_idempotent", "missing_spec", "unregistered"])
    def test_blocked_before_anything_changes(self, setup: str, monkeypatch: pytest.MonkeyPatch,
                                             memory: list) -> None:
        a, tools, log, old = failed_attempt()
        tools["step two"].fail = None
        if setup == "non_idempotent":
            idempotent(a, "step two", flag=False)
        elif setup == "unregistered":
            idempotent(a, "step two")
            a.tool_registry.unregister("step two")
        created: list[str] = []
        orig = a.pipeline_run_manager.create_run
        monkeypatch.setattr(a.pipeline_run_manager, "create_run",
                            lambda *x, **k: created.append("run") or orig(*x, **k))
        before, writes = snapshot(a), len(memory)
        log.clear()
        with pytest.raises(ValueError) as info:
            a.resume_failed_run(old.id)
        fragment = {"non_idempotent": "not idempotent", "missing_spec": "no ToolSpec",
                    "unregistered": "no registered tool"}[setup]
        assert fragment in str(info.value)
        assert created == [] and log == []
        assert snapshot(a) == before and len(memory) == writes
        assert a.pipeline_run_manager.get_run(old.id).status is R.FAILED

    def test_missing_spec_is_not_idempotent_even_if_other_specs_exist(self) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        for n in ("step one", "step three", "step four"):
            idempotent(a, n)
        with pytest.raises(ValueError, match="no ToolSpec"):
            a.resume_failed_run(old.id)

    def test_current_catalog_metadata_controls(self) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        with pytest.raises(ValueError):
            a.resume_failed_run(old.id)  # no spec yet
        idempotent(a, "step two")  # registered after the failure
        _, new, _, _ = a.resume_failed_run(old.id)
        assert new.status is R.COMPLETED

    def test_no_override_parameter(self) -> None:
        assert list(inspect.signature(Agent.resume_failed_run).parameters) == ["self", "run_id"]


# ── resumed failure ─────────────────────────────────────────────────────


class TestResumedFailure:
    def test_same_step_fails_again(self, memory: list) -> None:
        exc = ToolError(SECRET)
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = exc
        idempotent(a, "step two")
        memory.clear()
        with pytest.raises(ToolError) as info:
            a.resume_failed_run(old.id)
        assert info.value is exc
        new = a.pipeline_run_manager.list_runs()[-1]
        assert new.status is R.FAILED and new.id != old.id
        assert a.pipeline_run_manager.get_run(old.id).status is R.FAILED
        assert steps(a) == [P.COMPLETED, P.ACTIVE, P.DRAFT, P.DRAFT]
        assert goal_plan(a) == (G.ACTIVE, P.ACTIVE)
        assert len(memory) == 1 and memory[0][0][2].startswith("FAILED | problem: step two")
        (ref,) = [r for r in a.reflection.get_all() if r.metadata.get("run_id") == new.id]
        assert ref.metadata["task_id"] == a.planning_engine.list_plans()[0].steps[1].id
        assert SECRET not in repr((memory, a.reflection.get_all(), a.learning.get_all()))

    def test_later_stage_fails(self, memory: list) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        tools["step three"].fail = RuntimeError("boom")
        idempotent(a, "step two")
        memory.clear()
        with pytest.raises(RuntimeError):
            a.resume_failed_run(old.id)
        assert steps(a) == [P.COMPLETED, P.COMPLETED, P.ACTIVE, P.DRAFT]
        assert tools["step four"].calls == 0
        assert [m[0][2].split(" | ")[:2] for m in memory] == [["FAILED", "problem: step three"]]
        new = a.pipeline_run_manager.list_runs()[-1]
        assert a.learning.get_all()[-1].metadata["run_id"] == new.id
        assert goal_plan(a) == (G.ACTIVE, P.ACTIVE)

    @pytest.mark.parametrize("layer", ["memory", "reflection", "learning"])
    def test_failing_writeback_does_not_mask(self, layer: str, monkeypatch: pytest.MonkeyPatch) -> None:
        exc = ToolError("original")
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = exc
        idempotent(a, "step two")

        def boom(*x, **k):
            raise ValueError("writeback broke")

        target = {"memory": (problem_solver, "remember"),
                  "reflection": (a.reflection, "add_reflection"),
                  "learning": (a.learning, "record_failed_pattern")}[layer]
        monkeypatch.setattr(*target, boom)
        with pytest.raises(ToolError) as info:
            a.resume_failed_run(old.id)
        assert info.value is exc

    def test_resume_the_resumed_attempt(self) -> None:
        a, tools, _, old = failed_attempt()
        idempotent(a, "step two")
        with pytest.raises(ToolError):
            a.resume_failed_run(old.id)  # fails again
        second = a.pipeline_run_manager.list_runs()[-1]
        tools["step two"].fail = None
        _, third, _, _ = a.resume_failed_run(second.id)
        assert third.metadata["resumes_run_id"] == second.id and third.status is R.COMPLETED
        assert [r.status for r in a.pipeline_run_manager.list_runs()] == [R.FAILED, R.FAILED, R.COMPLETED]

    def test_no_retry_single_invocation_per_attempt(self) -> None:
        a, tools, _, old = failed_attempt()
        idempotent(a, "step two")
        with pytest.raises(ToolError):
            a.resume_failed_run(old.id)
        assert tools["step two"].calls == 2  # one per attempt, never retried in-run


# ── unresumable runs ────────────────────────────────────────────────────


class TestUnresumable:
    def test_unknown_run(self) -> None:
        a = Agent()
        with pytest.raises(KeyError):
            a.resume_failed_run("missing")
        assert a.pipeline_run_manager.count() == 0

    def test_completed_run(self) -> None:
        a, tools, _, old = failed_attempt()
        tools["step two"].fail = None
        idempotent(a, "step two")
        _, new, _, _ = a.resume_failed_run(old.id)
        with pytest.raises(ValueError, match="only a FAILED run"):
            a.resume_failed_run(new.id)
        with pytest.raises(ValueError, match="not a failed lifecycle attempt"):
            a.resume_failed_run(old.id)  # goal / plan COMPLETED now
        assert a.pipeline_run_manager.count() == 2

    @pytest.mark.parametrize("status", [R.CREATED, R.RUNNING, R.CANCELLED])
    def test_other_statuses(self, status: PipelineRunStatus) -> None:
        a, _, _, old = failed_attempt()
        run = a.pipeline_run_manager.create_run(old.pipeline_reference)
        if status is not R.CREATED:
            a.pipeline_run_manager.update_run(run.id, status=status)
        before = a.pipeline_run_manager.count()
        with pytest.raises(ValueError, match="only a FAILED run"):
            a.resume_failed_run(run.id)
        assert a.pipeline_run_manager.count() == before

    @pytest.mark.parametrize("method", ["execute_projection_with_run_status", "execute_projection_with_writeback"])
    def test_non_lifecycle_failed_run(self, method: str) -> None:
        a = Agent()
        log: list[str] = []
        a.tool_registry.register(Tool("fix the wifi", log, ToolError("x")))
        with pytest.raises(ToolError):
            getattr(a, method)("fix the wifi")
        run = a.pipeline_run_manager.list_runs()[0]
        idempotent(a, "fix the wifi")
        with pytest.raises(ValueError, match="not a failed lifecycle attempt"):
            a.resume_failed_run(run.id)
        assert a.pipeline_run_manager.count() == 1 and log == ["fix the wifi"]


# ── unchanged behaviour & architecture ──────────────────────────────────


class TestUnchanged:
    def test_status_vocabularies(self) -> None:
        assert [s.value for s in G] == ["draft", "active", "paused", "completed", "cancelled"]
        assert [s.value for s in P] == ["draft", "ready", "active", "completed", "archived"]
        assert [s.value for s in R] == ["created", "running", "completed", "failed", "cancelled"]
        assert len(ALLOWED_TRANSITIONS) == 5

    def test_registry_router_catalog_behaviour(self) -> None:
        registry = ToolRegistry()
        tool = registry.register(Tool("t", []))
        assert ToolRouter(registry).route(ToolRequest("t", {})).output == "t ok"
        catalog = ToolCatalog()
        spec = catalog.register(ToolSpec("t", "d", {"type": "object"}))
        assert catalog.get("t") is spec and registry.get("t") is tool

    def test_agent_catalog_is_empty_and_ignored_by_execution(self) -> None:
        a = Agent()
        assert isinstance(a.tool_catalog, ToolCatalog) and a.tool_catalog.list() == ()
        a.tool_registry.register(Tool("fix the wifi", []))
        _, run, _, _ = a.execute_projection_with_lifecycle("fix the wifi")
        assert run.status is R.COMPLETED

    def test_prepare_resume_writes_nothing(self) -> None:
        node = next(n for n in ast.walk(ast.parse(inspect.getsource(agent_module)))
                    if isinstance(n, ast.FunctionDef) and n.name == "_prepare_resume")
        attrs = {c.func.attr for c in ast.walk(node) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
        assert not attrs & {"create_run", "update_run", "update_plan", "update_goal", "route", "invoke",
                            "register", "record_problem_outcome", "add_reflection"}

    def test_resume_reuses_shared_run_helper(self) -> None:
        node = next(n for n in ast.walk(ast.parse(inspect.getsource(agent_module)))
                    if isinstance(n, ast.FunctionDef) and n.name == "resume_failed_run")
        calls = {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in ast.walk(node) if isinstance(c, ast.Call)}
        assert calls == {"_prepare_resume", "_run_projected_pipeline", "_record_failure_outcome",
                         "reflect_execution_completed", "_record_tool_outcomes"}
        (h,) = [n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)]
        assert isinstance(h.type, ast.Name) and h.type.id == "BaseException"
        assert [r.exc for r in ast.walk(h) if isinstance(r, ast.Raise)] == [None]

    def test_public_api(self) -> None:
        assert len(agent_module.__all__) == 16
        assert "resume_failed_run" in dir(Agent) and not any("retry" in n.lower() for n in dir(Agent))
