"""Tests for v8.2 Reflection Engine (Foundation Layer)."""

from __future__ import annotations

import ast
import os

import pytest

from core.reflection_engine import Reflection, ReflectionEngine


class TestStartsEmpty:
    def test_count_is_zero(self) -> None:
        assert ReflectionEngine().count() == 0

    def test_recent_reflections_is_empty_tuple(self) -> None:
        assert ReflectionEngine().recent_reflections() == ()

    def test_len_is_zero(self) -> None:
        assert len(ReflectionEngine()) == 0


class TestRecordReflection:
    def test_returns_reflection_with_id_and_timestamp(self) -> None:
        e = ReflectionEngine()
        r = e.record_reflection(category="c", summary="s")
        assert isinstance(r, Reflection)
        assert isinstance(r.id, str) and len(r.id) > 0
        assert isinstance(r.timestamp, float)

    def test_stores_canonical_fields(self) -> None:
        e = ReflectionEngine()
        r = e.record_reflection(
            category="cat",
            summary="sum",
            details="det",
            source="src",
            project="p",
            confidence=0.7,
            importance=4,
        )
        assert r.category == "cat"
        assert r.summary == "sum"
        assert r.details == "det"
        assert r.source == "src"
        assert r.project == "p"
        assert r.confidence == 0.7
        assert r.importance == 4

    def test_defaults(self) -> None:
        e = ReflectionEngine()
        r = e.record_reflection(category="c", summary="s")
        assert r.details == ""
        assert r.source == "engine"
        assert r.project is None
        assert r.confidence == 1.0
        assert r.importance == 3

    def test_record_increments_count(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="s")
        e.record_reflection(category="c", summary="s")
        assert e.count() == 2


class TestInsertionOrder:
    def test_order_preserved(self) -> None:
        e = ReflectionEngine()
        a = e.record_reflection(category="c", summary="a")
        b = e.record_reflection(category="c", summary="b")
        c = e.record_reflection(category="c", summary="c")
        out = e.recent_reflections()
        assert [r.summary for r in out] == ["a", "b", "c"]
        assert [r.id for r in out] == [a.id, b.id, c.id]

    def test_timestamp_monotonic_with_insertion(self) -> None:
        e = ReflectionEngine()
        a = e.record_reflection(category="c", summary="a")
        b = e.record_reflection(category="c", summary="b")
        assert a.timestamp <= b.timestamp


class TestCountAndClear:
    def test_count_reflects_inserts_and_clears(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="s")
        e.record_reflection(category="c", summary="s")
        assert e.count() == 2
        e.clear()
        assert e.count() == 0

    def test_clear_on_empty_is_safe(self) -> None:
        ReflectionEngine().clear()


class TestImmutableSnapshots:
    def test_recent_reflections_returns_tuple(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="s")
        out = e.recent_reflections()
        assert isinstance(out, tuple)

    def test_reflection_is_frozen(self) -> None:
        e = ReflectionEngine()
        r = e.record_reflection(category="c", summary="s")
        with pytest.raises(Exception):
            r.summary = "mutated"  # type: ignore[misc]

    def test_returned_snapshot_does_not_track_later_inserts(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="a")
        snap = e.recent_reflections()
        e.record_reflection(category="c", summary="b")
        assert len(snap) == 1

    def test_returned_snapshot_mutation_does_not_affect_engine(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="a")
        snap = e.recent_reflections()
        assert e.count() == 1
        # Tuples are immutable; ``+`` creates a new tuple. Engine
        # state is unchanged by reading the snapshot.
        new_ref = e.record_reflection(category="c", summary="b")
        snap2 = snap + (new_ref,)
        assert e.count() == 2
        assert len(snap) == 1
        assert len(snap2) == 2


