"""MARK L V3 Agent package.

Agent is the composition root for the Foundation modules living in
this package. It composes them and exposes their existing public
APIs together — it does NOT implement any of their functionality
itself, does NOT redesign or rewrite HistoryManager (kept exactly as
it already existed in this package, API unchanged), and performs no
reasoning, planning, tool execution, or persistence of its own.
"""

from __future__ import annotations

from typing import Any

from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningManager
from core.agent.memory_index_manager import MemoryIndexManager
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager
from core.planner import PlanningEngine

__all__ = [
    "Agent",
    "ContextManager",
    "HistoryManager",
    "KnowledgeManager",
    "LearningManager",
    "MemoryIndexManager",
    "PlanningEngine",
    "ReasoningManager",
    "ReflectionManager",
]


class Agent:
    """Composition root for the MARK L V3 Foundation modules.

    Holds one instance of each Foundation module and exposes them
    through read-only properties, plus thin aggregate helpers
    (``snapshot`` and ``clear_all``) built entirely from each module's
    existing public methods. Agent introduces no reasoning, planning,
    execution, or persistence of its own.

    ``history`` is ``core.agent.history_manager.HistoryManager`` —
    the package's pre-existing, canonical implementation, kept
    unchanged (``record`` / ``get_history`` / ``latest`` / ``summary``
    / ``clear``), not the ``add_event`` / ``get_all`` style API used
    by the other Foundation modules in this package.

    ``planning`` is ``core.planner.PlanningEngine`` (v3.1.0 Planning
    Engine, Phase 1), composed unchanged. It is stateless — ``plan()``
    is a pure function of a goal string with no stored state, no
    execution, no memory access, and no AI calls — so it holds no
    data for ``snapshot()`` or ``clear_all()`` to report or clear.
    """

    def __init__(
        self,
        history: HistoryManager | None = None,
        context: ContextManager | None = None,
        knowledge: KnowledgeManager | None = None,
        learning: LearningManager | None = None,
        memory_index: MemoryIndexManager | None = None,
        reflection: ReflectionManager | None = None,
        reasoning: ReasoningManager | None = None,
        planning: PlanningEngine | None = None,
    ) -> None:
        """Compose the Agent from Foundation module instances.

        Each argument defaults to a fresh instance of the corresponding
        module when not supplied, so ``Agent()`` is fully usable
        standalone. Supplying an existing instance lets the caller
        share state with a module used elsewhere.
        """
        self._history = history if history is not None else HistoryManager()
        self._context = context if context is not None else ContextManager()
        self._knowledge = knowledge if knowledge is not None else KnowledgeManager()
        self._learning = learning if learning is not None else LearningManager()
        self._memory_index = (
            memory_index if memory_index is not None else MemoryIndexManager()
        )
        self._reflection = reflection if reflection is not None else ReflectionManager()
        self._reasoning = reasoning if reasoning is not None else ReasoningManager()
        self._planning = planning if planning is not None else PlanningEngine()

    @property
    def history(self) -> HistoryManager:
        """The composed HistoryManager instance (canonical, unchanged API)."""
        return self._history

    @property
    def context(self) -> ContextManager:
        """The composed ContextManager instance."""
        return self._context

    @property
    def knowledge(self) -> KnowledgeManager:
        """The composed KnowledgeManager instance."""
        return self._knowledge

    @property
    def learning(self) -> LearningManager:
        """The composed LearningManager instance."""
        return self._learning

    @property
    def memory_index(self) -> MemoryIndexManager:
        """The composed MemoryIndexManager instance."""
        return self._memory_index

    @property
    def reflection(self) -> ReflectionManager:
        """The composed ReflectionManager instance."""
        return self._reflection

    @property
    def reasoning(self) -> ReasoningManager:
        """The composed ReasoningManager instance."""
        return self._reasoning

    @property
    def planning(self) -> PlanningEngine:
        """The composed PlanningEngine instance (stateless; core.planner, unchanged)."""
        return self._planning

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only aggregate snapshot across Foundation modules.

        Built entirely from each module's existing public read methods.
        ``history`` uses the canonical HistoryManager's own
        ``get_history()`` (not ``get_all()``). ``memory_index``
        contributes only its indexed-item count, since it stores no
        content to list. ``planning`` is omitted: PlanningEngine is
        stateless and its only public API, ``plan(goal)``, requires a
        goal argument and creates a new plan rather than reading
        existing state, so there is nothing for a read-only snapshot
        to report.
        """
        return {
            "history": self._history.get_history(),
            "context": self._context.snapshot(),
            "knowledge": self._knowledge.get_all(),
            "learning": self._learning.get_all(),
            "memory_index_count": len(self._memory_index),
            "reflection": self._reflection.get_all(),
            "reasoning": self._reasoning.get_all(),
        }

    def clear_all(self) -> None:
        """Clear every composed Foundation module.

        Delegates to each module's existing ``clear`` method; performs
        no logic of its own. ``planning`` has no ``clear()`` — it is
        stateless and holds nothing to clear.
        """
        self._history.clear()
        self._context.clear()
        self._knowledge.clear()
        self._learning.clear()
        self._memory_index.clear()
        self._reflection.clear()
        self._reasoning.clear()
