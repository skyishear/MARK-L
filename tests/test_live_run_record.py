"""Tests for v8.43 ``core.live_run_record`` — production run recording (P5).

Every production tool call is recorded through the v8.x lifecycle from the O9
outcome record only; the production SQLite store is never written (OD-5).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sqlite3

import pytest

import core.live_run_record as lrr
from core.agent import Agent
from core.goal_manager import GoalStatus
from core.live_tools import LiveCall
from core.pipeline_run import PipelineRunStatus
from core.planning_engine import PlanStatus
from core.tool_runtime import ToolCallOutcome

SECRET = "super-secret-argument"


def out(outcome: str, name: str = "get_time", call_id: str = "c1", exc: str | None = None) -> ToolCallOutcome:
    return ToolCallOutcome(call_id, name, outcome, exc)


def state(agent: Agent):
    (run,) = agent.pipeline_run_manager.list_runs()
    goal = agent.goal_manager.get_goal(run.metadata["goal_id"])
    (plan,) = agent.planning_engine.list_plans()
    return run, goal, plan


class TestExecuted:
    def test_run_completes_with_step_goal_and_plan_completed(self) -> None:
        agent = Agent()
        result = agent.record_live_tool_outcomes([out("executed")], project="p1")
        assert result.errors == 0 and len(result.runs) == 1
        run, goal, plan = state(agent)
        assert run.status is PipelineRunStatus.COMPLETED and result.runs[0].status is PipelineRunStatus.COMPLETED
        assert goal.status is GoalStatus.COMPLETED and plan.status is PlanStatus.COMPLETED
        assert [s.status for s in plan.steps] == [PlanStatus.COMPLETED]
        assert plan.steps[0].description == "get_time"
        assert run.metadata["call_id"] == "c1" and run.metadata["project"] == "p1"

    def test_success_writeback_memory_reflection_learning(self) -> None:
        agent = Agent()
        agent.record_live_tool_outcomes([out("executed")], project="p1")
        (mem,) = agent.memory_engine.recall(limit=10)
        assert (mem["category"], mem["key"], mem["value"], mem["project"]) == ("tool_outcome", "get_time:c1", "success", "p1")
        (refl,) = agent.reflection.get_all()
        assert "get_time" in refl.what_worked and refl.what_failed == "" and refl.confidence_level == 1.0
        (learned,) = agent.learning.get_all()
        assert learned.category.value == "successful_pattern" and learned.subject == "get_time"


class TestFailed:
    def test_failed_call_keeps_step_goal_plan_active_and_run_failed(self) -> None:
        agent = Agent()
        agent.record_live_tool_outcomes([out("failed", exc="ValueError")])
        run, goal, plan = state(agent)
        assert run.status is PipelineRunStatus.FAILED
        assert goal.status is GoalStatus.ACTIVE and plan.status is PlanStatus.ACTIVE
        assert [s.status for s in plan.steps] == [PlanStatus.ACTIVE]

    def test_exactly_one_failure_writeback_with_type_name_only(self) -> None:
        agent = Agent()
        agent.record_live_tool_outcomes([out("failed", exc="ValueError")])
        (mem,) = agent.memory_engine.recall(limit=10)
        assert mem["value"] == "failed:ValueError"
        (refl,) = agent.reflection.get_all()
        assert "get_time" in refl.what_failed and refl.what_worked == "" and refl.confidence_level == 0.0
        assert refl.metadata["exception_type"] == "ValueError"
        (learned,) = agent.learning.get_all()
        assert learned.category.value == "failed_pattern"


class TestRefused:
    def test_refused_step_is_archived_run_completes_and_nothing_is_written_back(self) -> None:
        agent = Agent()
        agent.record_live_tool_outcomes([out("refused")])
        run, goal, plan = state(agent)
        assert run.status is PipelineRunStatus.COMPLETED
        assert [s.status for s in plan.steps] == [PlanStatus.ARCHIVED]
        assert plan.status is PlanStatus.COMPLETED and goal.status is GoalStatus.COMPLETED
        assert agent.memory_engine.count() == 0
        assert agent.reflection.get_all() == [] and agent.learning.get_all() == []


class TestBatchesAndIsolation:
    def test_one_run_per_outcome_in_order(self) -> None:
        agent = Agent()
        result = agent.record_live_tool_outcomes(
            [out("executed", "a", "1"), out("failed", "b", "2", "KeyError"), out("refused", "c", "3")]
        )
        assert [r.status for r in result.runs] == [
            PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED, PipelineRunStatus.COMPLETED]
        assert [r.metadata["call_id"] for r in agent.pipeline_run_manager.list_runs()] == ["1", "2", "3"]
        assert agent.memory_engine.count() == 2  # executed + failed; refused writes nothing

    def test_an_unrecordable_outcome_is_counted_and_never_stops_the_others(self) -> None:
        agent = Agent()
        bad = ToolCallOutcome("bad", "get_time", "executed")
        object.__setattr__(bad, "tool_name", "   ")  # planner rejects a blank goal
        result = agent.record_live_tool_outcomes([bad, out("executed", "ok", "2")])
        assert result.errors == 1 and len(result.runs) == 1

    def test_empty_input(self) -> None:
        assert Agent().record_live_tool_outcomes([]) == lrr.LiveRunRecord((), 0)

    def test_no_arguments_outputs_or_exception_text_are_recorded(self) -> None:
        agent = Agent()
        agent.record_live_tool_outcomes([out("executed"), out("failed", "x", "2", "OSError")])
        dump = repr(agent.memory_engine.recall(limit=50)) + repr(agent.reflection.get_all()) + repr(
            agent.learning.get_all()) + repr(agent.pipeline_run_manager.list_runs())
        assert SECRET not in dump


class TestProductionStoreUntouched:
    def test_no_sqlite_connection_is_opened(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(*a: object, **k: object) -> None:
            raise AssertionError("production store touched")

        monkeypatch.setattr(sqlite3, "connect", boom)
        Agent().record_live_tool_outcomes([out("executed"), out("failed", exc="E"), out("refused")])


class TestLiveSessionRecorder:
    def test_recorder_wiring_records_real_session_outcomes(self) -> None:
        agent = Agent()

        async def execute(name: str, args: dict) -> dict:
            return {"result": f"ran {name}"}

        session = agent.live_tool_session(execute=execute, confirm=lambda c, s: True,
                                          recorder=agent.record_live_tool_outcomes)
        session.sync_declarations([{"name": "get_time", "description": "time", "parameters": {"type": "OBJECT", "properties": {}}}])
        replies = asyncio.run(session.handle_round([LiveCall("c1", "get_time", {"secret": SECRET}), LiveCall("c2", "nope", {})]))
        assert replies[0].response == {"result": "ran get_time"}
        runs = agent.pipeline_run_manager.list_runs()
        assert [r.metadata["call_id"] for r in runs] == ["c1", "c2"]
        assert SECRET not in repr(agent.reflection.get_all()) + repr(agent.memory_engine.recall(limit=50))

    def test_a_broken_recorder_never_breaks_the_call(self) -> None:
        agent = Agent()

        async def execute(name: str, args: dict) -> dict:
            return {"result": "ok"}

        def broken(outcomes: object) -> None:
            raise RuntimeError("x")

        session = agent.live_tool_session(execute=execute, confirm=lambda c, s: True, recorder=broken)
        session.sync_declarations([{"name": "get_time", "description": "t", "parameters": {"type": "OBJECT", "properties": {}}}])
        (reply,) = asyncio.run(session.handle_round([LiveCall("c1", "get_time", {})]))
        assert reply.response == {"result": "ok"}


class TestArchitecture:
    def test_agent_method_is_thin_and_public_surface_unchanged(self) -> None:
        import core.agent as agent_module

        tree = ast.parse(inspect.getsource(agent_module))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "record_live_tool_outcomes")
        assert node.end_lineno - node.lineno < 30 and len(agent_module.__all__) == 16

    def test_leaf_imports_only_stdlib_and_pipeline_run(self) -> None:
        tree = ast.parse(open(lrr.__file__, encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert mods == {"__future__", "collections.abc", "dataclasses", "typing", "core.pipeline_run"}
        assert "sqlite3" not in open(lrr.__file__, encoding="utf-8").read()
        assert lrr.__all__ == ["LifecycleHooks", "LiveRunRecord", "record_tool_outcomes"]
