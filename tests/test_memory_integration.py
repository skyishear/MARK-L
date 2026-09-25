"""Tests for v8.1 Memory Integration (Agent <-> MemoryEngine)."""

from __future__ import annotations

import pytest

from core.agent import Agent
from core.agent.memory_adapter import (
    bind_memory_engine,
    persist_to_memory_engine,
    query_memory_engine,
    remove_from_memory_engine,
)
from core.memory_engine import MemoryEngine
from core.problem_solver import (
    gather_context,
    get_memory_engine,
    record_outcome,
    set_memory_engine,
)


@pytest.fixture(autouse=True)
def _isolate_memory_engine():
    """Snapshot the module-level engine and restore it after each
    test so cross-test leakage does not occur."""
    saved = get_memory_engine()
    set_memory_engine(MemoryEngine())
    try:
        yield
    finally:
        set_memory_engine(saved)


class TestAgentInstallsItsOwnEngine:
    def test_agent_memory_engine_is_canonical_for_problem_solver(self) -> None:
        a = Agent()
        assert get_memory_engine() is a.memory_engine

    def test_injected_engine_propagates_to_problem_solver(self) -> None:
        e = MemoryEngine()
        Agent(memory_engine=e)
        assert get_memory_engine() is e


class TestNoDuplicateStores:
    def test_problem_solver_writes_go_into_agent_engine(self) -> None:
        a = Agent()
        rid = a.memory_engine.remember("a", "k", "v")
        # Read back via the module-level getter; same store.
        assert a.memory_engine.recall(category="a")[0]["id"] == rid
        # And via the public module proxy.
        import core.problem_solver as ps
        assert ps.recall(category="a")[0]["id"] == rid

    def test_record_outcome_uses_agent_engine(self) -> None:
        a = Agent()
        rid = record_outcome(
            "wifi down", "loose cable", "reseat", "success", project="mark_l"
        )
        assert a.memory_engine.count() == 1
        row = a.memory_engine.recall(id=rid) if False else a.memory_engine.recall(
            category="problems_solutions"
        )[0]
        assert row["id"] == rid
        assert "wifi down" in row["value"]

    def test_gather_context_uses_agent_engine(self) -> None:
        a = Agent()
        a.memory_engine.remember(
            "problems_solutions", "fixme", "SOLVED | problem: x | cause: y | solution: z | outcome: success",
            project="p",
        )
        ctx = gather_context("x", project="p")
        assert ctx["has_known_fix"] is True
        assert ctx["known_solutions"]


class TestMemoryAdapterUsesMemoryEngine:
    def test_bind_memory_engine_returns_three_callables(self) -> None:
        e = MemoryEngine()
        remember_fn, recall_fn, forget_fn = bind_memory_engine(e)
        rid = remember_fn("cat", "k", "v", importance=4)
        rows = recall_fn(category="cat")
        assert rows and rows[0]["id"] == rid
        assert forget_fn(key="k") == 1

    def test_persist_and_query_against_bound_engine(self) -> None:
        e = MemoryEngine()
        remember_fn, recall_fn, _forget_fn = bind_memory_engine(e)
        rid = persist_to_memory_engine(
            remember_fn, category="cat", key="k", value="v"
        )
        rows = query_memory_engine(recall_fn, category="cat")
        assert rows and rows[0]["id"] == rid

    def test_remove_against_bound_engine(self) -> None:
        e = MemoryEngine()
        remember_fn, recall_fn, forget_fn = bind_memory_engine(e)
        persist_to_memory_engine(remember_fn, category="cat", key="k", value="v")
        assert remove_from_memory_engine(forget_fn, key="k") == 1
        assert query_memory_engine(recall_fn, category="cat") == []


class TestAgentAndProblemSolverShareState:
    def test_remember_then_recall_via_agent_and_problem_solver(self) -> None:
        a = Agent()
        rid = a.memory_engine.remember("facts", "k1", "v1", project="p")
        # Same store, two views.
        from core import problem_solver
        rows = problem_solver.recall(category="facts", project="p")
        assert len(rows) == 1
        assert rows[0]["id"] == rid

    def test_record_outcome_visible_via_agent_engine(self) -> None:
        a = Agent()
        record_outcome("wifi", "loose", "reseat", "success", project="p")
        assert a.memory_engine.count() == 1

    def test_forget_propagates_between_views(self) -> None:
        a = Agent()
        a.memory_engine.remember("facts", "k", "v")
        from core import problem_solver
        assert problem_solver.forget(key="k") == 1
        assert a.memory_engine.count() == 0


class TestInjectedEngineRespected:
    def test_injecting_engine_also_changes_problem_solver_view(self) -> None:
        e1 = MemoryEngine()
        Agent(memory_engine=e1)
        assert get_memory_engine() is e1
        e2 = MemoryEngine()
        Agent(memory_engine=e2)
        assert get_memory_engine() is e2


class TestDependencyDirection:
    """The dependency direction is::

        Agent
          ↓
        MemoryAdapter / ProblemSolver
          ↓
        MemoryEngine

    MemoryEngine must NOT import any of those modules.
    """

    def test_memory_engine_does_not_import_agent(self) -> None:
        import ast
        import core.memory_engine as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        forbidden = ("core.agent", "core.ai_service", "core.ai_provider",
                    "core.ai_provider_router", "core.ai_conversation_engine",
                    "core.context_manager", "core.problem_solver",
                    "core.memory_adapter")
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.ImportFrom) and node.module:
                target = node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    if any(n.name.startswith(f) for f in forbidden):
                        raise AssertionError(
                            f"MemoryEngine must not import {n.name}"
                        )
                continue
            if target and any(target.startswith(f) for f in forbidden):
                raise AssertionError(
                    f"MemoryEngine must not import {target}"
                )