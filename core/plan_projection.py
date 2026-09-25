"""MARK L v8.21 — Legacy Plan → Foundation Projection Adapter.

A **write-side adapter / deterministic projection coordinator** that
projects one legacy ``core.planner.ExecutionPlan`` into the existing
v8.4–v8.10 Foundation stores:

    ExecutionPlan (legacy, read-only)
        → PlanningEngine  (one Foundation Plan, one Step per Task)
        → TaskGraph       (one Node per Task, one edge per depends_on)
        → GoalManager     (one GoalRecord referencing plan + graph)
        → ExecutionPlanner (one ExecutionMapping, explicit node order)
        → PipelineEngine  (one PipelineRecord)

It is **not** a pure function: it mutates the five injected stores
through their existing public APIs. It never executes anything, never
creates a ``PipelineRun``, never touches the tool stack, and never
modifies the legacy planner.

Identity and traceability
-------------------------
Every Foundation record receives a **store-generated** id (the shared
stores would otherwise collide on deterministic legacy ids when the
same goal is projected twice). Legacy identity is preserved
structurally instead:

* ``Step.id == legacy Task.id`` (plan-scoped, never globally keyed);
* ``Node.metadata == {"task_id", "plan_id"}``;
* ``ExecutionMapping.metadata == {"legacy_plan_id", "legacy_goal_id"}``;
* ``GoalRecord.tags == (legacy goal id,)``;
* ``PlanProjection.task_to_node`` maps legacy ``Task.id`` → ``Node.id``.

``graph_reference`` is the projected Foundation ``plan_id``: the shared
``TaskGraph`` has no identity of its own, so the plan id tags the
projected subgraph.

Re-projection is **not idempotent**: projecting the same plan again
creates a second, independent, fully traceable set of records.

Atomicity
---------
The stores provide no transactions or rollback. Everything that can be
checked is checked in a pre-flight step **before the first write**; if
a store raises after writes have begun, the exception propagates and
the records written so far remain (non-atomic, documented).

Dependency direction:

    Agent / callers  →  plan_projection  →  core.planner (types),
                                            goal_manager, planning_engine,
                                            task_graph, execution_planner,
                                            pipeline_engine
    plan_projection  →  pipeline_run / tool stack / skills / agent   (forbidden)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager
from core.pipeline_engine import PipelineEngine
from core.planner import ExecutionPlan, Task
from core.planning_engine import PlanStatus, PlanningEngine, Step
from core.task_graph import TaskGraph

__all__ = ["PlanProjection", "project_execution_plan"]


@dataclass(frozen=True, slots=True)
class PlanProjection:
    """Immutable record of the opaque ids created by one projection.

    Holds identifiers only — no Foundation record is embedded.
    ``task_to_node`` is a read-only mapping from legacy ``Task.id`` to
    the store-generated ``Node.id``; ``node_ids`` and ``step_ids`` are
    in legacy ``plan.tasks`` order.
    """

    goal_id: str
    plan_id: str
    graph_reference: str
    mapping_id: str
    pipeline_id: str
    step_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    task_to_node: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "task_to_node", MappingProxyType(dict(self.task_to_node))
        )


def project_execution_plan(
    plan: ExecutionPlan,
    *,
    goal_manager: GoalManager,
    planning_engine: PlanningEngine,
    task_graph: TaskGraph,
    execution_planner: ExecutionPlanner,
    pipeline_engine: PipelineEngine,
) -> PlanProjection:
    """Project ``plan`` into the five injected Foundation stores.

    Order (fixed): pre-flight → Foundation Plan + Steps → Nodes → edges
    → GoalRecord → ExecutionMapping (explicit ``ordered_node_ids`` from
    ``plan.execution_order()``) → PipelineRecord → ``PlanProjection``.

    Raises (before any write):
        TypeError: ``plan`` is not an ``ExecutionPlan`` or a store is not
            of the expected type.
        ValueError: blank goal/task description, a dependency naming an
            unknown task, or store wiring that is inconsistent with the
            supplied instances (``execution_planner`` / ``pipeline_engine``
            wired to different collaborators, or ``pipeline_engine``
            wired to no ``TaskGraph``).

    After writes begin, any exception raised by a store propagates
    unchanged; no rollback is performed.
    """
    _preflight(
        plan,
        goal_manager=goal_manager,
        planning_engine=planning_engine,
        task_graph=task_graph,
        execution_planner=execution_planner,
        pipeline_engine=pipeline_engine,
    )
    tasks: tuple[Task, ...] = plan.tasks
    legacy_plan_id = plan.id
    legacy_goal_id = plan.goal.id
    goal_text = plan.goal.description

    # 2. Foundation Plan + Steps (Step.id reuses the plan-scoped Task.id).
    steps = tuple(
        Step(
            id=task.id,
            index=index,
            title=task.description,
            description=task.description,
            status=PlanStatus.DRAFT,
        )
        for index, task in enumerate(tasks)
    )
    foundation_plan = planning_engine.create_plan(goal=goal_text, steps=steps)
    plan_id = foundation_plan.id

    # 3. Nodes (store-generated ids; legacy identity in metadata).
    task_to_node: dict[str, str] = {}
    for task in tasks:
        node = task_graph.create_node(
            title=task.description,
            metadata={"task_id": task.id, "plan_id": legacy_plan_id},
        )
        task_to_node[task.id] = node.id

    # 4. Edges: parent (dependency) -> child (dependent).
    for task in tasks:
        for dependency_id in task.depends_on:
            task_graph.connect(task_to_node[dependency_id], task_to_node[task.id])

    # 5. GoalRecord referencing the projected plan and subgraph tag.
    goal = goal_manager.create_goal(
        title=goal_text,
        plan_reference=plan_id,
        graph_reference=plan_id,
        tags=(legacy_goal_id,),
    )

    # 6. ExecutionMapping with explicit, legacy-derived node order.
    ordered_node_ids = tuple(
        task_to_node[task.id] for task in plan.execution_order()
    )
    mapping = execution_planner.create_execution_plan(
        goal_id=goal.id,
        plan_id=plan_id,
        graph_id=plan_id,
        ordered_node_ids=ordered_node_ids,
        metadata={"legacy_plan_id": legacy_plan_id, "legacy_goal_id": legacy_goal_id},
    )

    # 7. PipelineRecord (stages only; no run, no execution).
    pipeline = pipeline_engine.build_pipeline(mapping.id)

    return PlanProjection(
        goal_id=goal.id,
        plan_id=plan_id,
        graph_reference=plan_id,
        mapping_id=mapping.id,
        pipeline_id=pipeline.id,
        step_ids=tuple(step.id for step in steps),
        node_ids=tuple(task_to_node[task.id] for task in tasks),
        task_to_node=task_to_node,
    )


def _preflight(
    plan: object,
    *,
    goal_manager: object,
    planning_engine: object,
    task_graph: object,
    execution_planner: object,
    pipeline_engine: object,
) -> None:
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("plan must be a core.planner.ExecutionPlan")
    if not isinstance(goal_manager, GoalManager):
        raise TypeError("goal_manager must be a GoalManager")
    if not isinstance(planning_engine, PlanningEngine):
        raise TypeError("planning_engine must be a PlanningEngine")
    if not isinstance(task_graph, TaskGraph):
        raise TypeError("task_graph must be a TaskGraph")
    if not isinstance(execution_planner, ExecutionPlanner):
        raise TypeError("execution_planner must be an ExecutionPlanner")
    if not isinstance(pipeline_engine, PipelineEngine):
        raise TypeError("pipeline_engine must be a PipelineEngine")

    description = plan.goal.description
    if not isinstance(description, str) or not description.strip():
        raise ValueError("plan.goal.description must be a non-empty string")
    ids = {task.id for task in plan.tasks}
    for task in plan.tasks:
        if not isinstance(task.description, str) or not task.description.strip():
            raise ValueError(f"task {task.id!r} must have a non-empty description")
        for dependency_id in task.depends_on:
            if dependency_id not in ids:
                raise ValueError(
                    f"task {task.id!r} depends on unknown task {dependency_id!r}"
                )

    # Wiring consistency: collaborators that a store exposes must be the
    # instances supplied here (v8.10 performs no reconciliation, so an
    # injected planner/engine wired elsewhere must fail loudly).
    for name, wired, supplied in (
        ("execution_planner.goal_manager", execution_planner.goal_manager, goal_manager),
        ("execution_planner.planning_engine", execution_planner.planning_engine, planning_engine),
        ("execution_planner.task_graph", execution_planner.task_graph, task_graph),
        ("pipeline_engine.execution_planner", pipeline_engine.execution_planner, execution_planner),
    ):
        if wired is not None and wired is not supplied:
            raise ValueError(f"{name} is wired to a different instance")
    if pipeline_engine.task_graph is None:
        raise ValueError("pipeline_engine must be wired to a TaskGraph")
    if pipeline_engine.task_graph is not task_graph:
        raise ValueError("pipeline_engine.task_graph is wired to a different instance")
