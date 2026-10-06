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
from typing import Any, Callable, Mapping, Sequence

from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningManager
from core.agent.memory_index_manager import MemoryIndexManager
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.conversation_history import ConversationHistory, Message
from core.memory_engine import MemoryEngine
from core.problem_solver import set_memory_engine
from core.reflection_engine import ReflectionEngine
from core.execution_coordinator import CoordinationSnapshot, ExecutionCoordinator
from core.execution_orchestrator import ExecutionOrchestrator
from core.execution_pipeline import ExecutionPipeline
from core.execution_result import ExecutionResult, build_result_from_session
from core.execution_session import ExecutionSession, create_session
from core.planner import ExecutionPlan, Goal, InvalidGoalError, PlanningEngine, PlanValidationError
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan
from core.problem_solver import gather_context, record_outcome as record_problem_outcome
from core.skill_dispatch import SkillDispatchDecision, build_dispatch_decision
from core.skill_registry import dispatch as skill_dispatch, is_registered
# v8.x Foundation stores (v8.10 bridge). ``PlanningEngine`` is aliased
# because the legacy ``core.planner.PlanningEngine`` above keeps its name.
from core.execution_failure import normalize_execution_failure
from core.memory_context import MemoryRequest
from core.failure_taxonomy import FailureCategory, classify_failure
from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager, GoalStatus
from core.lifecycle_reflection import reflect_execution_completed, reflect_execution_started
from core.pipeline_engine import PipelineEngine
from core.pipeline_run import PipelineRun, PipelineRunManager, PipelineRunStatus
from core.plan_projection import PlanProjection, project_execution_plan
from core.stage_dispatch import build_stage_dispatch_decisions
from core.step_lifecycle import reflect_step_completed, reflect_step_reached, reflect_step_skipped
from core.planning_engine import PlanStatus, PlanningEngine as FoundationPlanningEngine
from core.task_graph import TaskGraph
# v8.11–v8.14 tool stack (v8.15 bridge): composition only, no dispatch path.
from core.tool_dispatch import ToolDispatchDecision, build_tool_dispatch_decision
from core.tool_interface import ToolRequest, ToolResult, TransientToolError
from core.tool_registry import ToolRegistry
from core.tool_catalog import ToolCatalog
from core.tool_router import ToolNotFoundError, ToolRouter
from core.tool_runtime import ToolLoopResult, run_tool_loop

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
    "SkillDispatchDecision",
]


