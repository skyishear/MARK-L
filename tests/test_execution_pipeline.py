"""Tests for core.execution_pipeline (v3.4 Execution Pipeline Foundation)."""

from __future__ import annotations

from core.execution_pipeline import ExecutionPipeline, PipelineExecutionDescriptor
from core.planner import PlanningEngine
from core.planner_execution_orchestrator_adapter import build_orchestrator_for_plan


def _pipeline_for(goal: str, *, project: str | None = None) -> tuple[ExecutionPipeline, object]:
    plan = PlanningEngine().plan(goal)
    orchestrator = build_orchestrator_for_plan(plan)
    pipeline = ExecutionPipeline(orchestrator, plan, project=project)
    return pipeline, orchestrator


class TestReadyTaskIds:
    def test_single_step_plan_first_task_is_ready(self) -> None:
        pipeline, _ = _pipeline_for("fix the wifi")
        assert len(pipeline.ready_task_ids()) == 1

    def test_multi_step_plan_only_first_task_ready_initially(self) -> None:
        plan = PlanningEngine().plan("step one then step two then step three")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        assert pipeline.ready_task_ids() == (plan.tasks[0].id,)

    def test_next_task_becomes_ready_after_completion(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        first_id = plan.tasks[0].id
        orchestrator.mark_running(first_id)
        orchestrator.mark_completed(first_id)
        assert pipeline.ready_task_ids() == (plan.tasks[1].id,)

    def test_empty_when_nothing_ready(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        orchestrator.mark_running(plan.tasks[0].id)
        assert pipeline.ready_task_ids() == ()


class TestReadyDescriptors:
    def test_descriptor_built_for_ready_task(self) -> None:
        pipeline, _ = _pipeline_for("fix the wifi")
        descriptors = pipeline.ready_descriptors()
        assert len(descriptors) == 1
        descriptor = descriptors[0]
        assert isinstance(descriptor, PipelineExecutionDescriptor)
        assert descriptor.work_item.problem == "fix the wifi"

    def test_gather_context_kwargs_shape(self) -> None:
        pipeline, _ = _pipeline_for("fix the wifi", project="mark_l")
        descriptor = pipeline.ready_descriptors()[0]
        assert dict(descriptor.gather_context_kwargs) == {
            "problem": "fix the wifi",
            "project": "mark_l",
        }

    def test_only_ready_tasks_get_descriptors(self) -> None:
        plan = PlanningEngine().plan("step one then step two then step three")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        descriptors = pipeline.ready_descriptors()
        assert [d.task_id for d in descriptors] == [plan.tasks[0].id]

    def test_empty_tuple_when_nothing_ready(self) -> None:
        plan = PlanningEngine().plan("fix the wifi")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        orchestrator.mark_running(plan.tasks[0].id)
        assert pipeline.ready_descriptors() == ()

    def test_descriptor_is_immutable(self) -> None:
        pipeline, _ = _pipeline_for("fix the wifi")
        descriptor = pipeline.ready_descriptors()[0]
        try:
            descriptor.task_id = "changed"  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised

    def test_gather_context_kwargs_mapping_is_read_only(self) -> None:
        pipeline, _ = _pipeline_for("fix the wifi")
        descriptor = pipeline.ready_descriptors()[0]
        try:
            descriptor.gather_context_kwargs["problem"] = "changed"  # type: ignore[index]
            raised = False
        except TypeError:
            raised = True
        assert raised


class TestNoStateMutationOrExecution:
    def test_building_descriptors_does_not_change_orchestrator_state(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        before = orchestrator.snapshot()
        pipeline.ready_descriptors()
        after = orchestrator.snapshot()
        assert before == after

    def test_dangerous_goal_text_is_never_executed(self) -> None:
        # The pipeline only ever produces data — it must not attempt
        # to run or interpret the task description in any way.
        pipeline, _ = _pipeline_for("delete the system32 folder")
        descriptor = pipeline.ready_descriptors()[0]
        assert descriptor.work_item.problem == "delete the system32 folder"


class TestDeterministicOrdering:
    def test_ready_task_ids_are_deterministic_across_calls(self) -> None:
        pipeline, _ = _pipeline_for("step one then step two")
        assert pipeline.ready_task_ids() == pipeline.ready_task_ids()

    def test_descriptor_order_matches_plan_order(self) -> None:
        plan = PlanningEngine().plan("step one then step two")
        orchestrator = build_orchestrator_for_plan(plan)
        pipeline = ExecutionPipeline(orchestrator, plan)
        first_id = plan.tasks[0].id
        orchestrator.mark_running(first_id)
        orchestrator.mark_completed(first_id)
        descriptors = pipeline.ready_descriptors()
        assert descriptors[0].task_id == plan.tasks[1].id
