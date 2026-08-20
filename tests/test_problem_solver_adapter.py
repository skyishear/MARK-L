"""Tests for core.problem_solver_adapter."""

from __future__ import annotations

from typing import Any

import pytest

from core import problem_solver
from core.agent.context_manager import ContextManager
from core.agent.problem_solver_adapter import (
    record_reasoning_from_context,
    record_reflection_from_execution,
    update_context_from_problem,
)
from core.agent.reasoning_manager import ReasoningManager
from core.agent.reflection_manager import ReflectionManager
from core.problem_solver import ExecutionResult, execute_and_verify, gather_context


@pytest.fixture(autouse=True)
def _stub_memory_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests hermetic: stub the MemoryEngine calls problem_solver.py
    makes internally, so no real SQLite database is touched.
    """
    monkeypatch.setattr(problem_solver, "recall", lambda **kwargs: [])
    monkeypatch.setattr(problem_solver, "why", lambda *args, **kwargs: [])


# ── record_reasoning_from_context ─────────────────────────────────────────


class TestRecordReasoningFromContext:
    def test_uses_real_gather_context_shape(self) -> None:
        rm = ReasoningManager()
        bundle = gather_context("wifi is slow", project="mark_l")

        record = record_reasoning_from_context(rm, "wifi is slow", bundle)

        assert record.problem_statement == "wifi is slow"
        assert record in rm.get_all()

    def test_maps_known_solutions_to_considered_options(self) -> None:
        rm = ReasoningManager()
        bundle = {
            "known_solutions": [{"value": "SOLVED | restart router"}],
            "related_decisions": [],
            "related_facts": [],
        }
        record = record_reasoning_from_context(rm, "wifi is slow", bundle)
        assert record.considered_options == ("SOLVED | restart router",)

    def test_maps_related_decisions_to_constraints(self) -> None:
        rm = ReasoningManager()
        bundle = {
            "known_solutions": [],
            "related_decisions": [{"decision": "use static IP", "reasoning": "x"}],
            "related_facts": [],
        }
        record = record_reasoning_from_context(rm, "wifi is slow", bundle)
        assert record.constraints == ("use static IP",)

    def test_maps_related_facts_to_assumptions(self) -> None:
        rm = ReasoningManager()
        bundle = {
            "known_solutions": [],
            "related_decisions": [],
            "related_facts": [
                {"category": "technical", "key": "router_model", "value": "Netgear"}
            ],
        }
        record = record_reasoning_from_context(rm, "wifi is slow", bundle)
        assert record.assumptions == ("technical/router_model: Netgear",)

    def test_empty_bundle_produces_empty_tuples(self) -> None:
        rm = ReasoningManager()
        bundle: dict[str, Any] = {}
        record = record_reasoning_from_context(rm, "problem", bundle)
        assert record.considered_options == ()
        assert record.constraints == ()
        assert record.assumptions == ()

    def test_caller_supplied_fields_are_forwarded(self) -> None:
        rm = ReasoningManager()
        bundle: dict[str, Any] = {}
        record = record_reasoning_from_context(
            rm,
            "problem",
            bundle,
            selected_option="restart router",
            rationale="known fix for this pattern",
            confidence_level=0.8,
            outcome="pending",
        )
        assert record.selected_option == "restart router"
        assert record.rationale == "known fix for this pattern"
        assert record.confidence_level == 0.8
        assert record.outcome == "pending"

    def test_non_dict_entries_are_skipped_safely(self) -> None:
        rm = ReasoningManager()
        bundle = {
            "known_solutions": ["not a dict", {"value": "ok"}],
            "related_decisions": [None, {"decision": "d1"}],
            "related_facts": [123, {"category": "c", "key": "k", "value": "v"}],
        }
        record = record_reasoning_from_context(rm, "problem", bundle)
        assert record.considered_options == ("ok",)
        assert record.constraints == ("d1",)
        assert record.assumptions == ("c/k: v",)

    def test_does_not_mutate_foundation_module_state_beyond_new_record(
        self,
    ) -> None:
        rm = ReasoningManager()
        before = len(rm)
        record_reasoning_from_context(rm, "problem", {})
        assert len(rm) == before + 1


# ── record_reflection_from_execution ──────────────────────────────────────


class TestRecordReflectionFromExecution:
    def test_uses_real_execute_and_verify_result_verified(self) -> None:
        rfm = ReflectionManager()
        result = execute_and_verify(lambda: "did it", lambda: True)

        record = record_reflection_from_execution(rfm, "restart router", result)

        assert record.confidence_level == 1.0
        assert "verified" in record.completion_summary
        assert "1 attempt" in record.completion_summary

    def test_uses_real_execute_and_verify_result_unverified(self) -> None:
        rfm = ReflectionManager()
        result = execute_and_verify(
            lambda: "tried", lambda: False, max_retries=1, retry_delay=0.0
        )

        record = record_reflection_from_execution(rfm, "restart router", result)

        assert record.confidence_level == 0.0
        assert "not verified" in record.completion_summary
        assert "2 attempt" in record.completion_summary

    def test_free_form_fields_are_forwarded_unchanged(self) -> None:
        rfm = ReflectionManager()
        result = ExecutionResult(success=True, result=None, attempts=1, verified=True)

        record = record_reflection_from_execution(
            rfm,
            "subject",
            result,
            what_worked="clean restart",
            what_failed="",
            mistakes_identified=["waited too long between retries"],
            uncertainties=["might not hold after reboot"],
            improvement_suggestions=["add a health check"],
        )

        assert record.what_worked == "clean restart"
        assert record.mistakes_identified == ("waited too long between retries",)
        assert record.uncertainties == ("might not hold after reboot",)
        assert record.improvement_suggestions == ("add a health check",)

    def test_subject_is_forwarded(self) -> None:
        rfm = ReflectionManager()
        result = ExecutionResult(success=True, result=None, attempts=1, verified=True)
        record = record_reflection_from_execution(rfm, "restart router", result)
        assert record.subject == "restart router"

    def test_does_not_mutate_foundation_module_state_beyond_new_record(
        self,
    ) -> None:
        rfm = ReflectionManager()
        before = len(rfm)
        result = ExecutionResult(success=True, result=None, attempts=1, verified=True)
        record_reflection_from_execution(rfm, "subject", result)
        assert len(rfm) == before + 1


# ── update_context_from_problem ───────────────────────────────────────────


class TestUpdateContextFromProblem:
    def test_sets_current_problem(self) -> None:
        cm = ContextManager()
        update_context_from_problem(cm, "wifi is slow")
        assert cm.get("current_problem") == "wifi is slow"

    def test_omits_project_when_not_given(self) -> None:
        cm = ContextManager()
        update_context_from_problem(cm, "wifi is slow")
        assert cm.has("current_project") is False

    def test_sets_current_project_when_given(self) -> None:
        cm = ContextManager()
        update_context_from_problem(cm, "wifi is slow", project="mark_l")
        assert cm.get("current_problem") == "wifi is slow"
        assert cm.get("current_project") == "mark_l"

    def test_returns_none(self) -> None:
        cm = ContextManager()
        result = update_context_from_problem(cm, "problem")
        assert result is None

    def test_overwrites_previous_problem(self) -> None:
        cm = ContextManager()
        update_context_from_problem(cm, "first problem")
        update_context_from_problem(cm, "second problem")
        assert cm.get("current_problem") == "second problem"


# ── No modification of ProblemSolver or Foundation modules ───────────────


class TestNoModification:
    def test_problem_solver_module_unchanged_public_api(self) -> None:
        # Confirms the adapter imported ProblemSolver's real, existing
        # public API rather than a stand-in — if any of these symbols
        # were renamed/removed, this import would already have failed
        # at collection time, but this test makes the expectation explicit.
        assert callable(problem_solver.gather_context)
        assert callable(problem_solver.format_context_for_solver)
        assert callable(problem_solver.record_outcome)
        assert callable(problem_solver.execute_and_verify)

    def test_adapter_does_not_import_memory_engine(self) -> None:
        import ast

        import core.agent.problem_solver_adapter as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        assert not any(name.startswith("memory") for name in imported_names)