class TestInvalidInput:
    def test_blank_category_rejected(self) -> None:
        e = ReflectionEngine()
        with pytest.raises(ValueError):
            e.record_reflection(category="", summary="s")
        with pytest.raises(ValueError):
            e.record_reflection(category="   ", summary="s")

    def test_blank_summary_rejected(self) -> None:
        e = ReflectionEngine()
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="")
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="   ")

    def test_blank_source_rejected(self) -> None:
        e = ReflectionEngine()
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="s", source="")

    def test_confidence_out_of_range_rejected(self) -> None:
        e = ReflectionEngine()
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="s", confidence=-0.1)
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="s", confidence=1.5)

    def test_importance_out_of_range_rejected(self) -> None:
        e = ReflectionEngine()
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="s", importance=0)
        with pytest.raises(ValueError):
            e.record_reflection(category="c", summary="s", importance=6)


class TestFiltersAndLimit:
    def test_filter_by_category(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="a", summary="x")
        e.record_reflection(category="b", summary="y")
        assert [r.summary for r in e.recent_reflections(category="a")] == ["x"]

    def test_filter_by_project(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="x", project="p1")
        e.record_reflection(category="c", summary="y", project="p2")
        assert [r.summary for r in e.recent_reflections(project="p1")] == ["x"]

    def test_filter_by_source(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="c", summary="x", source="learning")
        e.record_reflection(category="c", summary="y", source="agent")
        assert [r.summary for r in e.recent_reflections(source="learning")] == ["x"]

    def test_limit_caps_results(self) -> None:
        e = ReflectionEngine()
        for i in range(5):
            e.record_reflection(category="c", summary=str(i))
        assert len(e.recent_reflections(limit=3)) == 3

    def test_combined_filters(self) -> None:
        e = ReflectionEngine()
        e.record_reflection(category="a", summary="x", project="p")
        e.record_reflection(category="a", summary="y", project="q")
        out = e.recent_reflections(category="a", project="p")
        assert [r.summary for r in out] == ["x"]


class TestDeterministicBehavior:
    def test_repeat_calls_with_no_state_yield_equal_results(self) -> None:
        e1 = ReflectionEngine()
        e2 = ReflectionEngine()
        assert e1.recent_reflections() == e2.recent_reflections()
        assert e1.count() == e2.count()

    def test_id_is_unique_per_record(self) -> None:
        e = ReflectionEngine()
        ids = {
            e.record_reflection(category="c", summary=str(i)).id
            for i in range(20)
        }
        assert len(ids) == 20


class TestInjectedInstance:
    def test_two_engines_are_independent(self) -> None:
        a, b = ReflectionEngine(), ReflectionEngine()
        a.record_reflection(category="c", summary="x")
        assert b.count() == 0


class TestArchitecturalIsolation:
    def test_reflection_engine_imports_only_allowed_modules(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "reflection_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_roots = {
            "__future__", "dataclasses", "threading", "time",
            "typing", "uuid", "collections.abc", "types",
            "contextlib",
        }
        forbidden_roots = {
            "core", "memory",
        }
        seen: list[str] = []
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    seen.append(n.name)
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots, (
                        f"ReflectionEngine must not import {n.name}"
                    )
                continue
            if module is not None:
                seen.append(module)
                root = module.split(".")[0]
                assert root in allowed_roots, (
                    f"ReflectionEngine must not import {module!r} "
                    f"(root {root!r} is forbidden)"
                )

    def test_reflection_engine_does_not_import_ai_modules(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "reflection_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            source = f.read()
        forbidden = (
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.problem_solver", "core.planner",
            "core.skill_dispatch", "core.skill_registry",
        )
        for token in forbidden:
            assert token not in source, (
                f"reflection_engine.py must not reference {token}"
            )


class TestPublicAPISurface:
    def test_engine_exposes_expected_methods(self) -> None:
        e = ReflectionEngine()
        for name in (
            "record_reflection", "recent_reflections",
            "count", "clear",
        ):
            assert callable(getattr(e, name)), name

    def test_no_ai_or_memory_attributes(self) -> None:
        e = ReflectionEngine()
        for attr in (
            "memory", "memory_engine", "ai_service", "agent",
            "router", "registry", "engine", "context_manager",
        ):
            assert not hasattr(e, attr), attr