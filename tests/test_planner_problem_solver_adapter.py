"""Tests for core.planner_problem_solver_adapter (v3.2 integration layer)."""

from __future__ import annotations

import pytest

from core import problem_solver
from core.planner import PlanningEngine
from core.planner_problem_solver_adapter import (
    ProblemSolverWorkItem,
    format_context_kwargs,
    gather_context_kwargs,
    plan_to_work_items,
    record_outcome_kwargs,
)


@pytest.fixture(autouse=True)
def _stub_memory_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the one real-function integration test hermetic: stub the
    MemoryEngine calls problem_solver.py makes internally, so no real
    SQLite database is touched by this test module.
    """
    monkeypatch.setattr(problem_solver, "recall", lambda **kwargs: [])
    monkeypatch.setattr(problem_solver, "why", lambda *args, **kwargs: [])
    monkeypatch.setattr(problem_solver, "remember", lambda *args, **kwargs: "stub-id")


class TestPlanToWorkItems:
    def test_single_step_plan_produces_one_work_item(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        items = plan_to_work_items(plan)
        assert len(items) == 1
        assert isinstance(items[0], ProblemSolverWorkItem)
        assert items[0].problem == "fix the wifi"
        assert items[0].task_id == plan.tasks[0].id
        assert items[0].depends_on == ()
        assert items[0].project is None

    def test_multi_step_plan_preserves_execution_order_and_dependencies(self) -> None:
        plan = PlanningEngine().plan("open the file then edit it then save it")
        items = plan_to_work_items(plan)
        assert [item.problem for item in items] == [
            "open the file",
            "edit it",
            "save it",
        ]
        assert items[0].depends_on == ()
        assert items[1].depends_on == (items[0].task_id,)
        assert items[2].depends_on == (items[1].task_id,)

    def test_project_is_attached_to_every_item(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        items = plan_to_work_items(plan, project="mark_l")
        assert all(item.project == "mark_l" for item in items)

    def test_work_item_is_immutable(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        item = plan_to_work_items(plan)[0]
        with pytest.raises(AttributeError):
            item.problem = "changed"  # type: ignore[misc]

    def test_no_task_is_executed(self) -> None:
        # plan_to_work_items must be a pure translation: calling it
        # must not raise, block, touch the network, or do anything
        # beyond building the returned tuple.
        plan = PlanningEngine().plan("delete the system32 folder")
        items = plan_to_work_items(plan)
        assert items[0].problem == "delete the system32 folder"


class TestGatherContextKwargs:
    def test_shape_matches_problem_and_project(self) -> None:
        item = ProblemSolverWorkItem(
            task_id="t1", problem="fix the wifi", depends_on=(), project="mark_l"
        )
        assert gather_context_kwargs(item) == {
            "problem": "fix the wifi",
            "project": "mark_l",
        }

    def test_usable_directly_against_real_gather_context(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        item = plan_to_work_items(plan)[0]
        bundle = problem_solver.gather_context(**gather_context_kwargs(item))
        assert bundle["known_solutions"] == []


class TestFormatContextKwargs:
    def test_shape_matches_problem_and_project(self) -> None:
        item = ProblemSolverWorkItem(
            task_id="t1", problem="fix the wifi", depends_on=(), project=None
        )
        assert format_context_kwargs(item) == {
            "problem": "fix the wifi",
            "project": None,
        }

    def test_usable_directly_against_real_format_context_for_solver(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        item = plan_to_work_items(plan)[0]
        text = problem_solver.format_context_for_solver(**format_context_kwargs(item))
        assert isinstance(text, str)


class TestRecordOutcomeKwargs:
    def test_shape_includes_caller_supplied_fields(self) -> None:
        item = ProblemSolverWorkItem(
            task_id="t1", problem="fix the wifi", depends_on=(), project="mark_l"
        )
        kwargs = record_outcome_kwargs(
            item, cause="loose cable", solution="reseated cable", outcome="success"
        )
        assert kwargs == {
            "problem": "fix the wifi",
            "cause": "loose cable",
            "solution": "reseated cable",
            "outcome": "success",
            "project": "mark_l",
        }

    def test_usable_directly_against_real_record_outcome(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        item = plan_to_work_items(plan)[0]
        kwargs = record_outcome_kwargs(
            item, cause="loose cable", solution="reseated cable", outcome="success"
        )
        result = problem_solver.record_outcome(**kwargs)
        assert result == "stub-id"
