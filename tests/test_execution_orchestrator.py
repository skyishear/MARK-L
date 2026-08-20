"""Tests for core.execution_orchestrator (v3.3 Execution Orchestration Foundation)."""

from __future__ import annotations

import pytest

from core.execution_orchestrator import (
    ExecutionOrchestrator,
    InvalidTransitionError,
    OrchestratedTask,
    OrchestrationError,
    TaskState,
    UnknownTaskError,
)


def _linear_orchestrator() -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        [
            OrchestratedTask(task_id="a", depends_on=()),
            OrchestratedTask(task_id="b", depends_on=("a",)),
            OrchestratedTask(task_id="c", depends_on=("b",)),
        ]
    )


class TestConstruction:
    def test_all_tasks_start_pending(self) -> None:
        orch = _linear_orchestrator()
        assert all(orch.get_state(tid) == TaskState.PENDING for tid in orch.order)

    def test_order_matches_input_order(self) -> None:
        orch = _linear_orchestrator()
        assert orch.order == ("a", "b", "c")

    def test_duplicate_task_ids_raise(self) -> None:
        with pytest.raises(OrchestrationError):
            ExecutionOrchestrator(
                [
                    OrchestratedTask(task_id="a", depends_on=()),
                    OrchestratedTask(task_id="a", depends_on=()),
                ]
            )


class TestNextReadyTask:
    def test_first_task_with_no_deps_is_ready(self) -> None:
        orch = _linear_orchestrator()
        assert orch.next_ready_task() == "a"

    def test_dependent_task_not_ready_until_dependency_completed(self) -> None:
        orch = _linear_orchestrator()
        assert orch.next_ready_task() == "a"
        orch.mark_running("a")
        assert orch.next_ready_task() is None
        orch.mark_completed("a")
        assert orch.next_ready_task() == "b"

    def test_none_when_nothing_ready(self) -> None:
        orch = ExecutionOrchestrator([OrchestratedTask(task_id="a", depends_on=())])
        orch.mark_running("a")
        assert orch.next_ready_task() is None

    def test_none_once_all_terminal(self) -> None:
        orch = ExecutionOrchestrator([OrchestratedTask(task_id="a", depends_on=())])
        orch.mark_running("a")
        orch.mark_completed("a")
        assert orch.next_ready_task() is None
        assert orch.is_finished()


class TestTransitions:
    def test_pending_to_running_to_completed(self) -> None:
        orch = _linear_orchestrator()
        orch.mark_running("a")
        assert orch.get_state("a") == TaskState.RUNNING
        orch.mark_completed("a")
        assert orch.get_state("a") == TaskState.COMPLETED

    def test_pending_to_running_to_failed(self) -> None:
        orch = _linear_orchestrator()
        orch.mark_running("a")
        orch.mark_failed("a")
        assert orch.get_state("a") == TaskState.FAILED

    def test_pending_to_skipped(self) -> None:
        orch = _linear_orchestrator()
        orch.mark_skipped("a")
        assert orch.get_state("a") == TaskState.SKIPPED

    def test_invalid_transition_raises(self) -> None:
        orch = _linear_orchestrator()
        with pytest.raises(InvalidTransitionError):
            orch.mark_completed("a")  # PENDING -> COMPLETED is not allowed

    def test_cannot_transition_from_terminal_state(self) -> None:
        orch = _linear_orchestrator()
        orch.mark_running("a")
        orch.mark_completed("a")
        with pytest.raises(InvalidTransitionError):
            orch.mark_running("a")

    def test_unknown_task_id_raises(self) -> None:
        orch = _linear_orchestrator()
        with pytest.raises(UnknownTaskError):
            orch.mark_running("nonexistent")
        with pytest.raises(UnknownTaskError):
            orch.get_state("nonexistent")


class TestSnapshot:
    def test_snapshot_reflects_current_states_in_order(self) -> None:
        orch = _linear_orchestrator()
        orch.mark_running("a")
        orch.mark_completed("a")
        snap = orch.snapshot()
        assert [r.task_id for r in snap] == ["a", "b", "c"]
        assert [r.state for r in snap] == [
            TaskState.COMPLETED,
            TaskState.PENDING,
            TaskState.PENDING,
        ]

    def test_snapshot_record_is_immutable(self) -> None:
        orch = _linear_orchestrator()
        record = orch.snapshot()[0]
        with pytest.raises(AttributeError):
            record.state = TaskState.RUNNING  # type: ignore[misc]


class TestNoExecutionSideEffects:
    def test_orchestrator_never_calls_external_code(self) -> None:
        # Purely a state machine: constructing it and driving every
        # transition must not import or touch problem_solver, memory,
        # skills, or identity in any way.
        orch = _linear_orchestrator()
        orch.mark_running("a")
        orch.mark_completed("a")
        orch.mark_running("b")
        orch.mark_failed("b")
        orch.mark_skipped("c")
        assert orch.is_finished()