def _classify_execution_failure(exc: BaseException) -> FailureCategory:
    """Classify an execution failure by exception type only (v8.30).

    The execution rule table is owned by the composition root (which
    composes the planner and the tool router) and built per call, so the
    module holds no state. Only exception types whose documented meaning
    supports a category are listed; everything else — including
    ``ToolError`` and generic Python exceptions — is UNKNOWN. The only
    TRANSIENT class is ``TransientToolError`` (v8.33), the tool's explicit
    signal; UNKNOWN is never treated as transient.
    Classification itself changes nothing; its only consumer is the v8.33
    bounded in-run retry (``_route_with_transient_retry``).
    """
    rules: dict[type, FailureCategory] = {
        ToolNotFoundError: FailureCategory.PERMANENT,  # "tool_name is not registered"
        InvalidGoalError: FailureCategory.INVALID_INPUT,  # "goal cannot be planned"
        PlanValidationError: FailureCategory.INVALID_INPUT,  # "task graph is invalid"
        TransientToolError: FailureCategory.TRANSIENT,  # v8.33: tool-declared temporary
    }
    return classify_failure(exc, rules)


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

    ``goal_manager`` / ``planning_engine`` / ``task_graph`` /
    ``execution_planner`` / ``pipeline_engine`` /
    ``pipeline_run_manager`` are the v8.x Foundation stores (v8.10
    bridge), composed unchanged and purely additively. Defaults are
    wired to each other in dependency order; an injected instance is
    used verbatim and its own collaborators are never reconciled with
    Agent's siblings. None of them executes anything, and all start
    empty on construction. ``planning_engine`` is the v8.4
    ``core.planning_engine.PlanningEngine``, distinct from the legacy
    ``planning`` above.

    ``tool_registry`` / ``tool_router`` are the v8.12 / v8.14 tool
    stack (v8.15 bridge), composed with the same rule: defaults wired
    in dependency order (``ToolRouter(tool_registry)``), injected
    instances used verbatim and never reconciled. They are composition
    only — no request-handling method consults the router, the legacy
    ``skill_registry`` dispatch path is unchanged, and the registry
    starts empty. Neither participates in ``snapshot()`` /
    ``clear_all()`` (same ownership rule as ``memory_engine``).
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
        ai_service: AIService | None = None,
        conversation_history: ConversationHistory | None = None,
        memory_engine: MemoryEngine | None = None,
        reflection_engine: ReflectionEngine | None = None,
        goal_manager: GoalManager | None = None,
        planning_engine: FoundationPlanningEngine | None = None,
        task_graph: TaskGraph | None = None,
        execution_planner: ExecutionPlanner | None = None,
        pipeline_engine: PipelineEngine | None = None,
        pipeline_run_manager: PipelineRunManager | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_router: ToolRouter | None = None,
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
        self._reflection_engine = (
            reflection_engine if reflection_engine is not None else ReflectionEngine()
        )
        if reflection is not None:
            self._reflection = reflection
        else:
            self._reflection = ReflectionManager(engine=self._reflection_engine)
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
        self._ai_service = ai_service if ai_service is not None else AIService()
        self._conversation_history = (
            conversation_history if conversation_history is not None else ConversationHistory()
        )
        self._memory_engine = (
            memory_engine if memory_engine is not None else MemoryEngine()
        )
        # Install the engine as the canonical memory backend for
        # ``core.problem_solver`` so every memory operation in the
        # Agent's lifecycle flows through this single store.
        set_memory_engine(self._memory_engine)
        # v8.x Foundation stores, resolved in dependency order. Defaults
        # are wired to the already-resolved siblings; an injected
        # instance is used verbatim (no reconciliation).
        self._goal_manager = goal_manager if goal_manager is not None else GoalManager()
        self._planning_engine = (
            planning_engine if planning_engine is not None else FoundationPlanningEngine()
        )
        self._task_graph = task_graph if task_graph is not None else TaskGraph()
        self._execution_planner = (
            execution_planner
            if execution_planner is not None
            else ExecutionPlanner(
                goal_manager=self._goal_manager,
                planning_engine=self._planning_engine,
                task_graph=self._task_graph,
            )
        )
        self._pipeline_engine = (
            pipeline_engine
            if pipeline_engine is not None
            else PipelineEngine(self._execution_planner, task_graph=self._task_graph)
        )
        self._pipeline_run_manager = (
            pipeline_run_manager
            if pipeline_run_manager is not None
            else PipelineRunManager(self._pipeline_engine)
        )
        # v8.15 tool bridge: same rule as above — resolve in dependency
        # order, wire defaults to the resolved sibling, use injected
        # instances verbatim with no reconciliation. Nothing in Agent's
        # request handling calls the router; the legacy skill_registry
        # dispatch path is untouched.
        self._tool_registry = tool_registry if tool_registry is not None else ToolRegistry()
        self._tool_router = (
            tool_router if tool_router is not None else ToolRouter(self._tool_registry)
        )
        # v8.32: Agent-owned v8.31 ToolCatalog (metadata only; separate from
        # the registry). No constructor parameter: the v8.15 / v8.21 pins fix
        # the signature. Consulted only by ``resume_failed_run`` (O4).
        self._tool_catalog = ToolCatalog()

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

    @property
    def goal_manager(self) -> GoalManager:
        """The composed v8.6 GoalManager store (unchanged)."""
        return self._goal_manager

    @property
    def planning_engine(self) -> FoundationPlanningEngine:
        """The composed v8.4 core.planning_engine.PlanningEngine store (unchanged)."""
        return self._planning_engine

    @property
    def task_graph(self) -> TaskGraph:
        """The composed v8.5 TaskGraph store (unchanged)."""
        return self._task_graph

    @property
    def execution_planner(self) -> ExecutionPlanner:
        """The composed v8.7 ExecutionPlanner store (unchanged)."""
        return self._execution_planner

    @property
    def pipeline_engine(self) -> PipelineEngine:
        """The composed v8.8 PipelineEngine store (unchanged)."""
        return self._pipeline_engine

    @property
    def pipeline_run_manager(self) -> PipelineRunManager:
        """The composed v8.9 PipelineRunManager store (unchanged)."""
        return self._pipeline_run_manager

    @property
    def tool_registry(self) -> ToolRegistry:
        """The composed v8.12 ToolRegistry (unchanged; empty by default)."""
        return self._tool_registry

    @property
    def tool_router(self) -> ToolRouter:
        """The composed v8.14 ToolRouter (unchanged; not used by request handling)."""
        return self._tool_router

    @property
    def tool_catalog(self) -> ToolCatalog:
        """The Agent-owned v8.31 ToolCatalog (v8.32; empty by default).

        Tool metadata only — register ``ToolSpec``s here. Consulted solely by
        ``resume_failed_run`` to decide whether a failed step may be resumed.
        """
        return self._tool_catalog

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

        Pure glue only — delegates the planning -> session ->
        coordinator -> ProblemSolver context lifecycle to
        ``self.execute_request_with_skill_check`` (the canonical
        v4.4 chain) and returns the same ``ExecutionResult`` it
        produces. No new runtime object is introduced;
        ``ExecutionResult`` already exists (v3.5). No Skill
        invocation, no Memory write, no AI call.
        """
        result, _skill_checks = self.execute_request_with_skill_check(
            goal, project=project, metadata=metadata
        )
        return result

    def execute_request_with_skill_check(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[Mapping[str, Any], ...]]:
        """Extend ``execute_request`` (v4.3) with a controlled SkillRegistry
        check (v4.4): completed ProblemSolver output -> existing
        ``core.skill_registry.is_registered`` -> STOP before actual
        tool execution (``dispatch`` is never called).

        Pure glue: reuses ``self.planning.plan``,
        ``self.create_execution_session``, ``self.coordinate_execution``,
        and ``core.problem_solver.gather_context`` exactly as
        ``execute_request`` does, then for each ready descriptor calls
        the existing, read-only ``is_registered(descriptor.work_item.problem)``
        to report whether a matching skill exists. Returns the existing
        ``ExecutionResult`` (v3.5) plus one read-only skill-check
        record per ready task, in deterministic order. No Memory
        write, no AI call, no Skill execution.
        """
        plan = self.planning.plan(goal)
        session = self.create_execution_session(plan, project=project, metadata=metadata)
        coordination = self.coordinate_execution(session)
        skill_checks = []
        for descriptor in coordination.ready_descriptors:
            gather_context(**descriptor.gather_context_kwargs)
            skill_checks.append(
                MappingProxyType(
                    {
                        "task_id": descriptor.task_id,
                        "tool_name": descriptor.work_item.problem,
                        "is_registered": is_registered(descriptor.work_item.problem),
                    }
                )
            )
        result = build_result_from_session(session)
        return result, tuple(skill_checks)

    def execute_request_with_dispatch_decision(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[SkillDispatchDecision, ...]]:
        """Extend ``execute_request_with_skill_check`` (v4.4) with the
        controlled dispatch decision (v5.0): existing execution chain
        (Planning -> Session -> Coordinator -> ProblemSolver Context ->
        SkillRegistry check) -> immutable ``SkillDispatchDecision``
        per ready task -> STOP.

        Pure glue over the existing chain: delegates the full lifecycle
        to ``self.execute_request_with_skill_check`` (which already
        invokes ``planning``, ``create_execution_session``,
        ``coordinate_execution``, ``problem_solver.gather_context``,
        and ``core.skill_registry.is_registered``), then maps each
        returned read-only skill-check record to an immutable
        ``SkillDispatchDecision`` via the pure
        ``core.skill_dispatch.build_dispatch_decision``. No ``dispatch``
        call, no Memory write, no AI call, no skill execution, no tool
        invocation.
        """
        result, skill_checks = self.execute_request_with_skill_check(
            goal, project=project, metadata=metadata
        )
        decisions = tuple(
            build_dispatch_decision(
                task_id=check["task_id"],
                tool_name=check["tool_name"],
                context={"project": project},
            )
            for check in skill_checks
        )
        return result, decisions

    def execute_request_with_skill_execution(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[SkillDispatchDecision, ...]]:
        """Extend ``execute_request_with_dispatch_decision`` (v5.0) with
        controlled skill execution (v5.1): existing execution chain
        (Planning -> Session -> Coordinator -> ProblemSolver Context ->
        SkillRegistry check -> Dispatch Decision) -> existing
        ``core.skill_registry.dispatch`` per ready task whose dispatch
        decision allows dispatch -> existing ``ExecutionResult`` -> STOP.

        Pure glue over the existing chain: delegates the full lifecycle
        (planning, session, coordinator, ProblemSolver context, skill
        check, dispatch decision) to
        ``self.execute_request_with_dispatch_decision``. For each
        returned ``SkillDispatchDecision``, invokes
        ``core.skill_registry.dispatch`` **only** when
        ``would_dispatch is True``. Unregistered / ``skip`` decisions
        never invoke ``dispatch``. No AI call, no Memory write, no
        retry, no scheduling, no background execution, no new
        architectural layer.
        """
        result, decisions = self.execute_request_with_dispatch_decision(
            goal, project=project, metadata=metadata
        )
        for decision in decisions:
            if decision.would_dispatch:
                skill_dispatch(
                    decision.tool_name,
                    {"problem": decision.tool_name},
                    ctx={"project": project},
                )
        return result, decisions

    def execute_request_with_memory_writeback(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[SkillDispatchDecision, ...]]:
        """Extend ``execute_request_with_skill_execution`` (v5.1) with
        memory writeback (v5.2, Phase 1): existing chain (Planning ->
        Execution -> ProblemSolver -> SkillRegistry -> Dispatch
        Decision -> Controlled Skill Execution -> ExecutionResult) ->
        existing ``core.problem_solver.record_outcome`` per successfully
        dispatched decision -> STOP.

        Pure glue over the existing chain: delegates the full lifecycle
        to ``self.execute_request_with_skill_execution`` (which already
        performs planning, session, coordinator, ProblemSolver context,
        skill check, dispatch decision, and controlled skill execution
        via ``core.skill_registry.dispatch``), then for each
        ``SkillDispatchDecision`` whose ``would_dispatch is True``
        invokes the existing ``core.problem_solver.record_outcome`` —
        the existing MemoryEngine write primitive used elsewhere in
        MARK L — exactly once. Skipped (``action == "skip"``) or
        unregistered decisions never trigger a write. No new memory
        module, manager, service, coordinator, or storage layer. No
        AI call, no reflection, no learning, no async, no threads, no
        file I/O, no ranking, no retrieval change.
        """
        result, decisions = self.execute_request_with_skill_execution(
            goal, project=project, metadata=metadata
        )
        for decision in decisions:
            if decision.would_dispatch:
                record_problem_outcome(
                    problem=decision.tool_name,
                    cause="controlled_skill_execution",
                    solution=decision.tool_name,
                    outcome="success",
                    project=project,
                )
        return result, decisions

    def execute_request_with_reflection(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[SkillDispatchDecision, ...]]:
        """Extend ``execute_request_with_memory_writeback`` (v5.2) with
        reflection (v5.3, Phase 1): existing chain (Planning ->
        Execution -> ProblemSolver -> SkillRegistry -> Dispatch
        Decision -> Controlled Skill Execution -> ExecutionResult ->
        Memory Writeback) -> existing ``self.reflection.add_reflection``
        per successfully dispatched decision -> STOP.

        Pure glue over the existing chain: delegates the full lifecycle
        to ``self.execute_request_with_memory_writeback`` (which already
        performs planning, session, coordinator, ProblemSolver context,
        skill check, dispatch decision, controlled skill execution via
        ``core.skill_registry.dispatch``, and memory writeback via
        ``core.problem_solver.record_outcome``), then for each
        ``SkillDispatchDecision`` whose ``would_dispatch is True``
        invokes the existing ``self.reflection.add_reflection`` — the
        existing ReflectionManager API — exactly once. Skipped
        (``action == "skip"``) or failed executions never trigger a
        reflection. No new reflection module, manager, service,
        coordinator, or runtime layer. No AI call, no learning, no
        async, no threads, no file I/O. Planning and execution state
        are not modified.
        """
        result, decisions = self.execute_request_with_memory_writeback(
            goal, project=project, metadata=metadata
        )
        for decision in decisions:
            if decision.would_dispatch:
                self.reflection.add_reflection(
                    subject=decision.task_id,
                    what_worked=f"controlled_execution:{decision.tool_name}",
                    completion_summary=(
                        f"Skill '{decision.tool_name}' executed "
                        f"successfully under controlled dispatch."
                    ),
                    confidence_level=1.0,
                )
        return result, decisions

    def execute_request_with_learning(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[SkillDispatchDecision, ...]]:
        """Extend ``execute_request_with_reflection`` (v5.3) with learning
        (v5.4, Phase 1): existing chain (Planning -> Execution ->
        ProblemSolver -> SkillRegistry -> Dispatch Decision -> Controlled
        Skill Execution -> ExecutionResult -> Memory Writeback ->
        Reflection) -> existing ``self.learning.record_successful_pattern``
        per successfully dispatched decision -> STOP.

        Pure glue over the existing chain: delegates the full lifecycle
        to ``self.execute_request_with_reflection`` (which already
        performs planning, session, coordinator, ProblemSolver context,
        skill check, dispatch decision, controlled skill execution via
        ``core.skill_registry.dispatch``, memory writeback via
        ``core.problem_solver.record_outcome``, and reflection via
        ``self.reflection.add_reflection``), then for each
        ``SkillDispatchDecision`` whose ``would_dispatch is True``
        invokes the existing ``self.learning.record_successful_pattern``
        — the existing LearningManager API — exactly once. Skipped
        (``action == "skip"``) or failed executions never trigger a
        learning record. No new learning module, manager, service,
        coordinator, runtime layer, or abstraction. Planning,
        execution, memory, and reflection state are not modified.
        """
        result, decisions = self.execute_request_with_reflection(
            goal, project=project, metadata=metadata
        )
        for decision in decisions:
            if decision.would_dispatch:
                self.learning.record_successful_pattern(
                    subject=decision.tool_name,
                    detail=(
                        f"Skill '{decision.tool_name}' executed "
                        f"successfully under controlled dispatch."
                    ),
                    metadata={"task_id": decision.task_id, "project": project},
                )
        return result, decisions

    def execute_request_with_tool_routing(
        self,
        tool_name: str,
        *,
        arguments: Mapping[str, object] | None = None,
    ) -> ToolResult:
        """Opt-in v8.16 tool route: ``tool_name`` -> ``ToolRequest`` ->
        ``self.tool_router.route`` -> ``ToolResult``. STOP.

        The first runtime consumer of the v8.11–v8.15 tool stack, and a
        path **parallel** to — never a replacement for or fallback of —
        the legacy ``execute_request_with_skill_execution`` chain. Pure
        glue: builds one ``ToolRequest`` (``arguments`` copied by the
        request's own constructor; ``None`` means the request's default
        empty arguments), hands that exact object to the composed
        ``ToolRouter``, and returns the exact ``ToolResult`` it produces.
        ``ToolNotFoundError`` and tool exceptions propagate unchanged.

        Never calls ``core.skill_registry.dispatch`` or
        ``core.skill_dispatch.build_dispatch_decision``, never adapts a
        ``SkillManifest``, never touches ``ToolRegistry``. Limitation:
        ``ToolRequest`` carries no ``ctx``, so the legacy
        ``{"project": ...}`` context is not representable here.
        """
        request = (
            ToolRequest(tool_name=tool_name)
            if arguments is None
            else ToolRequest(tool_name=tool_name, arguments=arguments)
        )
        return self._tool_router.route(request)

    def execute_request_with_tool_dispatch(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in tool-dispatch chain (v8.17–v8.19): goal -> existing
        Planning -> Session -> Coordinator -> one v8.x
        ``ToolDispatchDecision`` per ready task (gated by
        ``self.tool_registry.has``) -> ``ToolRequest`` -> ``ToolRouter``
        -> ``ToolResult`` -> STOP.

        Public result contract (stable, deterministic):
        ``(ExecutionResult, tuple[ToolDispatchDecision, ...],
        tuple[ToolResult, ...])`` — the existing v3.5 ``ExecutionResult``
        built from the same session (no new result abstraction), one
        decision per ready descriptor in coordinator order, and the
        exact ``ToolResult`` objects in dispatch order. Skipped
        decisions contribute no result; a ``ToolResult`` is never
        embedded in a decision; exceptions are never converted into
        results. No Memory/Reflection/Learning writeback occurs here.

        A path **parallel** to — never a replacement for or fallback of
        — the legacy ``execute_request_with_skill_execution`` chain.
        Pure glue: reuses ``self.planning.plan``,
        ``self.create_execution_session`` and ``self.coordinate_execution``
        exactly as the legacy chain does, then builds each decision via
        the pure ``core.tool_dispatch.build_tool_dispatch_decision`` with
        ``self._tool_registry`` as the explicit registry and
        ``{"project": project}`` as informational context. The returned
        ``ExecutionResult`` is the existing v3.5 wrapper built from the
        same session. Never calls ``core.skill_registry`` /
        ``core.skill_dispatch``, never adapts a ``SkillManifest``, never
        performs the legacy ``gather_context`` read (its result was
        always discarded), never writes Memory/Reflection/Learning.

        v8.18 routing: for each decision with ``would_dispatch`` — in
        coordinator/decision order — build
        ``ToolRequest(tool_name, {"problem": tool_name})`` (the legacy
        argument shape) and hand it to ``self._tool_router.route``;
        the exact ``ToolResult`` objects are collected in dispatch
        order. Skipped decisions produce no result and never touch the
        router. Tool / router exceptions propagate unchanged and stop
        the loop at the first failure, matching legacy semantics. The
        legacy ``{"project": ...}`` ctx is not representable in
        ``ToolRequest`` and lives only in ``decision.context``.

        v8.29: the body lives in ``_run_tool_dispatch_chain`` (shared with
        the v8.20 writeback path, extracted unchanged).
        """
        return self._run_tool_dispatch_chain(goal, project=project, metadata=metadata)

    def _run_tool_dispatch_chain(
        self,
        goal: str,
        *,
        project: str | None,
        metadata: Mapping[str, Any] | None,
        routing: list[ToolDispatchDecision] | None = None,
    ) -> tuple[ExecutionResult, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """v8.19 chain body (extracted unchanged in v8.29 so the v8.20 path
        can observe its failure boundary): planning -> session ->
        coordinator -> decisions -> ``ToolRouter`` per dispatched decision.

        ``routing`` (v8.29, caller-owned, set only by the v8.20 path) holds
        the decision currently being routed: appended just before
        ``route`` and removed once ``route`` returns, so after an exception
        it is non-empty exactly when ``ToolRouter.route`` raised, naming the
        failed stage. It changes nothing else."""
        plan = self.planning.plan(goal)
        session = self.create_execution_session(plan, project=project, metadata=metadata)
        coordination = self.coordinate_execution(session)
        decisions = tuple(
            build_tool_dispatch_decision(
                descriptor.task_id,
                descriptor.work_item.problem,
                registry=self._tool_registry,
                context={"project": project},
            )
            for descriptor in coordination.ready_descriptors
        )
        results: list[ToolResult] = []
        for decision in decisions:
            if decision.would_dispatch:
                request = ToolRequest(
                    tool_name=decision.tool_name,
                    arguments={"problem": decision.tool_name},
                )
                if routing is not None:
                    routing.append(decision)
                results.append(self._tool_router.route(request))
                if routing is not None:
                    routing.pop()
        result = build_result_from_session(session)
        return result, decisions, tuple(results)

    def execute_request_with_tool_dispatch_writeback(
        self,
        goal: str,
        *,
        project: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[ExecutionResult, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in v8.20 tool-chain writeback: the v8.17–v8.19 tool
        dispatch chain -> existing Memory writeback -> existing
        Reflection -> existing Learning -> STOP.

        Mirrors the legacy v5.2 / v5.3 / v5.4 layering exactly, but over
        ``execute_request_with_tool_dispatch``: pure glue that delegates
        the full chain (planning, session, coordinator, decisions,
        routing) and then, for each decision with ``would_dispatch`` —
        paired positionally with its ``ToolResult`` in dispatch order —
        performs the same three existing writes, one layer at a time:

        1. ``core.problem_solver.record_outcome`` (via the Agent-owned
           ``MemoryEngine``) with ``cause="controlled_tool_dispatch"``;
        2. ``self.reflection.add_reflection`` (v3.x manager, unchanged);
        3. ``self.learning.record_successful_pattern`` (v3.x manager,
           unchanged), with the ``ToolResult.output`` in its metadata.

        Skipped decisions produce no write. If a tool raises, the
        exception propagates from the dispatch chain before any write
        occurs (legacy semantics). Returns the v8.19 contract unchanged:
        ``(ExecutionResult, decisions, results)``. Never calls the legacy
        skill chain, never touches ``ToolRegistry`` / ``ToolRouter``
        directly.

        v8.29: runs the v8.19 body (``_run_tool_dispatch_chain``) directly
        with a caller-owned in-flight ``routing`` log. An exception raised by
        ``ToolRouter.route`` (the execution boundary) gets exactly one
        structured failure writeback through the shared writer
        (``_record_failure_outcome``; no ``PipelineRun`` exists here, so
        ``run_id`` / ``goal_id`` / ``plan_id`` are ``None``) and is re-raised
        unchanged. Failures before any routing (planning, session,
        coordination, decisions) write nothing. No success record is written
        for a failed attempt.
        """
        routing: list[ToolDispatchDecision] = []
        try:
            result, decisions, results = self._run_tool_dispatch_chain(
                goal, project=project, metadata=metadata, routing=routing
            )
        except BaseException as exc:
            self._record_failure_outcome(None, exc, project=project, dispatched=routing)
            raise
        dispatched = tuple(
            (decision, tool_result)
            for decision, tool_result in zip(
                (d for d in decisions if d.would_dispatch), results
            )
        )
        for decision, _tool_result in dispatched:
            record_problem_outcome(
                problem=decision.tool_name,
                cause="controlled_tool_dispatch",
                solution=decision.tool_name,
                outcome="success",
                project=project,
            )
        for decision, tool_result in dispatched:
            self.reflection.add_reflection(
                subject=decision.task_id,
                what_worked=f"controlled_tool_dispatch:{decision.tool_name}",
                completion_summary=(
                    f"Tool '{decision.tool_name}' executed successfully "
                    f"under controlled tool dispatch: {tool_result.output}"
                ),
                confidence_level=1.0,
            )
        for decision, tool_result in dispatched:
            self.learning.record_successful_pattern(
                subject=decision.tool_name,
                detail=(
                    f"Tool '{decision.tool_name}' executed successfully "
                    f"under controlled tool dispatch."
                ),
                metadata={
                    "task_id": decision.task_id,
                    "project": project,
                    "output": tool_result.output,
                },
            )
        return result, decisions, results

    def project_request(self, goal: str) -> tuple[ExecutionPlan, PlanProjection]:
        """Opt-in v8.21 projection: goal -> existing legacy
        ``self.planning.plan(goal)`` -> ``core.plan_projection.
        project_execution_plan`` into the six Agent-owned Foundation
        stores wired in v8.10 -> STOP.

        Pure glue: the legacy planner is used unchanged (``InvalidGoalError``
        on a blank goal propagates), the resulting ``ExecutionPlan`` is
        projected with the exact ``goal_manager`` / ``planning_engine`` /
        ``task_graph`` / ``execution_planner`` / ``pipeline_engine``
        instances this Agent owns (injected instances are used verbatim;
        inconsistent injected wiring fails loudly in the adapter's
        pre-flight), and both the legacy plan and the ``PlanProjection``
        are returned. No execution, no ``PipelineRun``, no tool routing,
        no Memory/Reflection/Learning write; no existing request path
        is touched.
        """
        plan = self.planning.plan(goal)
        projection = project_execution_plan(
            plan,
            goal_manager=self._goal_manager,
            planning_engine=self._planning_engine,
            task_graph=self._task_graph,
            execution_planner=self._execution_planner,
            pipeline_engine=self._pipeline_engine,
        )
        return plan, projection

    def execute_projection_with_tool_dispatch(
        self,
        goal: str,
        *,
        project: str | None = None,
    ) -> tuple[PlanProjection, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in v8.22 pipeline-stage tool dispatch: goal ->
        ``self.project_request`` (legacy plan projected into the Foundation
        stores, v8.21) -> the projected ``PipelineRecord``'s stages ->
        one v8.x ``ToolDispatchDecision`` per stage (``core.stage_dispatch``,
        gated by ``self.tool_registry.has``) -> ``ToolRequest`` ->
        ``ToolRouter`` -> ``ToolResult`` -> STOP.

        The first request path that runs end-to-end on the v8.x Foundation
        + tool architecture; the legacy coordinator is not involved. The
        result mirrors the v8.19 contract with the ``PlanProjection``
        standing in for the legacy ``ExecutionResult``:
        ``(PlanProjection, decisions, results)`` — decisions in stage
        (execution) order, exact ``ToolResult`` objects in dispatch order,
        skipped stages contribute no result, exceptions propagate unchanged
        and stop the loop at the first failure. Every stage is dispatched
        in order (``PipelineStage.depends_on`` is descriptive only); no
        readiness evaluation, no ``PipelineRun``, no status transition, no
        writeback, no legacy skill call.
        """
        _plan, projection = self.project_request(goal)
        pipeline = self._pipeline_engine.get_pipeline(projection.pipeline_id)
        if pipeline is None:
            raise KeyError(projection.pipeline_id)
        decisions = build_stage_dispatch_decisions(
            pipeline,
            task_graph=self._task_graph,
            registry=self._tool_registry,
            context={"project": project},
        )
        results: list[ToolResult] = []
        for decision in decisions:
            if decision.would_dispatch:
                request = ToolRequest(
                    tool_name=decision.tool_name,
                    arguments={"problem": decision.tool_name},
                )
                results.append(self._tool_router.route(request))
        return projection, decisions, tuple(results)

    def execute_projection_with_run_status(
        self,
        goal: str,
        *,
        project: str | None = None,
    ) -> tuple[PlanProjection, PipelineRun, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in v8.23 run-status recording over the v8.22 stage dispatch:
        goal -> ``project_request`` -> ``PipelineRunManager.create_run``
        (CREATED) -> stage decisions -> RUNNING -> ``ToolRouter`` per
        dispatched stage -> COMPLETED, or FAILED when a tool raises ->
        STOP.

        The first producer of the v8.9 ``PipelineRunManager``. Same
        decisions/results semantics as ``execute_projection_with_tool_dispatch``
        (stage order, registry gating, exact ``ToolResult`` identity, stop at
        first failure). The run references the projected ``pipeline_id`` and
        carries ``{"project", "goal_id", "mapping_id"}`` metadata. On a tool
        exception the run is marked FAILED and the **same exception is
        re-raised unchanged** — nothing is swallowed or wrapped. An empty or
        fully skipped pipeline completes. No per-stage status (the v8.9
        model is run-level), no retries, no cancellation, no writeback, no
        legacy call. Returns ``(projection, final_run, decisions, results)``.
        """
        _plan, projection = self.project_request(goal)
        run, decisions, results = self._run_projected_pipeline(projection, project=project)
        return projection, run, decisions, results

    def _run_projected_pipeline(
        self,
        projection: PlanProjection,
        *,
        project: str | None,
        reflect_steps: bool = False,
        dispatched: list[ToolDispatchDecision] | None = None,
        skip_task_ids: frozenset[str] | None = None,
        resumes_run_id: str | None = None,
        retry_transient: bool = False,
    ) -> tuple[PipelineRun, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """v8.23 run body (extracted unchanged in v8.25 so the lifecycle-aware
        path can reuse it): ``create_run`` (CREATED) -> stage decisions ->
        RUNNING -> route each dispatched stage -> COMPLETED, or FAILED with
        the same exception re-raised unchanged.

        ``reflect_steps`` (v8.26, set only by the lifecycle path) reflects
        each *reached* stage onto its Foundation step, targeted by
        ``projection.plan_id`` + ``decision.task_id``: dispatched -> ACTIVE
        before routing, COMPLETED after success; skipped -> ARCHIVED. On a
        failure nothing more is written (the failing step stays ACTIVE,
        unreached steps stay DRAFT). Off by default, so v8.23 / v8.24 leave
        steps untouched.

        ``dispatched`` (v8.28, caller-owned, set only by the v8.24 path)
        receives each dispatched decision just before it is routed, so the
        caller can name the failed stage; it changes nothing else.

        ``skip_task_ids`` / ``resumes_run_id`` (v8.32, set only by
        ``resume_failed_run``): stages whose task id is in ``skip_task_ids``
        (steps already COMPLETED or ARCHIVED) are left out of this run —
        not dispatched, not reflected, not returned — and the new run's
        metadata records ``"resumes_run_id"``. Defaults change nothing.

        ``retry_transient`` (v8.33, set only by the lifecycle path and
        ``resume_failed_run``) routes each dispatched stage through
        ``_route_with_transient_retry`` (bounded in-run retry, owner policy
        O5); off by default, so every other path routes exactly once."""
        pipeline = self._pipeline_engine.get_pipeline(projection.pipeline_id)
        if pipeline is None:
            raise KeyError(projection.pipeline_id)
        metadata: dict[str, Any] = {
            "project": project,
            "goal_id": projection.goal_id,
            "mapping_id": projection.mapping_id,
        }
        if resumes_run_id is not None:
            metadata["resumes_run_id"] = resumes_run_id
        run = self._pipeline_run_manager.create_run(projection.pipeline_id, metadata=metadata)
        decisions = build_stage_dispatch_decisions(
            pipeline,
            task_graph=self._task_graph,
            registry=self._tool_registry,
            context={"project": project},
        )
        if skip_task_ids:
            decisions = tuple(d for d in decisions if d.task_id not in skip_task_ids)
        self._pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.RUNNING)
        results: list[ToolResult] = []
        plan_id = projection.plan_id
        engine = self._planning_engine
        try:
            for decision in decisions:
                if decision.would_dispatch:
                    if dispatched is not None:
                        dispatched.append(decision)
                    if reflect_steps:
                        reflect_step_reached(plan_id, decision.task_id, planning_engine=engine)
                    request = ToolRequest(
                        tool_name=decision.tool_name,
                        arguments={"problem": decision.tool_name},
                    )
                    if retry_transient:
                        results.append(self._route_with_transient_retry(request))
                    else:
                        results.append(self._tool_router.route(request))
                    if reflect_steps:
                        reflect_step_completed(plan_id, decision.task_id, planning_engine=engine)
                elif reflect_steps:
                    reflect_step_skipped(plan_id, decision.task_id, planning_engine=engine)
        except BaseException:
            # Record the failure, then propagate the original exception.
            self._pipeline_run_manager.update_run(run.id, status=PipelineRunStatus.FAILED)
            raise
        final_run = self._pipeline_run_manager.update_run(
            run.id, status=PipelineRunStatus.COMPLETED
        )
        return final_run, decisions, tuple(results)

    def execute_projection_with_writeback(
        self,
        goal: str,
        *,
        project: str | None = None,
    ) -> tuple[PlanProjection, PipelineRun, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in v8.24 writeback over the Foundation-native path:
        ``execute_projection_with_run_status`` -> existing Memory writeback
        -> existing Reflection -> existing Learning -> STOP.

        Mirrors v8.20 (itself a mirror of v5.2 / v5.3 / v5.4) one layer at
        a time over each dispatched decision paired positionally with its
        ``ToolResult``; the learning metadata additionally records the
        ``run_id`` now that a ``PipelineRun`` exists. Skipped stages
        produce no write. Returns the v8.23 4-tuple unchanged. No Goal/Plan
        status transitions, no per-stage status, no legacy call.

        v8.28: runs the same v8.23 body (``project_request`` +
        ``_run_projected_pipeline``) directly so the failed stage is known;
        a failed execution attempt (FAILED run) gets exactly one structured
        failure writeback (``_record_failure_outcome``, the failed stage
        being the last dispatched one) and the original exception is
        re-raised unchanged. No success record is written for a failed
        attempt.
        """
        _plan, projection = self.project_request(goal)
        dispatched: list[ToolDispatchDecision] = []
        try:
            run, decisions, results = self._run_projected_pipeline(
                projection, project=project, dispatched=dispatched
            )
        except BaseException as exc:
            self._record_failure_outcome(projection, exc, project=project, dispatched=dispatched)
            raise
        self._record_tool_outcomes(decisions, results, run=run, project=project)
        return projection, run, decisions, results

    def _route_with_transient_retry(self, request: ToolRequest) -> ToolResult:
        """v8.33 bounded in-run retry (owner policy O5, locked).

        Routes ``request`` through the unchanged ``ToolRouter`` at most three
        times: the initial attempt plus at most two retries, with no delay.
        A failure is retried only if the v8.30 type-based classifier says
        TRANSIENT (``_classify_execution_failure``; UNKNOWN is never
        retried) and an attempt remains; any other failure, or the third
        failure, is re-raised unchanged — the exact exception object of that
        final attempt. The successful attempt's ``ToolResult`` is returned
        as-is. Intermediate failures stay inside this method, so they never
        reach run-status recording or failure writeback; the step stays
        ACTIVE throughout (it is reflected by the caller). ``BaseException``
        that is not an ``Exception`` (e.g. ``KeyboardInterrupt``) is never
        retried. No state, no sleep, no new run.
        """
        max_attempts = 3  # O5: initial attempt + at most 2 retries (hard bound)
        for attempt in range(1, max_attempts + 1):
            try:
                return self._tool_router.route(request)
            except Exception as exc:
                if attempt == max_attempts or (
                    _classify_execution_failure(exc) is not FailureCategory.TRANSIENT
                ):
                    raise
        raise AssertionError("unreachable: every attempt returns or raises")

    def _record_tool_outcomes(
        self,
        decisions: tuple[ToolDispatchDecision, ...],
        results: tuple[ToolResult, ...],
        *,
        run: PipelineRun,
        project: str | None,
    ) -> None:
        """v8.24 writeback body (extracted unchanged in v8.25): the existing
        Memory -> Reflection -> Learning writes, one layer at a time, per
        dispatched decision paired with its ``ToolResult``."""
        dispatched = tuple(
            zip((d for d in decisions if d.would_dispatch), results)
        )
        for decision, _tool_result in dispatched:
            record_problem_outcome(
                problem=decision.tool_name,
                cause="controlled_tool_dispatch",
                solution=decision.tool_name,
                outcome="success",
                project=project,
            )
        for decision, tool_result in dispatched:
            self.reflection.add_reflection(
                subject=decision.task_id,
                what_worked=f"controlled_tool_dispatch:{decision.tool_name}",
                completion_summary=(
                    f"Tool '{decision.tool_name}' executed successfully "
                    f"under controlled tool dispatch: {tool_result.output}"
                ),
                confidence_level=1.0,
            )
        for decision, tool_result in dispatched:
            self.learning.record_successful_pattern(
                subject=decision.tool_name,
                detail=(
                    f"Tool '{decision.tool_name}' executed successfully "
                    f"under controlled tool dispatch."
                ),
                metadata={
                    "task_id": decision.task_id,
                    "project": project,
                    "output": tool_result.output,
                    "run_id": run.id,
                },
            )

    def _record_failure_outcome(
        self,
        projection: PlanProjection | None,
        exc: BaseException,
        *,
        project: str | None,
        dispatched: list[ToolDispatchDecision] | None = None,
    ) -> None:
        """Shared failure writeback (v8.27; v8.28 shared with the v8.24
        path; v8.29 with the v8.20 tool chain): exactly one structured
        record per failed execution attempt,
        through the existing Memory -> Reflection -> Learning APIs
        (``record_outcome`` with a non-success outcome,
        ``add_reflection(what_failed=...)``, ``record_failed_pattern``).

        Derived only from authoritative state: the attempt counts as an
        *execution* failure only if this projection's pipeline has a FAILED
        ``PipelineRun`` (a failure before the run reached RUNNING is not an
        execution failure and writes nothing). The failed stage is, with
        ``dispatched=None`` (lifecycle path), the one ACTIVE step (v8.26),
        when there is one; with a ``dispatched`` log (v8.24 path, no step
        reflection), its last decision, when there is one. With
        ``projection=None`` (v8.20 tool chain: no ``PipelineRun``, no
        Foundation goal or plan) the attempt is an execution failure only if
        ``dispatched`` (the in-flight routing log) names the decision whose
        ``ToolRouter.route`` raised; ``run_id`` / ``goal_id`` / ``plan_id``
        are then ``None`` — nothing is invented. The exception is reduced to
        a v8.28 ``ExecutionFailure`` (type name only) — its message, repr,
        args and traceback are never written. Any exception raised while
        writing is suppressed so it can never mask the original execution
        exception (writes are not atomic: earlier layers may remain
        written). Changes no status.
        """
        try:
            if projection is None:
                if not dispatched:
                    return
                run_id = goal_id = plan_id = goal_title = None
                task_id, stage = dispatched[-1].task_id, dispatched[-1].tool_name
            else:
                failed_runs = [
                    r for r in self._pipeline_run_manager.list_runs(status=PipelineRunStatus.FAILED)
                    if r.pipeline_reference == projection.pipeline_id
                ]
                if not failed_runs:
                    return
                run_id = failed_runs[-1].id
                goal_id, plan_id = projection.goal_id, projection.plan_id
                if dispatched is None:
                    plan = self._planning_engine.get_plan(projection.plan_id)
                    active = [s for s in (plan.steps if plan else ()) if s.status is PlanStatus.ACTIVE]
                    step = active[0] if len(active) == 1 else None
                    task_id = step.id if step is not None else None
                    stage = step.title if step is not None else None
                else:
                    last = dispatched[-1] if dispatched else None
                    task_id = last.task_id if last is not None else None
                    stage = last.tool_name if last is not None else None
                goal_title = self._goal_manager.get_goal(projection.goal_id).title
            failure = normalize_execution_failure(
                exc, run_id=run_id, tool_name=stage, project=project
            )
            metadata = {
                "run_id": failure.run_id,
                "goal_id": goal_id,
                "plan_id": plan_id,
                "task_id": task_id,
                "project": failure.project,
                "exception_type": failure.exception_type,
            }
            record_problem_outcome(
                problem=failure.tool_name or goal_title,
                cause="controlled_tool_dispatch_failure",
                solution=failure.tool_name or "",
                outcome=f"failed:{failure.exception_type}",
                project=failure.project,
            )
            self.reflection.add_reflection(
                subject=task_id if task_id is not None else goal_id,
                what_failed=f"controlled_tool_dispatch:{failure.tool_name or 'unknown stage'}",
                completion_summary=(
                    f"Execution attempt failed ({failure.exception_type}) under "
                    f"controlled tool dispatch."
                ),
                confidence_level=0.0,
                metadata=dict(metadata),
            )
            self.learning.record_failed_pattern(
                subject=failure.tool_name or goal_title,
                detail=(
                    f"Execution attempt failed ({failure.exception_type}) under "
                    f"controlled tool dispatch."
                ),
                metadata=dict(metadata),
            )
        except Exception:
            # The original execution exception is authoritative (v8.27).
            return

    def execute_projection_with_lifecycle(
        self,
        goal: str,
        *,
        project: str | None = None,
    ) -> tuple[PlanProjection, PipelineRun, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """Opt-in v8.25 lifecycle-aware Foundation-native execution:
        projection -> Goal ACTIVE / Plan ACTIVE -> the v8.23 run
        (CREATED -> RUNNING -> tool execution -> COMPLETED | FAILED) ->
        on COMPLETED: Plan COMPLETED, Goal COMPLETED -> the v8.24
        writeback -> STOP.

        Locked semantics: a FAILED run leaves Goal and Plan ACTIVE (a
        failed attempt is not a failed goal), performs no success writeback, and
        re-raises the original exception unchanged. No new status values,
        no transition state machine — the existing replacement-style
        ``update_goal`` / ``update_plan`` are used via
        ``core.lifecycle_reflection``. Added as a separate method because
        the v8.23/v8.24 methods' "no Goal/Plan transition" behaviour is
        pinned by their tests; they share this method's body through the
        private helpers. Returns the v8.23/v8.24 4-tuple.

        v8.26: the only path that reflects stage outcomes onto
        ``Step.status`` (``reflect_steps=True``; see
        ``_run_projected_pipeline`` and ``core.step_lifecycle``).

        v8.27: a failed execution attempt gets exactly one structured
        failure writeback (``_record_failure_outcome``) before the original
        exception is re-raised; statuses are unchanged by it.
        """
        _plan, projection = self.project_request(goal)
        reflect_execution_started(
            projection.goal_id,
            projection.plan_id,
            goal_manager=self._goal_manager,
            planning_engine=self._planning_engine,
        )
        try:
            run, decisions, results = self._run_projected_pipeline(
                projection, project=project, reflect_steps=True, retry_transient=True
            )
        except BaseException as exc:
            self._record_failure_outcome(projection, exc, project=project)
            raise
        reflect_execution_completed(
            projection.goal_id,
            projection.plan_id,
            goal_manager=self._goal_manager,
            planning_engine=self._planning_engine,
        )
        self._record_tool_outcomes(decisions, results, run=run, project=project)
        return projection, run, decisions, results

    def resume_failed_run(
        self,
        run_id: str,
    ) -> tuple[PlanProjection, PipelineRun, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...]]:
        """v8.32: resume a FAILED lifecycle attempt as a **new** ``PipelineRun``
        on the **same** projected pipeline (owner decisions O4 / O6 / O7).

        Everything that can forbid the resume is checked **before** the new
        run is created (``_prepare_resume``); a refused resume changes
        nothing. The failed run is never modified. Stages are considered in
        pipeline order with freshly rebuilt decisions:

        * COMPLETED step — skipped: not invoked, not reflected, no new
          success writeback (O7);
        * ARCHIVED step — skipped, never re-checked against the registry
          (O6);
        * ACTIVE (failed) step — re-dispatched only if its ``ToolSpec`` in
          ``self.tool_catalog`` is ``idempotent=True`` (O4; no spec or
          ``idempotent=False`` refuses the resume, no override);
        * DRAFT step — executed normally (v8.26 step semantics).

        The new run carries ``{"project", "goal_id", "mapping_id",
        "resumes_run_id"}`` metadata (``project`` from the failed run) and
        follows the v8.25-v8.27 lifecycle exactly: COMPLETED -> Plan / Goal
        COMPLETED + success writeback for the stages newly executed in this
        run only; FAILED -> Goal / Plan stay ACTIVE, exactly one failure
        writeback for this run (new ``run_id``), original exception
        re-raised unchanged. No retry, no new status. Returns the
        lifecycle 4-tuple ``(projection, new_run, decisions, results)``
        where ``decisions`` covers only the stages of this run.

        Raises (before any change):
            KeyError: unknown ``run_id``.
            ValueError: the run is not FAILED, is not a lifecycle attempt
                (its Goal / Plan are not ACTIVE), its pipeline / mapping /
                plan cannot be resolved, or a failed ACTIVE step is not
                resumable (tool not registered, no ``ToolSpec``, or not
                idempotent).
        """
        projection, project, skip_task_ids = self._prepare_resume(run_id)
        try:
            run, decisions, results = self._run_projected_pipeline(
                projection,
                project=project,
                reflect_steps=True,
                retry_transient=True,
                skip_task_ids=skip_task_ids,
                resumes_run_id=run_id,
            )
        except BaseException as exc:
            self._record_failure_outcome(projection, exc, project=project)
            raise
        reflect_execution_completed(
            projection.goal_id,
            projection.plan_id,
            goal_manager=self._goal_manager,
            planning_engine=self._planning_engine,
        )
        self._record_tool_outcomes(decisions, results, run=run, project=project)
        return projection, run, decisions, results

    def _prepare_resume(self, run_id: str) -> tuple[PlanProjection, str | None, frozenset[str]]:
        """Read-only validation for ``resume_failed_run``: resolve the failed
        run's projection and decide which stages to skip. Writes nothing."""
        run = self._pipeline_run_manager.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.status is not PipelineRunStatus.FAILED:
            raise ValueError(f"run {run_id!r} is {run.status.value}; only a FAILED run can be resumed")
        pipeline = self._pipeline_engine.get_pipeline(run.pipeline_reference)
        mapping = (
            self._execution_planner.get_execution_plan(pipeline.execution_mapping_reference)
            if pipeline is not None else None
        )
        plan = (
            self._planning_engine.get_plan(mapping.plan_reference)
            if mapping is not None and mapping.plan_reference else None
        )
        goal = (
            self._goal_manager.get_goal(mapping.goal_reference)
            if mapping is not None and mapping.goal_reference else None
        )
        if pipeline is None or mapping is None or plan is None or goal is None:
            raise ValueError(f"run {run_id!r}: its pipeline, mapping, plan or goal cannot be resolved")
        if goal.status is not GoalStatus.ACTIVE or plan.status is not PlanStatus.ACTIVE:
            raise ValueError(f"run {run_id!r} is not a failed lifecycle attempt (goal / plan not ACTIVE)")
        project = run.metadata.get("project")
        decisions = {
            d.task_id: d
            for d in build_stage_dispatch_decisions(
                pipeline,
                task_graph=self._task_graph,
                registry=self._tool_registry,
                context={"project": project},
            )
        }
        skip: set[str] = set()
        for step in plan.steps:
            if step.status in (PlanStatus.COMPLETED, PlanStatus.ARCHIVED):
                skip.add(step.id)
            elif step.status is PlanStatus.ACTIVE:
                decision = decisions.get(step.id)
                if decision is None or not decision.would_dispatch:
                    raise ValueError(f"run {run_id!r}: failed step {step.id!r} has no registered tool")
                spec = self._tool_catalog.get(decision.tool_name)
                if spec is None:
                    raise ValueError(
                        f"run {run_id!r}: failed step {step.id!r} has no ToolSpec; not resumable"
                    )
                if not spec.idempotent:
                    raise ValueError(
                        f"run {run_id!r}: failed step {step.id!r} is not idempotent; not resumable"
                    )
        task_to_node: dict[str, str] = {}
        for stage in pipeline.stages:
            node = self._task_graph.get_node(stage.node_id)
            if node is not None and isinstance(node.metadata.get("task_id"), str):
                task_to_node[node.metadata["task_id"]] = node.id
        projection = PlanProjection(
            goal_id=goal.id,
            plan_id=plan.id,
            graph_reference=mapping.graph_reference or plan.id,
            mapping_id=mapping.id,
            pipeline_id=pipeline.id,
            step_ids=tuple(step.id for step in plan.steps),
            node_ids=tuple(task_to_node[step.id] for step in plan.steps if step.id in task_to_node),
            task_to_node=task_to_node,
        )
        return projection, project, frozenset(skip)

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

    @property
    def ai_service(self) -> AIService:
        """The composed ``AIService`` used for every reasoning request."""
        return self._ai_service

    def reason(
        self,
        provider_name: str,
        prompt: str,
        history: ConversationHistory | None = None,
        *,
        memory: MemoryRequest | None = None,
    ) -> AIResponse:
        """Delegate one synchronous reasoning request to ``AIService``.

        Pure delegation: builds an ``AIRequest`` from ``prompt`` and
        forwards to ``self._ai_service.complete(provider_name, ...)``.
        ``history`` is optional — when supplied it is passed through
        so the provider receives the full multi-turn context. The
        Agent performs no provider routing, no SDK instantiation, and
        no provider-specific logic — that all lives inside
        ``AIService`` and the v7.x real-transport provider stack.
        """
        # v8.36: ``memory`` is forwarded only when requested, so the default
        # call shape to ``AIService.complete`` is exactly the pre-v8.36 one.
        extra = {"memory": memory} if memory is not None else {}
        return self._ai_service.complete(
            provider_name,
            AIRequest(prompt=prompt),
            history=history,
            **extra,
        )

    @property
    def memory_engine(self) -> MemoryEngine:
        """The composed in-process ``MemoryEngine`` owned by the Agent."""
        return self._memory_engine

    @property
    def reflection_engine(self) -> ReflectionEngine:
        """The canonical Foundation-level ``ReflectionEngine`` owned by
        the Agent. The composed ``ReflectionManager`` writes through
        this engine, so all reflections flow into a single store.
        """
        return self._reflection_engine

    @property
    def conversation_history(self) -> ConversationHistory:
        """The composed multi-turn ``ConversationHistory`` owned by the Agent.

        Callers can append user / assistant turns here and then pass the
        history back into :meth:`reason` so the next completion sees the
        full ordered context.
        """
        return self._conversation_history

    def ask(
        self,
        provider_name: str,
        prompt: str,
        *,
        memory: MemoryRequest | None = None,
    ) -> AIResponse:
        """One synchronous multi-turn reasoning call.

        Forwards the Agent's existing conversation history to
        ``AIService`` (so the provider receives the full prior
        context) along with the new ``prompt`` turn. On success the
        user turn and the assistant reply are appended to the
        Agent's history so the next :meth:`ask` sees the full
        ordered transcript. No memory / reflection / learning
        integration is performed here, except the v8.36 opt-in: an explicit
        ``memory=MemoryRequest(...)`` injects non-sensitive memories into the
        request's system channel (canonical history is unchanged).
        """
        prior_history = ConversationHistory()
        prior_history.extend(self._conversation_history)
        extra = {"memory": memory} if memory is not None else {}  # v8.36 opt-in only
        response = self._ai_service.complete(
            provider_name,
            AIRequest(prompt=prompt),
            history=prior_history,
            **extra,
        )
        self._conversation_history.append_user(prompt)
        self._conversation_history.append_assistant(response.text)
        return response

    def ask_with_tools(
        self,
        provider_name: str,
        prompt: str,
        *,
        tools: Sequence[Any] | None = None,
        confirm: Callable[[Any, Any], bool] | None = None,
        memory: MemoryRequest | None = None,
    ) -> ToolLoopResult:
        """One synchronous tool-calling run (v8.39); thin wiring over
        ``core.tool_runtime.run_tool_loop``.

        Like :meth:`ask`, the Agent's conversation history is sent as prior
        context and, only on success, the user prompt and the final reply are
        appended to it; the tool exchanges stay loop-local and nothing is
        appended when the run raises. ``tools`` defaults to the
        ``model_invocable`` specs of :attr:`tool_catalog` (an empty selection
        raises ``ValueError``); ``confirm`` approves side-effecting calls (no
        hook: they are refused); ``memory`` is the v8.36 opt-in. The loop
        limits, refusal rules and audit records are owned by the runtime leaf.
        """
        offered = (
            tuple(tools) if tools is not None
            else tuple(spec for spec in self.tool_catalog.list() if spec.model_invocable)
        )
        prior_history = ConversationHistory()
        prior_history.extend(self._conversation_history)
        extra = {"memory": memory} if memory is not None else {}
        result = run_tool_loop(
            lambda request: self._ai_service.complete(
                provider_name, request, history=prior_history, **extra
            ),
            prompt=prompt,
            tools=offered,
            router=self.tool_router,
            registry=self.tool_registry,
            confirm=confirm,
        )
        self._conversation_history.append_user(prompt)
        self._conversation_history.append_assistant(result.response.text)
        return result
