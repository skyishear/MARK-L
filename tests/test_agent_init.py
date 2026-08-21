"""Tests for core.agent (the Agent composition root)."""

from __future__ import annotations

import pytest

from core.agent import Agent
from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningManager
from core.agent.memory_index_manager import MemoryIndexManager
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager
from core.execution_orchestrator import ExecutionOrchestrator, OrchestratedTask, TaskState
from core.execution_pipeline import ExecutionPipeline
from core.execution_result import ExecutionResult
from core.execution_session import ExecutionSession
from core.planner import ExecutionPlan, PlanningEngine


class TestDefaultConstruction:
    def test_default_construction_creates_all_modules(self) -> None:
        agent = Agent()
        assert isinstance(agent.history, HistoryManager)
        assert isinstance(agent.context, ContextManager)
        assert isinstance(agent.knowledge, KnowledgeManager)
        assert isinstance(agent.learning, LearningManager)
        assert isinstance(agent.memory_index, MemoryIndexManager)
        assert isinstance(agent.reflection, ReflectionManager)
        assert isinstance(agent.reasoning, ReasoningManager)
        assert isinstance(agent.planning, PlanningEngine)
        assert isinstance(agent.execution_orchestrator, ExecutionOrchestrator)
        assert isinstance(agent.execution_pipeline, ExecutionPipeline)

    def test_default_modules_start_empty(self) -> None:
        agent = Agent()
        assert agent.history.get_history() == []
        assert len(agent.context) == 0
        assert len(agent.knowledge) == 0
        assert len(agent.learning) == 0
        assert len(agent.memory_index) == 0
        assert len(agent.reflection) == 0
        assert len(agent.reasoning) == 0

    def test_default_execution_orchestrator_has_no_tasks(self) -> None:
        agent = Agent()
        assert agent.execution_orchestrator.order == ()
        assert agent.execution_pipeline.ready_task_ids() == ()

    def test_two_default_agents_have_independent_modules(self) -> None:
        agent1 = Agent()
        agent2 = Agent()
        agent1.history.record("event", "only in agent1")
        assert agent2.history.get_history() == []


class TestInjectedConstruction:
    def test_injected_history_is_used(self) -> None:
        history = HistoryManager()
        history.record("event", "pre-existing")
        agent = Agent(history=history)
        assert agent.history is history
        assert len(agent.history.get_history()) == 1

    def test_injected_context_is_used(self) -> None:
        context = ContextManager()
        context.set("k", "v")
        agent = Agent(context=context)
        assert agent.context is context
        assert agent.context.get("k") == "v"

    def test_injected_knowledge_is_used(self) -> None:
        knowledge = KnowledgeManager()
        agent = Agent(knowledge=knowledge)
        assert agent.knowledge is knowledge

    def test_injected_learning_is_used(self) -> None:
        learning = LearningManager()
        agent = Agent(learning=learning)
        assert agent.learning is learning

    def test_injected_memory_index_is_used(self) -> None:
        memory_index = MemoryIndexManager()
        agent = Agent(memory_index=memory_index)
        assert agent.memory_index is memory_index

    def test_injected_reflection_is_used(self) -> None:
        reflection = ReflectionManager()
        agent = Agent(reflection=reflection)
        assert agent.reflection is reflection

    def test_injected_reasoning_is_used(self) -> None:
        reasoning = ReasoningManager()
        agent = Agent(reasoning=reasoning)
        assert agent.reasoning is reasoning

    def test_injected_planning_is_used(self) -> None:
        planning = PlanningEngine()
        agent = Agent(planning=planning)
        assert agent.planning is planning

    def test_injected_execution_orchestrator_is_used(self) -> None:
        orchestrator = ExecutionOrchestrator(
            [OrchestratedTask(task_id="t1", depends_on=())]
        )
        agent = Agent(execution_orchestrator=orchestrator)
        assert agent.execution_orchestrator is orchestrator
        assert agent.execution_orchestrator.order == ("t1",)

    def test_injected_execution_pipeline_is_used(self) -> None:
        orchestrator = ExecutionOrchestrator([])
        plan = PlanningEngine().plan("write the report")
        pipeline = ExecutionPipeline(orchestrator, plan)
        agent = Agent(execution_pipeline=pipeline)
        assert agent.execution_pipeline is pipeline

    def test_partial_injection_defaults_the_rest(self) -> None:
        history = HistoryManager()
        agent = Agent(history=history)
        assert agent.history is history
        assert isinstance(agent.context, ContextManager)
        assert isinstance(agent.knowledge, KnowledgeManager)


