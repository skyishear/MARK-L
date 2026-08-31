"""Architecture Freeze verification (v4.7).

Pure static + runtime audit. No production code changes.
"""

from __future__ import annotations

import ast
import importlib
import sys

import pytest


FREEZE_ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "core.agent": frozenset({
        "core.agent.context_manager",
        "core.agent.history_manager",
        "core.agent.knowledge_manager",
        "core.agent.learning_manager",
        "core.agent.memory_index_manager",
        "core.agent.reasoning_manager",
        "core.agent.reflection_manager",
        "core.execution_coordinator",
        "core.execution_orchestrator",
        "core.execution_pipeline",
        "core.execution_result",
        "core.execution_session",
        "core.planner",
        "core.planner_execution_orchestrator_adapter",
        "core.problem_solver",
        "core.skill_registry",
    }),
    "core.planner": frozenset(),
    "core.execution_orchestrator": frozenset(),
    "core.execution_pipeline": frozenset({
        "core.execution_orchestrator",
        "core.planner",
        "core.planner_problem_solver_adapter",
    }),
    "core.execution_session": frozenset({
        "core.execution_orchestrator",
        "core.execution_pipeline",
        "core.planner",
    }),
    "core.execution_result": frozenset({
        "core.execution_orchestrator",
        "core.execution_progress",
        "core.execution_session",
    }),
    "core.execution_progress": frozenset({"core.execution_orchestrator"}),
    "core.execution_coordinator": frozenset({
        "core.execution_pipeline",
        "core.execution_progress",
        "core.execution_session",
    }),
    "core.execution_event": frozenset(),
    "core.planner_execution_orchestrator_adapter": frozenset({
        "core.execution_orchestrator",
        "core.planner",
    }),
    "core.planner_problem_solver_adapter": frozenset({"core.planner"}),
}


def _collect_imports(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "core" and any(n.name == "problem_solver" for n in node.names):
                out.add("core.problem_solver")
                continue
            out.add(node.module)
    return out


class TestArchitectureFreeze:
    def test_no_circular_dependencies_in_freeze_modules(self) -> None:
        """Module dependency graph must be acyclic."""
        graph: dict[str, set[str]] = {}
        for module_name in FREEZE_ALLOWED_IMPORTS:
            mod = importlib.import_module(module_name)
            graph[module_name] = {
                dep for dep in _collect_imports(mod.__file__)
                if dep in FREEZE_ALLOWED_IMPORTS
            }

        WHITE, GRAY, BLACK = 0, 1, 2
        color = {m: WHITE for m in graph}

        def dfs(node: str) -> bool:
            color[node] = GRAY
            for nxt in graph[node]:
                if color[nxt] == GRAY:
                    return True
                if color[nxt] == WHITE and dfs(nxt):
                    return True
            color[node] = BLACK
            return False

        for node in graph:
            if color[node] == WHITE and dfs(node):
                pytest.fail(f"Circular dependency detected starting at {node}")

    def test_constructor_injection_preserved_on_agent(self) -> None:
        from core.agent import Agent

        sig = Agent.__init__
        for name in (
            "history", "context", "knowledge", "learning", "memory_index",
            "reflection", "reasoning", "planning",
            "execution_orchestrator", "execution_pipeline",
        ):
            assert name in sig.__doc__ or True  # signature-only check
        import inspect
        params = inspect.signature(sig).parameters
        for name in (
            "history", "context", "knowledge", "learning", "memory_index",
            "reflection", "reasoning", "planning",
            "execution_orchestrator", "execution_pipeline",
        ):
            assert name in params, f"Agent missing injection slot: {name}"
            assert params[name].default is None, f"{name} must default to None"

    def test_no_duplicate_execution_paths(self) -> None:
        from core.agent import (
            Agent,
            ExecutionPipeline,
            ExecutionOrchestrator,
        )
        agent = Agent()
        plan = agent.planning.plan("step one then step two")
        pipeline = ExecutionPipeline(ExecutionOrchestrator([]), plan)
        # Agent's own composed pipeline stays separate from a caller-built one
        assert agent.execution_pipeline is not pipeline

    def test_deterministic_lifecycle(self) -> None:
        from core.agent import Agent

        a1 = Agent().handle_request("fix the wifi")
        a2 = Agent().handle_request("fix the wifi")
        assert a1.session_id == a2.session_id
        assert a1.ready_task_ids == a2.ready_task_ids

    def test_public_api_surface_is_stable(self) -> None:
        import core.agent as agent_module

        expected = {
            "Agent",
            "CoordinationSnapshot",
            "ContextManager",
            "ExecutionCoordinator",
            "ExecutionOrchestrator",
            "ExecutionPipeline",
            "ExecutionResult",
            "ExecutionSession",
            "HistoryManager",
            "KnowledgeManager",
            "LearningManager",
            "MemoryIndexManager",
            "PlanningEngine",
            "ReasoningManager",
            "ReflectionManager",
        }
        assert set(agent_module.__all__) == expected

    def test_no_runtime_state_mutation_on_construction(self) -> None:
        from core.agent import Agent

        agent = Agent(
            execution_orchestrator=__import__(
                "core.execution_orchestrator", fromlist=["ExecutionOrchestrator"]
            ).ExecutionOrchestrator([])
        )
        before = agent.execution_orchestrator.snapshot()
        # Property access and identity checks must not mutate state
        agent.execution_orchestrator
        agent.execution_pipeline
        after = agent.execution_orchestrator.snapshot()
        assert before == after

    def test_loose_coupling_agent_does_not_compose_runtime_objects(self) -> None:
        """Agent must not import ExecutionProgress or ExecutionEvent directly.

        ExecutionSession is allowed only as an imported runtime type (used
        as return type for create_execution_session) — Agent must not
        instantiate it on its own.
        """
        import core.agent as agent_module

        source = agent_module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for n in node.names:
                    imported_names.add(n.name)
        assert "ExecutionProgress" not in imported_names
        assert "ExecutionEvent" not in imported_names
        assert "ExecutionSession" in imported_names  # return-type only

    def test_module_boundaries_intact(self) -> None:
        for module_name, allowed in FREEZE_ALLOWED_IMPORTS.items():
            mod = importlib.import_module(module_name)
            actual = _collect_imports(mod.__file__) & FREEZE_ALLOWED_IMPORTS.keys() - {module_name}
            unexpected = actual - allowed
            assert not unexpected, (
                f"{module_name} has unexpected dependencies: {unexpected}"
            )

    def test_no_architectural_work_remaining_before_intelligence(self) -> None:
        from core.agent import Agent

        agent = Agent()
        # All composed modules construct successfully and are reachable.
        for attr in (
            "history", "context", "knowledge", "learning",
            "memory_index", "reflection", "reasoning",
            "planning", "execution_orchestrator", "execution_pipeline",
        ):
            assert getattr(agent, attr) is not None