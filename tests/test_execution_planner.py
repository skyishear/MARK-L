"""Tests for v8.7 Execution Planner (Foundation Layer)."""

from __future__ import annotations

import ast
import os

import pytest

from core.execution_planner import ExecutionMapping, ExecutionPlanner
from core.goal_manager import GoalManager, GoalStatus
from core.planning_engine import PlanStatus, PlanningEngine
from core.task_graph import TaskGraph


def build_graph() -> TaskGraph:
    g = TaskGraph()
    for nid in ("a", "b", "c", "d"):
        g.create_node(title=nid, node_id=nid)
    # a -> b, a -> c, b -> d, c -> d
    g.connect("a", "b")
    g.connect("a", "c")
    g.connect("b", "d")
    g.connect("c", "d")
    return g


class TestEmpty:
    def test_count_is_zero(self) -> None:
        assert ExecutionPlanner().count() == 0

    def test_list_is_empty(self) -> None:
        assert ExecutionPlanner().list_execution_plans() == ()

    def test_get_unknown_returns_none(self) -> None:
        assert ExecutionPlanner().get_execution_plan("nope") is None

    def test_len_is_zero(self) -> None:
        assert len(ExecutionPlanner()) == 0


class TestCreateExecutionPlan:
    def test_create_with_no_references(self) -> None:
        p = ExecutionPlanner()
        m = p.create_execution_plan()
        assert isinstance(m, ExecutionMapping)
        assert m.goal_reference is None
        assert m.plan_reference is None
        assert m.graph_reference is None
        assert m.ordered_node_ids == ()
        assert m.metadata == {}

    def test_id_auto_generated(self) -> None:
        m = ExecutionPlanner().create_execution_plan()
        assert isinstance(m.id, str) and len(m.id) > 0

    def test_explicit_id_preserved(self) -> None:
        m = ExecutionPlanner().create_execution_plan(mapping_id="m1")
        assert m.id == "m1"

    def test_duplicate_id_rejected(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan(mapping_id="m1")
        with pytest.raises(ValueError):
            p.create_execution_plan(mapping_id="m1")

    def test_blank_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            ExecutionPlanner().create_execution_plan(mapping_id="   ")

    def test_blank_references_rejected(self) -> None:
        p = ExecutionPlanner()
        with pytest.raises(ValueError):
            p.create_execution_plan(goal_id="")
        with pytest.raises(ValueError):
            p.create_execution_plan(plan_id="   ")
        with pytest.raises(ValueError):
            p.create_execution_plan(graph_id="")

    def test_create_increments_count(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan()
        p.create_execution_plan()
        assert p.count() == 2


class TestReferenceValidation:
    def test_goal_reference_must_exist(self) -> None:
        gm = GoalManager()
        gm.create_goal(title="t", goal_id="g1")
        p = ExecutionPlanner(goal_manager=gm)
        with pytest.raises(ValueError):
            p.create_execution_plan(goal_id="missing")

    def test_plan_reference_must_exist(self) -> None:
        pe = PlanningEngine()
        pe.create_plan(goal="g", plan_id="p1")
        p = ExecutionPlanner(planning_engine=pe)
        with pytest.raises(ValueError):
            p.create_execution_plan(plan_id="missing")

    def test_known_goal_reference_accepted(self) -> None:
        gm = GoalManager()
        gm.create_goal(title="t", goal_id="g1")
        p = ExecutionPlanner(goal_manager=gm)
        m = p.create_execution_plan(goal_id="g1")
        assert m.goal_reference == "g1"

    def test_known_plan_reference_accepted(self) -> None:
        pe = PlanningEngine()
        pe.create_plan(goal="g", plan_id="p1")
        p = ExecutionPlanner(planning_engine=pe)
        m = p.create_execution_plan(plan_id="p1")
        assert m.plan_reference == "p1"

    def test_no_wired_stores_means_no_validation(self) -> None:
        p = ExecutionPlanner()
        # References stored verbatim even though stores are absent.
        m = p.create_execution_plan(goal_id="g-unknown", plan_id="p-unknown")
        assert m.goal_reference == "g-unknown"
        assert m.plan_reference == "p-unknown"


class TestUpdateExecutionPlan:
    def test_updates_ordered_node_ids(self) -> None:
        p = ExecutionPlanner()
        m = p.create_execution_plan()
        new = p.update_execution_plan(m.id, ordered_node_ids=("x", "y"))
        assert new.ordered_node_ids == ("x", "y")
        assert p.get_execution_plan(m.id).ordered_node_ids == ("x", "y")

    def test_updates_metadata(self) -> None:
        p = ExecutionPlanner()
        m = p.create_execution_plan()
        new = p.update_execution_plan(m.id, metadata={"k": "v"})
        assert new.metadata == {"k": "v"}

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError):
            ExecutionPlanner().update_execution_plan("missing")

    def test_invalid_node_id_rejected(self) -> None:
        p = ExecutionPlanner()
        m = p.create_execution_plan()
        with pytest.raises(ValueError):
            p.update_execution_plan(m.id, ordered_node_ids=("ok", ""))


class TestRemoveAndClear:
    def test_remove_existing_returns_true(self) -> None:
        p = ExecutionPlanner()
        m = p.create_execution_plan()
        assert p.remove_execution_plan(m.id) is True
        assert p.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        assert ExecutionPlanner().remove_execution_plan("missing") is False

    def test_clear_empties_planner(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan()
        p.create_execution_plan()
        p.clear()
        assert p.count() == 0
        assert p.list_execution_plans() == ()


class TestInsertionOrder:
    def test_list_preserves_order(self) -> None:
        p = ExecutionPlanner()
        for mid in ("a", "b", "c"):
            p.create_execution_plan(mapping_id=mid)
        assert [m.id for m in p.list_execution_plans()] == ["a", "b", "c"]

    def test_remove_preserves_relative_order(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan(mapping_id="a")
        p.create_execution_plan(mapping_id="b")
        p.create_execution_plan(mapping_id="c")
        p.remove_execution_plan("b")
        assert [m.id for m in p.list_execution_plans()] == ["a", "c"]


class TestStepsForGoalAndPlan:
    def test_steps_for_goal_filters(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan(mapping_id="m1", goal_id="g1")
        p.create_execution_plan(mapping_id="m2", goal_id="g2")
        p.create_execution_plan(mapping_id="m3", goal_id="g1")
        out = p.steps_for_goal("g1")
        assert [m.id for m in out] == ["m1", "m3"]

    def test_steps_for_plan_filters(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan(mapping_id="m1", plan_id="p1")
        p.create_execution_plan(mapping_id="m2", plan_id="p2")
        out = p.steps_for_plan("p1")
        assert [m.id for m in out] == ["m1"]

    def test_steps_for_unknown_returns_empty(self) -> None:
        assert ExecutionPlanner().steps_for_goal("nope") == ()


class TestExecutionOrderFromGraph:
    def test_topological_order_respects_dependencies(self) -> None:
        g = build_graph()
        p = ExecutionPlanner(task_graph=g)
        m = p.create_execution_plan()
        order = m.ordered_node_ids
        # a must come first, d must come last; b and c relative
        # order is free but stable.
        assert order[0] == "a"
        assert order[-1] == "d"
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_explicit_order_overrides_default(self) -> None:
        g = build_graph()
        p = ExecutionPlanner(task_graph=g)
        m = p.create_execution_plan(ordered_node_ids=("z", "y", "x"))
        assert m.ordered_node_ids == ("z", "y", "x")

    def test_execution_order_returns_tuple(self) -> None:
        g = build_graph()
        p = ExecutionPlanner(task_graph=g)
        m = p.create_execution_plan()
        out = p.execution_order(m.id)
        assert isinstance(out, tuple)

    def test_execution_order_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            ExecutionPlanner().execution_order("nope")

    def test_graph_only_used_when_no_explicit_order(self) -> None:
        g = build_graph()
        p = ExecutionPlanner(task_graph=g)
        # Without graph_reference we still use the wired graph.
        m = p.create_execution_plan()
        assert m.ordered_node_ids[0] == "a"


class TestImmutableSnapshots:
    def test_mapping_is_frozen(self) -> None:
        m = ExecutionPlanner().create_execution_plan()
        with pytest.raises(Exception):
            m.goal_reference = "x"  # type: ignore[misc]

    def test_list_returns_tuple(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan()
        assert isinstance(p.list_execution_plans(), tuple)

    def test_ordered_node_ids_is_tuple(self) -> None:
        m = ExecutionPlanner().create_execution_plan(ordered_node_ids=["a", "b"])
        assert isinstance(m.ordered_node_ids, tuple)

    def test_snapshot_does_not_track_later_inserts(self) -> None:
        p = ExecutionPlanner()
        p.create_execution_plan(mapping_id="a")
        snap = p.list_execution_plans()
        p.create_execution_plan(mapping_id="b")
        assert len(snap) == 1


class TestDeterministicBehavior:
    def test_two_planners_are_independent(self) -> None:
        a, b = ExecutionPlanner(), ExecutionPlanner()
        a.create_execution_plan()
        assert b.count() == 0

    def test_topological_order_is_stable(self) -> None:
        # Build the same graph twice; orders must match.
        g1, g2 = build_graph(), build_graph()
        p1, p2 = ExecutionPlanner(task_graph=g1), ExecutionPlanner(task_graph=g2)
        m1 = p1.create_execution_plan()
        m2 = p2.create_execution_plan()
        assert m1.ordered_node_ids == m2.ordered_node_ids


class TestPublicAPISurface:
    def test_exposes_expected_methods(self) -> None:
        p = ExecutionPlanner()
        for name in (
            "create_execution_plan", "update_execution_plan",
            "get_execution_plan", "list_execution_plans",
            "remove_execution_plan", "steps_for_goal",
            "steps_for_plan", "execution_order",
            "clear", "count",
        ):
            assert callable(getattr(p, name)), name

    def test_no_forbidden_attributes(self) -> None:
        p = ExecutionPlanner()
        for attr in (
            "memory_engine", "reflection_engine", "ai_service", "agent",
            "router", "registry", "engine", "context_manager",
            "conversation_history",
        ):
            assert not hasattr(p, attr), attr


class TestArchitecturalIsolation:
    def test_execution_planner_imports_only_allowed_modules(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "execution_planner.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        allowed_roots = {
            "__future__", "dataclasses", "enum", "threading", "time",
            "typing", "uuid", "collections", "collections.abc",
            "types", "contextlib",
        }
        allowed_full = {
            "core.goal_manager", "core.planning_engine", "core.task_graph",
        }
        forbidden_roots = {
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.reflection_engine",
            "core.problem_solver", "core.planner",
            "core.skill_dispatch", "core.skill_registry",
            "core.execution_coordinator", "core.execution_orchestrator",
            "core.execution_pipeline", "core.execution_session",
            "core.execution_result", "core.execution_progress",
            "core.execution_event",
            "memory",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                root = module.split(".")[0]
                assert root in allowed_roots or module in allowed_full, (
                    f"ExecutionPlanner must not import {module!r}"
                )
                assert root not in forbidden_roots, (
                    f"ExecutionPlanner must not import {module!r}"
                )
                assert not any(
                    module.startswith(f + ".") or module == f
                    for f in forbidden_roots
                )
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots, (
                        f"ExecutionPlanner must not import {n.name}"
                    )

    def test_does_not_embed_records(self) -> None:
        """ExecutionMapping must only hold opaque string identifiers,
        not actual Foundation record instances."""
        p = ExecutionPlanner()
        m = p.create_execution_plan(goal_id="g", plan_id="p", graph_id="gr")
        # These are plain strings, not record instances.
        assert isinstance(m.goal_reference, str)
        assert isinstance(m.plan_reference, str)
        assert isinstance(m.graph_reference, str)


class TestCoexistenceWithLegacyExecutionPlan:
    def test_legacy_execution_plan_still_importable(self) -> None:
        from core.planner import ExecutionPlan as LegacyExecutionPlan
        assert LegacyExecutionPlan is not ExecutionMapping
        assert LegacyExecutionPlan.__name__ == "ExecutionPlan"