class TestProperties:
    def test_properties_return_same_instance_across_calls(self) -> None:
        agent = Agent()
        assert agent.history is agent.history
        assert agent.context is agent.context
        assert agent.knowledge is agent.knowledge
        assert agent.learning is agent.learning
        assert agent.memory_index is agent.memory_index
        assert agent.reflection is agent.reflection
        assert agent.reasoning is agent.reasoning
        assert agent.planning is agent.planning
        assert agent.execution_orchestrator is agent.execution_orchestrator
        assert agent.execution_pipeline is agent.execution_pipeline

    def test_execution_orchestrator_and_pipeline_share_the_same_orchestrator(self) -> None:
        agent = Agent()
        assert agent.execution_pipeline.ready_task_ids() == agent.execution_orchestrator.order

    def test_no_task_is_executed_and_no_orchestrator_state_changes(self) -> None:
        agent = Agent(
            execution_orchestrator=ExecutionOrchestrator(
                [OrchestratedTask(task_id="t1", depends_on=())]
            )
        )
        before = agent.execution_orchestrator.snapshot()
        agent.execution_pipeline
        agent.execution_orchestrator
        after = agent.execution_orchestrator.snapshot()
        assert before == after
        assert agent.execution_orchestrator.get_state("t1") == TaskState.PENDING

    def test_planning_produces_a_plan_without_touching_other_modules(self) -> None:
        agent = Agent()
        result = agent.planning.plan("write the report")
        assert isinstance(result, ExecutionPlan)
        assert agent.history.get_history() == []
        assert len(agent.context) == 0


class TestSnapshot:
    def test_snapshot_on_empty_agent(self) -> None:
        agent = Agent()
        snap = agent.snapshot()
        assert snap["history"] == []
        assert snap["context"] == {}
        assert snap["knowledge"] == []
        assert snap["learning"] == []
        assert snap["memory_index_count"] == 0
        assert snap["reflection"] == []
        assert snap["reasoning"] == []

    def test_snapshot_reflects_history_state_via_canonical_api(self) -> None:
        agent = Agent()
        agent.history.record("event", "started")
        snap = agent.snapshot()
        assert len(snap["history"]) == 1
        assert snap["history"][0].description == "started"

    def test_snapshot_reflects_context_state(self) -> None:
        agent = Agent()
        agent.context.set("active_project", "mark_l")
        snap = agent.snapshot()
        assert snap["context"] == {"active_project": "mark_l"}

    def test_snapshot_reflects_knowledge_state(self) -> None:
        agent = Agent()
        agent.knowledge.add("topic", "content")
        snap = agent.snapshot()
        assert len(snap["knowledge"]) == 1

    def test_snapshot_reflects_learning_state(self) -> None:
        agent = Agent()
        agent.learning.record_preference("dark_mode")
        snap = agent.snapshot()
        assert len(snap["learning"]) == 1

    def test_snapshot_reflects_memory_index_count(self) -> None:
        agent = Agent()
        agent.memory_index.index("item1", {"tag"})
        snap = agent.snapshot()
        assert snap["memory_index_count"] == 1

    def test_snapshot_reflects_reflection_state(self) -> None:
        agent = Agent()
        agent.reflection.add_reflection("task_a")
        snap = agent.snapshot()
        assert len(snap["reflection"]) == 1

    def test_snapshot_reflects_reasoning_state(self) -> None:
        agent = Agent()
        agent.reasoning.add_reasoning("problem")
        snap = agent.snapshot()
        assert len(snap["reasoning"]) == 1

    def test_snapshot_omits_planning(self) -> None:
        agent = Agent()
        snap = agent.snapshot()
        assert "planning" not in snap

    def test_snapshot_omits_execution_orchestrator_and_pipeline(self) -> None:
        agent = Agent()
        snap = agent.snapshot()
        assert "execution_orchestrator" not in snap
        assert "execution_pipeline" not in snap

    def test_snapshot_context_is_a_copy(self) -> None:
        agent = Agent()
        agent.context.set("k", "v")
        snap = agent.snapshot()
        snap["context"]["k"] = "mutated"
        assert agent.context.get("k") == "v"


class TestClearAll:
    def test_clear_all_empties_every_module(self) -> None:
        agent = Agent()
        agent.history.record("event", "e")
        agent.context.set("k", "v")
        agent.knowledge.add("t", "c")
        agent.learning.record_observation("s")
        agent.memory_index.index("item1", {"tag"})
        agent.reflection.add_reflection("task")
        agent.reasoning.add_reasoning("problem")

        agent.clear_all()

        assert agent.history.get_history() == []
        assert len(agent.context) == 0
        assert len(agent.knowledge) == 0
        assert len(agent.learning) == 0
        assert len(agent.memory_index) == 0
        assert len(agent.reflection) == 0
        assert len(agent.reasoning) == 0

    def test_clear_all_on_empty_agent_is_safe(self) -> None:
        agent = Agent()
        agent.clear_all()
        assert agent.history.get_history() == []


