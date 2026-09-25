"""Tests for v8.6 Goal Manager (Foundation Layer)."""

from __future__ import annotations

import ast
import os

import pytest

from core.goal_manager import (
    GoalManager,
    GoalPriority,
    GoalRecord,
    GoalStatus,
)


class TestEmpty:
    def test_count_is_zero(self) -> None:
        assert GoalManager().count() == 0

    def test_list_goals_is_empty(self) -> None:
        assert GoalManager().list_goals() == ()

    def test_len_is_zero(self) -> None:
        assert len(GoalManager()) == 0

    def test_get_unknown_returns_none(self) -> None:
        assert GoalManager().get_goal("nope") is None


class TestCreateGoal:
    def test_returns_record(self) -> None:
        g = GoalManager()
        r = g.create_goal(title="t")
        assert isinstance(r, GoalRecord)
        assert r.title == "t"
        assert r.description == ""
        assert r.priority == GoalPriority.MEDIUM
        assert r.status == GoalStatus.DRAFT
        assert r.plan_reference is None
        assert r.graph_reference is None
        assert r.tags == ()

    def test_id_auto_generated(self) -> None:
        r = GoalManager().create_goal(title="t")
        assert isinstance(r.id, str) and len(r.id) > 0

    def test_explicit_id_preserved(self) -> None:
        r = GoalManager().create_goal(title="t", goal_id="g1")
        assert r.id == "g1"

    def test_duplicate_id_rejected(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        with pytest.raises(ValueError):
            g.create_goal(title="t", goal_id="g1")

    def test_blank_title_rejected(self) -> None:
        g = GoalManager()
        with pytest.raises(ValueError):
            g.create_goal(title="")
        with pytest.raises(ValueError):
            g.create_goal(title="   ")

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            GoalManager().create_goal(title="t", status="bogus")

    def test_invalid_priority_rejected(self) -> None:
        with pytest.raises(ValueError):
            GoalManager().create_goal(title="t", priority="urgent")

    def test_invalid_tags_rejected(self) -> None:
        g = GoalManager()
        with pytest.raises(ValueError):
            g.create_goal(title="t", tags=("ok", ""))
        with pytest.raises(ValueError):
            g.create_goal(title="t", tags="not-a-sequence")

    def test_blank_reference_rejected(self) -> None:
        g = GoalManager()
        with pytest.raises(ValueError):
            g.create_goal(title="t", plan_reference="")
        with pytest.raises(ValueError):
            g.create_goal(title="t", graph_reference="   ")

    def test_create_increments_count(self) -> None:
        g = GoalManager()
        g.create_goal(title="a")
        g.create_goal(title="b")
        assert g.count() == 2


class TestUpdateGoal:
    def test_updates_title(self) -> None:
        g = GoalManager()
        r = g.create_goal(title="old", goal_id="g1")
        new = g.update_goal("g1", title="new")
        assert new.title == "new"
        assert g.get_goal("g1").title == "new"

    def test_updates_status_and_priority(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        new = g.update_goal(
            "g1", status=GoalStatus.ACTIVE, priority=GoalPriority.HIGH
        )
        assert new.status == GoalStatus.ACTIVE
        assert new.priority == GoalPriority.HIGH

    def test_updates_references(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        new = g.update_goal("g1", plan_reference="p-1", graph_reference="g-1")
        assert new.plan_reference == "p-1"
        assert new.graph_reference == "g-1"

    def test_updates_tags(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        new = g.update_goal("g1", tags=("a", "b"))
        assert new.tags == ("a", "b")

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError):
            GoalManager().update_goal("missing", title="x")

    def test_blank_title_rejected(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        with pytest.raises(ValueError):
            g.update_goal("g1", title="")

    def test_blank_reference_rejected(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        with pytest.raises(ValueError):
            g.update_goal("g1", plan_reference="")

    def test_updated_at_refreshed(self) -> None:
        g = GoalManager()
        r = g.create_goal(title="t", goal_id="g1")
        new = g.update_goal("g1", title="t2")
        assert new.updated_at >= r.updated_at
        assert new.created_at == r.created_at


class TestRemoveAndClear:
    def test_remove_existing_returns_true(self) -> None:
        g = GoalManager()
        g.create_goal(title="t", goal_id="g1")
        assert g.remove_goal("g1") is True
        assert g.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        assert GoalManager().remove_goal("missing") is False

    def test_clear_empties_manager(self) -> None:
        g = GoalManager()
        g.create_goal(title="a")
        g.create_goal(title="b")
        g.clear()
        assert g.count() == 0
        assert g.list_goals() == ()


class TestInsertionOrder:
    def test_list_preserves_order(self) -> None:
        g = GoalManager()
        for gid in ("a", "b", "c"):
            g.create_goal(title=gid, goal_id=gid)
        assert [r.id for r in g.list_goals()] == ["a", "b", "c"]

    def test_remove_preserves_relative_order(self) -> None:
        g = GoalManager()
        g.create_goal(title="a", goal_id="a")
        g.create_goal(title="b", goal_id="b")
        g.create_goal(title="c", goal_id="c")
        g.remove_goal("b")
        assert [r.id for r in g.list_goals()] == ["a", "c"]


class TestListFilters:
    def test_filter_by_status(self) -> None:
        g = GoalManager()
        g.create_goal(title="a", status=GoalStatus.DRAFT, goal_id="a")
        g.create_goal(title="b", status=GoalStatus.ACTIVE, goal_id="b")
        g.create_goal(title="c", status=GoalStatus.ACTIVE, goal_id="c")
        out = g.list_goals(status=GoalStatus.ACTIVE)
        assert [r.id for r in out] == ["b", "c"]

    def test_filter_by_priority(self) -> None:
        g = GoalManager()
        g.create_goal(title="a", priority=GoalPriority.LOW, goal_id="a")
        g.create_goal(title="b", priority=GoalPriority.HIGH, goal_id="b")
        out = g.list_goals(priority=GoalPriority.HIGH)
        assert [r.id for r in out] == ["b"]

    def test_filter_combined(self) -> None:
        g = GoalManager()
        g.create_goal(
            title="a", status=GoalStatus.ACTIVE,
            priority=GoalPriority.HIGH, goal_id="a",
        )
        g.create_goal(
            title="b", status=GoalStatus.ACTIVE,
            priority=GoalPriority.LOW, goal_id="b",
        )
        out = g.list_goals(status=GoalStatus.ACTIVE, priority=GoalPriority.HIGH)
        assert [r.id for r in out] == ["a"]


class TestReferencesAreOptional:
    def test_create_with_no_references(self) -> None:
        r = GoalManager().create_goal(title="t")
        assert r.plan_reference is None
        assert r.graph_reference is None

    def test_create_with_references(self) -> None:
        r = GoalManager().create_goal(
            title="t", plan_reference="plan-1", graph_reference="graph-1"
        )
        assert r.plan_reference == "plan-1"
        assert r.graph_reference == "graph-1"

    def test_references_are_plain_strings(self) -> None:
        r = GoalManager().create_goal(title="t", plan_reference="p1")
        # No method to dereference — just ensure the type is plain.
        assert isinstance(r.plan_reference, str)


class TestImmutableSnapshots:
    def test_record_is_frozen(self) -> None:
        r = GoalManager().create_goal(title="t")
        with pytest.raises(Exception):
            r.title = "x"  # type: ignore[misc]

    def test_list_returns_tuple(self) -> None:
        g = GoalManager()
        g.create_goal(title="t")
        assert isinstance(g.list_goals(), tuple)

    def test_tags_is_tuple(self) -> None:
        r = GoalManager().create_goal(title="t", tags=["a", "b"])
        assert isinstance(r.tags, tuple)

    def test_snapshot_does_not_track_later_inserts(self) -> None:
        g = GoalManager()
        g.create_goal(title="a", goal_id="a")
        snap = g.list_goals()
        g.create_goal(title="b", goal_id="b")
        assert len(snap) == 1


class TestDeterministicBehavior:
    def test_two_managers_are_independent(self) -> None:
        a, b = GoalManager(), GoalManager()
        a.create_goal(title="x")
        assert b.count() == 0

    def test_get_goal_returns_same_value(self) -> None:
        g = GoalManager()
        r = g.create_goal(title="t", goal_id="g1")
        assert g.get_goal("g1") is r
        assert g.get_goal("g1") == r


class TestPublicAPISurface:
    def test_exposes_expected_methods(self) -> None:
        g = GoalManager()
        for name in (
            "create_goal", "update_goal", "get_goal",
            "list_goals", "remove_goal", "clear", "count",
        ):
            assert callable(getattr(g, name)), name

    def test_no_forbidden_attributes(self) -> None:
        g = GoalManager()
        for attr in (
            "memory_engine", "reflection_engine", "planning_engine",
            "task_graph", "ai_service", "agent", "router", "registry",
            "engine", "context_manager",
        ):
            assert not hasattr(g, attr), attr


class TestArchitecturalIsolation:
    def test_goal_manager_imports_only_stdlib(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "goal_manager.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        allowed_roots = {
            "__future__", "dataclasses", "enum", "threading", "time",
            "typing", "uuid", "collections.abc", "types", "contextlib",
        }
        forbidden_roots = {"core", "memory"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root in allowed_roots, (
                    f"GoalManager must not import {node.module!r}"
                )
                assert root not in forbidden_roots
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots, (
                        f"GoalManager must not import {n.name}"
                    )

    def test_goal_manager_does_not_reference_forbidden_modules(self) -> None:
        import ast as _ast

        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "goal_manager.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = _ast.parse(f.read())
        forbidden = (
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.reflection_engine",
            "core.problem_solver", "core.planner", "core.planning_engine",
            "core.task_graph", "core.goal_manager",
            "core.skill_dispatch", "core.skill_registry",
        )
        for node in _ast.walk(tree):
            target = None
            if isinstance(node, _ast.ImportFrom) and node.module:
                target = node.module
            elif isinstance(node, _ast.Import):
                for n in node.names:
                    for f in forbidden:
                        assert not n.name.startswith(f), (
                            f"goal_manager.py must not import {n.name}"
                        )
                continue
            if target is not None:
                for f in forbidden:
                    assert not target.startswith(f), (
                        f"goal_manager.py must not import {target}"
                    )


class TestCoexistenceWithLegacyGoal:
    def test_legacy_goal_record_still_importable(self) -> None:
        """The pre-existing ``core.planner.Goal`` dataclass must keep
        working alongside the new Foundation module."""
        from core.planner import Goal as LegacyGoal
        assert LegacyGoal is not GoalRecord
        assert LegacyGoal.__name__ == "Goal"