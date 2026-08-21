"""MARK L V3 Agent package.

Agent is the composition root for the Foundation modules living in
this package. It composes them and exposes their existing public
APIs together — it does NOT implement any of their functionality
itself, does NOT redesign or rewrite HistoryManager (kept exactly as
it already existed in this package, API unchanged), and performs no
reasoning, planning, tool execution, or persistence of its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningManager
from core.agent.memory_index_manager import MemoryIndexManager
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager
from core.execution_coordinator import CoordinationSnapshot, ExecutionCoordinator
from core.execution_orchestrator import ExecutionOrchestrator
from core.execution_pipeline import ExecutionPipeline
from core.execution_result import ExecutionResult, build_result_from_session
from core.execution_session import ExecutionSession, create_session
from core.planner import ExecutionPlan, Goal, PlanningEngine
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan
from core.problem_solver import gather_context

__all__ = [
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
]


def _default_execution_plan() -> ExecutionPlan:
    """A fixed, empty (zero-task) placeholder ExecutionPlan.

    Backs Agent's default ``execution_pipeline`` only, so
    ``ExecutionPipeline`` (which requires a plan) is still
    default-constructible with no caller input, matching every other
    Foundation module's zero-arg default. Built directly from
    ``core.planner``'s existing data types rather than via
    ``PlanningEngine.plan()`` (which requires a real, non-empty goal
    string) — no planning, execution, or side effect occurs. Its
    empty task set is never exercised unless a caller supplies real
    tasks via an injected ``ExecutionOrchestrator``/``ExecutionPipeline``.
    """
    now = datetime.now(timezone.utc)
    goal = Goal(id="agent-default-goal", description="agent-default", created_at=now)
    return ExecutionPlan(id="agent-default-plan", goal=goal, tasks=(), created_at=now)


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

    ``execution_orchestrator`` (``core.execution_orchestrator.
    ExecutionOrchestrator``) and ``execution_pipeline``
    (``core.execution_pipeline.ExecutionPipeline``, v3.5 Execution
    Runtime) are composed unchanged. Neither is exercised
    automatically: no task is executed, no ``ProblemSolver``/AI/
    Memory/Skill call is made, and no orchestrator state changes on
    construction. ``ExecutionSession``, ``ExecutionProgress``,
    ``ExecutionResult``, and ``ExecutionEvent`` remain runtime objects
    created later by higher-level flows — Agent does not compose or
    expose them.
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
        execution_orchestrator: ExecutionOrchestrator | None = None,
        execution_pipeline: ExecutionPipeline | None = None,
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
        self._execution_orchestrator = (
            execution_orchestrator
            if execution_orchestrator is not None
            else ExecutionOrchestrator([])
        )
        self._execution_pipeline = (
            execution_pipeline
            if execution_pipeline is not None
            else ExecutionPipeline(self._execution_orchestrator, _default_execution_plan())
        )

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

    @property
    def execution_orchestrator(self) -> ExecutionOrchestrator:
        """The composed ExecutionOrchestrator instance (v3.5 runtime, unchanged)."""
        return self._execution_orchestrator

    @property
    def execution_pipeline(self) -> ExecutionPipeline:
        """The composed ExecutionPipeline instance (v3.5 runtime, unchanged)."""
        return self._execution_pipeline

    def create_execution_session(
        self,
        plan: ExecutionPlan,
        *,
        orchestrator: ExecutionOrchestrator | None = None,
        pipeline: ExecutionPipeline | None = None,
        project: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionSession:
        """Build an ``ExecutionSession`` for ``plan`` (v3.8 end-to-end flow, Phase 1).

        Pure orchestration — reuses existing modules, adds no new
        logic of its own:

        - ``orchestrator`` is used as-is if supplied (reuse); otherwise
          one is built via the existing
          ``core.planner_execution_orchestrator_adapter.build_orchestrator_for_plan(plan)``.
        - ``pipeline`` is used as-is if supplied (reuse); otherwise one
          is built via the existing
          ``core.execution_pipeline.ExecutionPipeline(orchestrator, plan, project=project)``.
        - The three are combined into an ``ExecutionSession`` via the
          existing ``core.execution_session.create_session``.

        No task is executed, no ``mark_*`` method is called on any
        orchestrator (no state mutation), and this call never touches
        ``self._execution_orchestrator`` / ``self._execution_pipeline``
        — Agent's own composed defaults are left exactly as they were.
        Deterministic given the same ``plan`` and injected dependencies.
        """
        resolved_orchestrator = (
            orchestrator if orchestrator is not None else build_orchestrator_for_plan(plan)
        )
        resolved_pipeline = (
            pipeline
            if pipeline is not None
            else ExecutionPipeline(resolved_orchestrator, plan, project=project)
        )
        return create_session(
            plan,
            resolved_orchestrator,
            resolved_pipeline,
            session_id=session_id,
            metadata=metadata,
        )

    def coordinate_execution(self, session: ExecutionSession) -> CoordinationSnapshot:
        """Coordinate ``session`` via the existing ``ExecutionCoordinator`` (v4.0).

        Pure delegation — constructs no new logic: builds
        ``ExecutionCoordinator(session)`` and returns its
        ``coordinate()`` result unchanged. Read-only, deterministic,
        no state mutation, no execution.
        """
        return ExecutionCoordinator(session).coordinate()

    def handle_request(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> CoordinationSnapshot:
        """Run the full request lifecycle (v4.1): goal -> PlanningEngine ->
        ExecutionCoordinator -> ExecutionPipeline -> Planner->ProblemSolver
        Adapter -> immutable handoff objects. STOP — no execution beyond
        this point.

        Pure glue over existing methods, in order:
        ``self.planning.plan(goal)`` -> ``self.create_execution_session(plan, ...)``
        -> ``self.coordinate_execution(session)``. The pipeline's
        ``ready_descriptors()`` (already built via the existing
        Planner->ProblemSolver adapter) are included in the returned
        snapshot. No task execution, no ProblemSolver/Skill/Memory/AI
        call, no state mutation.
        """
        plan = self.planning.plan(goal)
        session = self.create_execution_session(plan, project=project, metadata=metadata)
        return self.coordinate_execution(session)

    def handle_request_with_context(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[CoordinationSnapshot, tuple[Mapping[str, Any], ...]]:
        """Extend ``handle_request`` (v4.1) with the ProblemSolver step (v4.2):
        goal -> ... -> Planner->ProblemSolver Adapter -> existing
        ProblemSolver integration (``core.problem_solver.gather_context``)
        -> STOP.

        Reuses ``self.handle_request(...)`` unchanged, then calls the
        existing ``gather_context(**kwargs)`` for every ready
        descriptor's already-built ``gather_context_kwargs``.
        ``gather_context`` only reads MemoryEngine (no writes); no
        Skill is invoked and no AI provider is called. Returns the
        snapshot together with each read-only context bundle; nothing
        further is done with the results.
        """
        snapshot = self.handle_request(goal, project=project, metadata=metadata)
        context_bundles = tuple(
            MappingProxyType(dict(gather_context(**descriptor.gather_context_kwargs)))
            for descriptor in snapshot.ready_descriptors
        )
        return snapshot, context_bundles

    def execute_request(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        """First complete executable request (v4.3): goal -> Planning ->
        Execution -> ProblemSolver Context -> existing ProblemSolver ->
        immutable ``ExecutionResult``. STOP.

        Pure glue only — no new runtime object is introduced;
        ``ExecutionResult`` already exists (v3.5). Reuses
        ``self.planning.plan``, ``self.create_execution_session``,
        ``self.coordinate_execution`` (Planning + Execution), feeds
        each ready descriptor's ``gather_context_kwargs`` to the
        existing ``core.problem_solver.gather_context`` (read-only:
        recall/why only, no write), and returns
        ``core.execution_result.build_result_from_session(session)``.
        No Skill invocation, no Memory write, no AI call.
        """
        plan = self.planning.plan(goal)
        session = self.create_execution_session(plan, project=project, metadata=metadata)
        coordination = self.coordinate_execution(session)
        for descriptor in coordination.ready_descriptors:
            gather_context(**descriptor.gather_context_kwargs)
        return build_result_from_session(session)

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only aggregate snapshot across Foundation modules.

        Built entirely from each module's existing public read methods.
        ``history`` uses the canonical HistoryManager's own
        ``get_history()`` (not ``get_all()``). ``memory_index``
        contributes only its indexed-item count, since it stores no
        content to list. ``planning``, ``execution_orchestrator``, and
        ``execution_pipeline`` are omitted: none has a compatible
        zero-argument read method that reports meaningful aggregate
        state the way the other modules' does.
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
        stateless and holds nothing to clear. ``execution_orchestrator``
        and ``execution_pipeline`` are likewise excluded: neither has a
        clear-equivalent public method, and clearing orchestrator state
        here would mean modifying runtime state, which this integration
        does not do.
        """
        self._history.clear()
        self._context.clear()
        self._knowledge.clear()
        self._learning.clear()
        self._memory_index.clear()
        self._reflection.clear()
        self._reasoning.clear()
