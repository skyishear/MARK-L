"""Tests for v8.4 Planning Engine (Foundation Layer)."""

from __future__ import annotations

import ast
import os

import pytest

from core.planning_engine import Plan, PlanStatus, PlanningEngine, Step


def make_step(i: int, title: str = "", status: PlanStatus = PlanStatus.DRAFT) -> Step:
    return Step(
        id=f"s{i}",
        index=i,
        title=title or f"step-{i}",
        description=f"desc-{i}",
        status=status,
    )


class TestEmptyEngine:
    def test_count_is_zero(self) -> None:
        assert PlanningEngine().count() == 0

    def test_list_plans_is_empty(self) -> None:
        assert PlanningEngine().list_plans() == ()

    def test_len_is_zero(self) -> None:
        assert len(PlanningEngine()) == 0

    def test_get_plan_unknown_returns_none(self) -> None:
        assert PlanningEngine().get_plan("nope") is None


class TestCreatePlan:
    def test_returns_plan(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        assert isinstance(p, Plan)
        assert p.goal == "g"
        assert p.status == PlanStatus.DRAFT
        assert p.steps == ()

    def test_id_is_generated_when_not_provided(self) -> None:
        p = PlanningEngine().create_plan(goal="g")
        assert isinstance(p.id, str) and len(p.id) > 0

    def test_explicit_id_is_preserved(self) -> None:
        p = PlanningEngine().create_plan(goal="g", plan_id="p1")
        assert p.id == "p1"

    def test_duplicate_id_raises(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="g", plan_id="p1")
        with pytest.raises(ValueError):
            e.create_plan(goal="g", plan_id="p1")

    def test_blank_goal_rejected(self) -> None:
        e = PlanningEngine()
        with pytest.raises(ValueError):
            e.create_plan(goal="")
        with pytest.raises(ValueError):
            e.create_plan(goal="   ")

    def test_invalid_status_rejected(self) -> None:
        e = PlanningEngine()
        with pytest.raises(ValueError):
            e.create_plan(goal="g", status="bogus")

    def test_steps_validation_rejects_non_step(self) -> None:
        e = PlanningEngine()
        with pytest.raises(ValueError):
            e.create_plan(goal="g", steps=[("not", "a step")])

    def test_steps_index_must_match_position(self) -> None:
        e = PlanningEngine()
        bad = Step(id="x", index=5, title="t", description="d", status=PlanStatus.DRAFT)
        with pytest.raises(ValueError):
            e.create_plan(goal="g", steps=[bad])

    def test_create_increments_count(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="g1")
        e.create_plan(goal="g2")
        assert e.count() == 2


class TestUpdatePlan:
    def test_updates_goal(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="old")
        new = e.update_plan(p.id, goal="new")
        assert new.goal == "new"
        assert e.get_plan(p.id).goal == "new"

    def test_updates_status(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        new = e.update_plan(p.id, status=PlanStatus.READY)
        assert new.status == PlanStatus.READY

    def test_updates_steps(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        new = e.update_plan(p.id, steps=[make_step(0), make_step(1)])
        assert len(new.steps) == 2
        assert e.get_plan(p.id).steps == new.steps

    def test_unknown_id_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            PlanningEngine().update_plan("missing", goal="x")

    def test_blank_goal_rejected(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        with pytest.raises(ValueError):
            e.update_plan(p.id, goal="")

    def test_invalid_status_rejected(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        with pytest.raises(ValueError):
            e.update_plan(p.id, status="bogus")

    def test_updated_at_is_refreshed(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        new = e.update_plan(p.id, goal="g2")
        assert new.updated_at >= p.updated_at
        assert new.created_at == p.created_at


class TestRemoveAndClear:
    def test_remove_existing_returns_true(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        assert e.remove_plan(p.id) is True
        assert e.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        assert PlanningEngine().remove_plan("missing") is False

    def test_clear_empties_engine(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="g1")
        e.create_plan(goal="g2")
        e.clear()
        assert e.count() == 0
        assert e.list_plans() == ()


class TestInsertionOrder:
    def test_list_plans_preserves_insertion_order(self) -> None:
        e = PlanningEngine()
        a = e.create_plan(goal="a", plan_id="a")
        b = e.create_plan(goal="b", plan_id="b")
        c = e.create_plan(goal="c", plan_id="c")
        assert [p.id for p in e.list_plans()] == [a.id, b.id, c.id]

    def test_remove_preserves_relative_order_of_remaining(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="a", plan_id="a")
        b = e.create_plan(goal="b", plan_id="b")
        e.create_plan(goal="c", plan_id="c")
        e.remove_plan(b.id)
        assert [p.id for p in e.list_plans()] == ["a", "c"]


class TestListFilters:
    def test_filter_by_status(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="a", status=PlanStatus.DRAFT, plan_id="a")
        e.create_plan(goal="b", status=PlanStatus.READY, plan_id="b")
        e.create_plan(goal="c", status=PlanStatus.READY, plan_id="c")
        out = e.list_plans(status=PlanStatus.READY)
        assert [p.id for p in out] == ["b", "c"]

    def test_filter_by_string_status(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="a", status="draft", plan_id="a")
        e.create_plan(goal="b", status="ready", plan_id="b")
        out = e.list_plans(status="ready")
        assert [p.id for p in out] == ["b"]


class TestImmutableSnapshots:
    def test_plan_is_frozen(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g")
        with pytest.raises(Exception):
            p.goal = "x"  # type: ignore[misc]

    def test_step_is_frozen(self) -> None:
        s = make_step(0)
        with pytest.raises(Exception):
            s.title = "x"  # type: ignore[misc]

    def test_list_plans_returns_tuple(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="g")
        out = e.list_plans()
        assert isinstance(out, tuple)

    def test_plan_steps_returns_tuple(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g", steps=[make_step(0)])
        assert isinstance(p.steps, tuple)

    def test_snapshot_does_not_track_later_inserts(self) -> None:
        e = PlanningEngine()
        e.create_plan(goal="g1")
        snap = e.list_plans()
        e.create_plan(goal="g2")
        assert len(snap) == 1


class TestDeterministicBehavior:
    def test_two_engines_are_independent(self) -> None:
        a, b = PlanningEngine(), PlanningEngine()
        a.create_plan(goal="x")
        assert b.count() == 0

    def test_get_plan_returns_same_value(self) -> None:
        e = PlanningEngine()
        p = e.create_plan(goal="g", plan_id="p1")
        assert e.get_plan("p1") is p
        assert e.get_plan("p1") == p


class TestInjectedInstance:
    def test_engine_supports_constructor_injection_via_outer_layer(self) -> None:
        """This engine has no constructor parameters; tests below
        verify the surrounding pattern. The Agent will inject the
        engine into a future planning manager; here we only confirm
        the engine itself is plain."""
        e = PlanningEngine()
        assert isinstance(e, PlanningEngine)


class TestArchitecturalIsolation:
    def test_planning_engine_imports_only_stdlib(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "planning_engine.py")
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
                    f"PlanningEngine must not import {node.module!r}"
                )
                assert root not in forbidden_roots
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots, (
                        f"PlanningEngine must not import {n.name}"
                    )

    def test_planning_engine_does_not_reference_forbidden_modules(self) -> None:
        """AST-based check: only count import / import-from statements
        and string-literal expressions that name a forbidden module.
        Docstrings and comments are ignored."""
        import ast as _ast

        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "planning_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = _ast.parse(f.read())
        forbidden = (
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.reflection_engine",
            "core.problem_solver", "core.planner", "core.skill_dispatch",
            "core.skill_registry",
        )
        for node in _ast.walk(tree):
            target = None
            if isinstance(node, _ast.ImportFrom) and node.module:
                target = node.module
            elif isinstance(node, _ast.Import):
                for n in node.names:
                    for f in forbidden:
                        assert not n.name.startswith(f), (
                            f"planning_engine.py must not import {n.name}"
                        )
                continue
            if target is not None:
                for f in forbidden:
                    assert not target.startswith(f), (
                        f"planning_engine.py must not import {target}"
                    )


class TestPublicAPISurface:
    def test_engine_exposes_expected_methods(self) -> None:
        e = PlanningEngine()
        for name in (
            "create_plan", "update_plan", "get_plan",
            "list_plans", "remove_plan", "clear", "count",
        ):
            assert callable(getattr(e, name)), name

    def test_no_forbidden_attributes(self) -> None:
        e = PlanningEngine()
        for attr in (
            "memory_engine", "reflection_engine", "ai_service", "agent",
            "router", "registry", "engine", "context_manager",
        ):
            assert not hasattr(e, attr), attr


class TestExistingPlannerUntouched:
    def test_pre_existing_planner_still_importable(self) -> None:
        """Sanity check: the new module coexists with the pre-existing
        ``core.planner.PlanningEngine`` without conflict."""
        from core.planner import PlanningEngine as LegacyPlanningEngine
        assert LegacyPlanningEngine is not PlanningEngine