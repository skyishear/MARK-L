"""Tests for v8.3 Reflection Integration."""

from __future__ import annotations

import ast
import os

from core.agent import Agent
from core.agent.reflection_manager import (
    InvalidReflectionRecordError,
    ReflectionManager,
    ReflectionRecord,
)
from core.reflection_engine import ReflectionEngine


class TestAgentOwnsReflectionEngine:
    def test_default_agent_has_one_reflection_engine(self) -> None:
        a = Agent()
        assert isinstance(a.reflection_engine, ReflectionEngine)

    def test_injected_reflection_engine_is_used(self) -> None:
        e = ReflectionEngine()
        a = Agent(reflection_engine=e)
        assert a.reflection_engine is e

    def test_default_reflection_engine_is_fresh(self) -> None:
        assert Agent().reflection_engine is not Agent().reflection_engine

    def test_reflection_manager_uses_agent_engine(self) -> None:
        a = Agent()
        assert a.reflection.engine is a.reflection_engine


class TestReflectionManagerWiring:
    def test_default_manager_owns_a_fresh_engine(self) -> None:
        rm = ReflectionManager()
        assert isinstance(rm.engine, ReflectionEngine)

    def test_injected_engine_is_used(self) -> None:
        e = ReflectionEngine()
        rm = ReflectionManager(engine=e)
        assert rm.engine is e


class TestAddReflectionMirrorsIntoEngine:
    def test_add_reflection_writes_into_engine(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(
            subject="task-1",
            what_worked="all good",
            what_failed="nothing",
            confidence_level=0.9,
            completion_summary="done",
        )
        assert rm.engine.count() == 1

    def test_engine_records_preserve_subject_and_summary(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(subject="task-X", completion_summary="s")
        snap = rm.engine.recent_reflections()
        assert snap[0].summary == "task-X"

    def test_engine_records_carry_confidence(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(subject="t", confidence_level=0.42, completion_summary="s")
        snap = rm.engine.recent_reflections()
        assert abs(snap[0].confidence - 0.42) < 1e-9

    def test_engine_records_carry_mistakes_and_improvements(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(
            subject="t",
            mistakes_identified=["m1", "m2"],
            improvement_suggestions=["i1"],
            completion_summary="s",
        )
        snap = rm.engine.recent_reflections()
        assert "mistake=m1" in snap[0].details
        assert "mistake=m2" in snap[0].details
        assert "improve=i1" in snap[0].details

    def test_injected_engine_observed_by_manager(self) -> None:
        e = ReflectionEngine()
        rm = ReflectionManager(engine=e)
        rm.add_reflection(subject="t", completion_summary="s")
        assert e.count() == 1

    def test_invalid_confidence_does_not_write(self) -> None:
        rm = ReflectionManager()
        try:
            rm.add_reflection(subject="t", confidence_level=2.0)
        except InvalidReflectionRecordError:
            pass
        assert rm.engine.count() == 0


class TestAgentLifecycleIntegration:
    def test_agent_reflection_lifecycle_writes_to_engine(self) -> None:
        a = Agent()
        a.reflection.add_reflection(
            subject="task-1",
            what_worked="ok",
            confidence_level=0.8,
            completion_summary="done",
        )
        assert a.reflection_engine.count() == 1
        snap = a.reflection_engine.recent_reflections()
        assert snap[0].summary == "task-1"

    def test_agent_clear_all_empties_reflection_engine(self) -> None:
        a = Agent()
        a.reflection.add_reflection(subject="t", completion_summary="s")
        a.clear_all()
        assert a.reflection_engine.count() == 0

    def test_injected_reflection_engine_sees_all_writes(self) -> None:
        e = ReflectionEngine()
        a = Agent(reflection_engine=e)
        a.reflection.add_reflection(subject="t1", completion_summary="s")
        a.reflection.add_reflection(subject="t2", completion_summary="s")
        assert e.count() == 2


class TestNoDuplicateStores:
    def test_manager_records_and_engine_records_match(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(subject="t", completion_summary="s")
        assert len(rm) == 1
        assert rm.engine.count() == 1

    def test_clear_empties_both(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection(subject="t", completion_summary="s")
        rm.clear()
        assert len(rm) == 0
        assert rm.engine.count() == 0


class TestDependencyDirection:
    def test_reflection_engine_does_not_import_agent(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "reflection_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            source = f.read()
        for token in (
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.problem_solver", "core.planner",
            "core.skill_dispatch", "core.skill_registry",
        ):
            assert token not in source, (
                f"reflection_engine.py must not reference {token}"
            )

    def test_reflection_manager_is_only_integration_layer(self) -> None:
        """The Agent talks to the engine ONLY through the manager; the
        engine itself never references the manager."""
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "reflection_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            source = f.read()
        assert "reflection_manager" not in source, (
            "ReflectionEngine must not reference ReflectionManager"
        )


class TestArchitecturalIsolation:
    def test_reflection_engine_only_imports_stdlib(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "reflection_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        forbidden_roots = {"core", "memory"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in forbidden_roots
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots


class TestBackwardCompatibility:
    def test_existing_manager_api_unchanged(self) -> None:
        rm = ReflectionManager()
        # Old API surface still works.
        r = rm.add_reflection(
            subject="s",
            what_worked="w",
            what_failed="f",
            mistakes_identified=["m"],
            uncertainties=["u"],
            improvement_suggestions=["i"],
            confidence_level=0.5,
            completion_summary="c",
            metadata={"k": "v"},
        )
        assert isinstance(r, ReflectionRecord)
        assert rm.get(r.id) is r
        assert rm.get_by_subject("s") == [r]
        assert rm.get_all() == [r]

    def test_agent_constructs_without_explicit_reflection_engine(self) -> None:
        a = Agent()
        assert a.reflection_engine is not None
        assert a.reflection is not None