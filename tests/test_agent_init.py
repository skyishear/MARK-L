"""Tests for core.agent (the Agent composition root)."""

from __future__ import annotations

from core.agent import Agent
from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningManager
from core.agent.memory_index_manager import MemoryIndexManager
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager


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

    def test_default_modules_start_empty(self) -> None:
        agent = Agent()
        assert agent.history.get_history() == []
        assert len(agent.context) == 0
        assert len(agent.knowledge) == 0
        assert len(agent.learning) == 0
        assert len(agent.memory_index) == 0
        assert len(agent.reflection) == 0
        assert len(agent.reasoning) == 0

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
            "typing",
            "__future__",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module in allowed_module_names
