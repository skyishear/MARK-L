"""Tests for core.execution_progress (v3.5)."""

from __future__ import annotations

from core.execution_orchestrator import ExecutionOrchestrator, OrchestratedTask
from core.execution_progress import ExecutionProgress


def _orchestrator() -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        [
            OrchestratedTask(task_id="a", depends_on=()),
            OrchestratedTask(task_id="b", depends_on=("a",)),
            OrchestratedTask(task_id="c", depends_on=("b",)),
        ]
    )


class TestFromSnapshot:
    def test_all_pending_initially(self) -> None:
        orch = _orchestrator()
        progress = ExecutionProgress.from_snapshot(orch.snapshot())
        assert progress.total == 3
        assert progress.pending == 3
        assert progress.running == progress.completed == progress.failed == progress.skipped == 0

    def test_counts_reflect_mixed_states(self) -> None:
        orch = _orchestrator()
        orch.mark_running("a")
        orch.mark_completed("a")
        orch.mark_running("b")
        orch.mark_failed("b")
        orch.mark_skipped("c")
        progress = ExecutionProgress.from_snapshot(orch.snapshot())
        assert (progress.pending, progress.running, progress.completed, progress.failed, progress.skipped) == (
            0, 0, 1, 1, 1,
        )


class TestFromOrchestrator:
    def test_matches_from_snapshot(self) -> None:
        orch = _orchestrator()
        orch.mark_running("a")
        orch.mark_completed("a")
        assert ExecutionProgress.from_orchestrator(orch) == ExecutionProgress.from_snapshot(
            orch.snapshot()
        )

    def test_does_not_mutate_orchestrator_state(self) -> None:
        orch = _orchestrator()
        before = orch.snapshot()
        ExecutionProgress.from_orchestrator(orch)
        assert orch.snapshot() == before


class TestPercentageComplete:
    def test_zero_percent_when_none_completed(self) -> None:
        progress = ExecutionProgress(total=3, pending=3, running=0, completed=0, failed=0, skipped=0)
        assert progress.percentage_complete == 0.0

    def test_partial_percentage(self) -> None:
        progress = ExecutionProgress(total=4, pending=1, running=0, completed=2, failed=1, skipped=0)
        assert progress.percentage_complete == 50.0

    def test_full_percentage(self) -> None:
        progress = ExecutionProgress(total=2, pending=0, running=0, completed=2, failed=0, skipped=0)
        assert progress.percentage_complete == 100.0

    def test_zero_total_does_not_divide_by_zero(self) -> None:
        progress = ExecutionProgress(total=0, pending=0, running=0, completed=0, failed=0, skipped=0)
        assert progress.percentage_complete == 0.0

    def test_progress_is_immutable(self) -> None:
        progress = ExecutionProgress(total=1, pending=1, running=0, completed=0, failed=0, skipped=0)
        try:
            progress.total = 5  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised
