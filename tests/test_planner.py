"""Tests for core.planner (V3.1.0 Planning Engine, Phase 1)."""

from __future__ import annotations

import pytest

from core.planner import (
    ExecutionPlan,
    Goal,
    InvalidGoalError,
    PlanningEngine,
    PlanValidationError,
    Task,
)


class TestPlanBasicGoal:
    def test_single_step_goal_produces_one_task(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("write the report")
        assert isinstance(result, ExecutionPlan)
        assert len(result.tasks) == 1
        assert result.tasks[0].description == "write the report"

    def test_single_task_has_no_dependencies(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("write the report")
        assert result.tasks[0].depends_on == ()

    def test_goal_description_is_stripped(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("  write the report  ")
        assert result.goal.description == "write the report"

    def test_result_types(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("write the report")
        assert isinstance(result.goal, Goal)
        assert all(isinstance(task, Task) for task in result.tasks)


class TestPlanMultiStepGoal:
    def test_then_delimiter_produces_ordered_tasks(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("open the file then edit it then save it")
        descriptions = [task.description for task in result.tasks]
        assert descriptions == ["open the file", "edit it", "save it"]

    def test_and_then_delimiter_is_recognized(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("open the file and then save it")
        descriptions = [task.description for task in result.tasks]
        assert descriptions == ["open the file", "save it"]

    def test_semicolon_delimiter_is_recognized(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("open the file; save it")
        descriptions = [task.description for task in result.tasks]
        assert descriptions == ["open the file", "save it"]

    def test_multi_step_tasks_form_sequential_chain(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("step one then step two then step three")
        first, second, third = result.tasks
        assert first.depends_on == ()
        assert second.depends_on == (first.id,)
        assert third.depends_on == (second.id,)

    def test_blank_steps_are_dropped(self) -> None:
        engine = PlanningEngine()
        result = engine.plan("step one then  then step two")
        descriptions = [task.description for task in result.tasks]
        assert descriptions == ["step one", "step two"]


class TestPlanDeterminism:
    def test_same_goal_produces_same_goal_id(self) -> None:
        engine = PlanningEngine()
        first = engine.plan("write the report")
        second = engine.plan("write the report")
        assert first.goal.id == second.goal.id

    def test_same_goal_produces_same_task_ids_and_order(self) -> None:
        engine = PlanningEngine()
        first = engine.plan("open it then close it")
        second = engine.plan("open it then close it")
        assert [t.id for t in first.tasks] == [t.id for t in second.tasks]
        assert [t.description for t in first.tasks] == [
            t.description for t in second.tasks
        ]
        assert [t.depends_on for t in first.tasks] == [
            t.depends_on for t in second.tasks
        ]

    def test_different_goals_produce_different_ids(self) -> None:
        engine = PlanningEngine()
        first = engine.plan("write the report")
        second = engine.plan("write the memo")
        assert first.goal.id != second.goal.id
        assert first.tasks[0].id != second.tasks[0].id

    def test_new_engine_instance_is_still_deterministic(self) -> None:
        first = PlanningEngine().plan("write the report")
        second = PlanningEngine().plan("write the report")
        assert first.goal.id == second.goal.id
        assert [t.id for t in first.tasks] == [t.id for t in second.tasks]


class TestInvalidGoal:
    def test_empty_string_raises(self) -> None:
        engine = PlanningEngine()
        with pytest.raises(InvalidGoalError):
            engine.plan("")

    def test_whitespace_only_raises(self) -> None:
        engine = PlanningEngine()
        with pytest.raises(InvalidGoalError):
            engine.plan("   ")

    def test_non_string_raises(self) -> None:
        engine = PlanningEngine()
        with pytest.raises(InvalidGoalError):
            engine.plan(None)  # type: ignore[arg-type]


class TestExecutionPlanImmutability:
    def test_plan_is_immutable(self) -> None:
        result = PlanningEngine().plan("write the report")
        with pytest.raises(AttributeError):
            result.tasks = ()  # type: ignore[misc]

    def test_task_is_immutable(self) -> None:
        result = PlanningEngine().plan("write the report")
        with pytest.raises(AttributeError):
            result.tasks[0].description = "changed"  # type: ignore[misc]

    def test_goal_is_immutable(self) -> None:
        result = PlanningEngine().plan("write the report")
        with pytest.raises(AttributeError):
            result.goal.description = "changed"  # type: ignore[misc]


class TestGetTask:
    def test_get_task_returns_matching_task(self) -> None:
        result = PlanningEngine().plan("step one then step two")
        first = result.tasks[0]
        assert result.get_task(first.id) == first

    def test_get_task_returns_none_when_missing(self) -> None:
        result = PlanningEngine().plan("write the report")
        assert result.get_task("nonexistent") is None


class TestExecutionOrder:
    def test_execution_order_matches_dependency_chain(self) -> None:
        result = PlanningEngine().plan("step one then step two then step three")
        ordered = result.execution_order()
        assert [task.id for task in ordered] == [task.id for task in result.tasks]

    def test_execution_order_respects_out_of_order_input(self) -> None:
        a = Task(id="a", description="a", depends_on=(), metadata={})
        b = Task(id="b", description="b", depends_on=("a",), metadata={})
        c = Task(id="c", description="c", depends_on=("b",), metadata={})
        goal = Goal(id="g", description="g", created_at=_utc_now())
        # Deliberately stored out of dependency order.
        plan = ExecutionPlan(id="p", goal=goal, tasks=(c, a, b), created_at=_utc_now())
        ordered_ids = [task.id for task in plan.execution_order()]
        assert ordered_ids.index("a") < ordered_ids.index("b") < ordered_ids.index("c")

    def test_execution_order_is_deterministic_for_parallel_ready_tasks(self) -> None:
        a = Task(id="a", description="a", depends_on=(), metadata={})
        b = Task(id="b", description="b", depends_on=(), metadata={})
        goal = Goal(id="g", description="g", created_at=_utc_now())
        plan = ExecutionPlan(id="p", goal=goal, tasks=(a, b), created_at=_utc_now())
        first_order = [t.id for t in plan.execution_order()]
        second_order = [t.id for t in plan.execution_order()]
        assert first_order == second_order == ["a", "b"]


class TestPlanValidation:
    def test_unknown_dependency_raises(self) -> None:
        task = Task(id="a", description="a", depends_on=("missing",), metadata={})
        goal = Goal(id="g", description="g", created_at=_utc_now())
        with pytest.raises(PlanValidationError):
            ExecutionPlan(id="p", goal=goal, tasks=(task,), created_at=_utc_now())

    def test_duplicate_task_ids_raise(self) -> None:
        a1 = Task(id="a", description="first", depends_on=(), metadata={})
        a2 = Task(id="a", description="second", depends_on=(), metadata={})
        goal = Goal(id="g", description="g", created_at=_utc_now())
        with pytest.raises(PlanValidationError):
            ExecutionPlan(id="p", goal=goal, tasks=(a1, a2), created_at=_utc_now())

    def test_cyclic_dependency_raises(self) -> None:
        a = Task(id="a", description="a", depends_on=("b",), metadata={})
        b = Task(id="b", description="b", depends_on=("a",), metadata={})
        goal = Goal(id="g", description="g", created_at=_utc_now())
        with pytest.raises(PlanValidationError):
            ExecutionPlan(id="p", goal=goal, tasks=(a, b), created_at=_utc_now())


class TestLen:
    def test_len_reflects_task_count(self) -> None:
        result = PlanningEngine().plan("step one then step two then step three")
        assert len(result) == 3


class TestStandaloneIsolation:
    def test_no_cross_module_imports(self) -> None:
        import ast

        import core.planner as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        forbidden_substrings = (
            "memory",
            "history",
            "context",
            "knowledge",
            "learning",
            "reflection",
            "skill",
            "agent",
            "problemsolver",
            "problem_solver",
            "identity",
            "llm_client",
            "dashboard",
            "actions",
        )
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