class TestCreateExecutionSession:
    def test_builds_session_with_plan_orchestrator_pipeline_metadata(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("step one then step two")
        session = agent.create_execution_session(plan, metadata={"source": "test"})
        assert isinstance(session, ExecutionSession)
        assert session.plan is plan
        assert isinstance(session.orchestrator, ExecutionOrchestrator)
        assert isinstance(session.pipeline, ExecutionPipeline)
        assert dict(session.metadata) == {"source": "test"}

    def test_built_orchestrator_matches_plan_tasks(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("step one then step two")
        session = agent.create_execution_session(plan)
        assert session.orchestrator.order == tuple(t.id for t in plan.execution_order())
        assert session.pipeline.ready_task_ids() == (plan.tasks[0].id,)

    def test_injected_orchestrator_and_pipeline_are_reused(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = ExecutionOrchestrator(
            [OrchestratedTask(task_id=plan.tasks[0].id, depends_on=())]
        )
        pipeline = ExecutionPipeline(orchestrator, plan)
        session = agent.create_execution_session(plan, orchestrator=orchestrator, pipeline=pipeline)
        assert session.orchestrator is orchestrator
        assert session.pipeline is pipeline

    def test_does_not_mutate_agent_composed_defaults(self) -> None:
        agent = Agent()
        default_orchestrator = agent.execution_orchestrator
        default_pipeline = agent.execution_pipeline
        plan = PlanningEngine().plan("fix the wifi")
        agent.create_execution_session(plan)
        assert agent.execution_orchestrator is default_orchestrator
        assert agent.execution_pipeline is default_pipeline
        assert agent.execution_orchestrator.order == ()

    def test_no_orchestrator_state_changes(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        session = agent.create_execution_session(plan)
        assert session.orchestrator.get_state(plan.tasks[0].id) == TaskState.PENDING

    def test_deterministic_for_same_plan(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        session1 = agent.create_execution_session(plan)
        session2 = agent.create_execution_session(plan)
        assert session1.id == session2.id
        assert session1.orchestrator.order == session2.orchestrator.order


class TestCoordinateExecution:
    def test_delegates_to_execution_coordinator(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("step one then step two")
        session = agent.create_execution_session(plan)
        snapshot = agent.coordinate_execution(session)
        assert snapshot.session_id == session.id
        assert snapshot.ready_task_ids == (plan.tasks[0].id,)

    def test_no_state_mutation(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        session = agent.create_execution_session(plan)
        before = session.orchestrator.snapshot()
        agent.coordinate_execution(session)
        assert session.orchestrator.snapshot() == before


class TestHandleRequest:
    def test_full_lifecycle_returns_ready_descriptors(self) -> None:
        agent = Agent()
        snapshot = agent.handle_request("step one then step two", project="mark_l")
        assert len(snapshot.ready_descriptors) == 1
        descriptor = snapshot.ready_descriptors[0]
        assert descriptor.work_item.problem == "step one"
        assert descriptor.gather_context_kwargs["project"] == "mark_l"

    def test_deterministic_for_same_goal(self) -> None:
        agent = Agent()
        first = agent.handle_request("fix the wifi")
        second = agent.handle_request("fix the wifi")
        assert first.session_id == second.session_id
        assert first.ready_task_ids == second.ready_task_ids


class TestHandleRequestWithContext:
    @pytest.fixture(autouse=True)
    def _stub_memory_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core import problem_solver

        monkeypatch.setattr(problem_solver, "recall", lambda **kwargs: [])
        monkeypatch.setattr(problem_solver, "why", lambda *args, **kwargs: [])

    def test_returns_snapshot_and_context_bundle_per_ready_task(self) -> None:
        agent = Agent()
        snapshot, bundles = agent.handle_request_with_context("fix the wifi")
        assert len(bundles) == 1
        assert bundles[0]["known_solutions"] == []
        assert len(snapshot.ready_descriptors) == 1

    def test_no_state_mutation(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        session = agent.create_execution_session(plan)
        before = session.orchestrator.snapshot()
        agent.handle_request_with_context("fix the wifi")
        assert session.orchestrator.snapshot() == before


class TestExecuteRequest:
    @pytest.fixture(autouse=True)
    def _stub_memory_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core import problem_solver

        monkeypatch.setattr(problem_solver, "recall", lambda **kwargs: [])
        monkeypatch.setattr(problem_solver, "why", lambda *args, **kwargs: [])

    def test_returns_execution_result(self) -> None:
        agent = Agent()
        result = agent.execute_request("fix the wifi")
        assert isinstance(result, ExecutionResult)
        assert result.progress.total == 1
        assert result.progress.pending == 1
        assert result.success is False  # no task executed, still pending

    def test_no_task_execution_or_state_mutation(self) -> None:
        agent = Agent()
        plan = PlanningEngine().plan("fix the wifi")
        session = agent.create_execution_session(plan)
        before = session.orchestrator.snapshot()
        agent.execute_request("fix the wifi")
        assert session.orchestrator.snapshot() == before


class TestNoForbiddenIntegration:
    def test_agent_module_only_imports_foundation_siblings(self) -> None:
        import ast

        import core.agent as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_module_names = {
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
            "datetime",
            "types",
            "typing",
            "__future__",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module in allowed_module_names
