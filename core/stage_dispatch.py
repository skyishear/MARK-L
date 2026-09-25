"""MARK L v8.22 — Pipeline-Stage Dispatch Decisions (read-only).

Translates the ordered stages of a v8.8 ``PipelineRecord`` into v8.17
``ToolDispatchDecision`` records, one per stage in stage order:

    PipelineStage.node_id
        → TaskGraph.get_node(node_id)
            .title                  → ToolDispatchDecision.tool_name
            .metadata["task_id"]    → ToolDispatchDecision.task_id
                                      (falls back to the node id when the
                                       node was not produced by the v8.21
                                       projection and carries no task_id)
        → build_tool_dispatch_decision(..., registry=registry)

Pure, deterministic and read-only: it never routes, never invokes a
tool, never mutates the pipeline, the graph or the registry, and never
consults the legacy skill registry. ``PipelineStage.depends_on`` is
descriptive only (v8.8) and is not evaluated here — stage order *is*
the execution order fixed at projection time (v8.21).

Dependency direction:

    Agent / callers  →  stage_dispatch  →  tool_dispatch, pipeline_engine,
                                            task_graph
    stage_dispatch  →  the router, agent, skill_* or pipeline_run     (forbidden)
"""

from __future__ import annotations

from typing import Mapping, Optional

from core.pipeline_engine import PipelineRecord
from core.task_graph import TaskGraph
from core.tool_dispatch import ToolDispatchDecision, build_tool_dispatch_decision
from core.tool_registry import ToolRegistry

__all__ = ["build_stage_dispatch_decisions"]


def build_stage_dispatch_decisions(
    pipeline: PipelineRecord,
    *,
    task_graph: TaskGraph,
    registry: ToolRegistry,
    context: Optional[Mapping[str, object]] = None,
) -> tuple[ToolDispatchDecision, ...]:
    """Build one ``ToolDispatchDecision`` per stage of ``pipeline``.

    Raises:
        TypeError: ``pipeline`` / ``task_graph`` / ``registry`` are not of
            the expected types.
        KeyError: a stage references a node id unknown to ``task_graph``.
        ValueError: propagated from ``build_tool_dispatch_decision`` for a
            blank node title or invalid context.

    An empty pipeline yields ``()``.
    """
    if not isinstance(pipeline, PipelineRecord):
        raise TypeError("pipeline must be a PipelineRecord")
    if not isinstance(task_graph, TaskGraph):
        raise TypeError("task_graph must be a TaskGraph")
    if not isinstance(registry, ToolRegistry):
        raise TypeError("registry must be a ToolRegistry")
    decisions: list[ToolDispatchDecision] = []
    for stage in pipeline.stages:
        node = task_graph.get_node(stage.node_id)
        if node is None:
            raise KeyError(stage.node_id)
        task_id = node.metadata.get("task_id", node.id)
        if not isinstance(task_id, str) or not task_id.strip():
            task_id = node.id
        decisions.append(
            build_tool_dispatch_decision(
                task_id,
                node.title,
                registry=registry,
                context=context,
            )
        )
    return tuple(decisions)
