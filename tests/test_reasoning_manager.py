"""Tests for core.reasoning_manager."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from core.agent.reasoning_manager import (
    InvalidReasoningRecordError,
    ReasoningManager,
    ReasoningRecord,
    ReasoningRecordNotFoundError,
)


class TestAddReasoning:
    def test_add_reasoning_returns_record(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning(
            problem_statement="choose a database",
            selected_option="postgres",
        )
        assert isinstance(record, ReasoningRecord)
        assert record.problem_statement == "choose a database"
        assert record.selected_option == "postgres"

    def test_add_reasoning_generates_unique_ids(self) -> None:
        rm = ReasoningManager()
        r1 = rm.add_reasoning("p1")
        r2 = rm.add_reasoning("p2")
        assert r1.id != r2.id

    def test_add_reasoning_sets_utc_timestamp(self) -> None:
        rm = ReasoningManager()
        before = datetime.now(timezone.utc)
        record = rm.add_reasoning("p1")
        after = datetime.now(timezone.utc)
        assert record.created_at.tzinfo == timezone.utc
        assert before <= record.created_at <= after

    def test_default_string_fields_are_empty(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.selected_option == ""
        assert record.rationale == ""

    def test_default_list_fields_are_empty_tuples(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.assumptions == ()
        assert record.constraints == ()
        assert record.considered_options == ()

    def test_default_confidence_level_is_zero(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.confidence_level == 0.0

    def test_default_outcome_is_none(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.outcome is None

    def test_list_fields_stored_as_tuples(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning(
            "p1",
            assumptions=["network is reliable"],
            constraints=["must run offline"],
            considered_options=["sqlite", "postgres"],
        )
        assert record.assumptions == ("network is reliable",)
        assert record.constraints == ("must run offline",)
        assert record.considered_options == ("sqlite", "postgres")

    def test_confidence_level_boundaries_accepted(self) -> None:
        rm = ReasoningManager()
        low = rm.add_reasoning("p1", confidence_level=0.0)
        high = rm.add_reasoning("p2", confidence_level=1.0)
        assert low.confidence_level == 0.0
        assert high.confidence_level == 1.0

    def test_confidence_level_below_zero_raises(self) -> None:
        rm = ReasoningManager()
        with pytest.raises(InvalidReasoningRecordError):
            rm.add_reasoning("p1", confidence_level=-0.1)

    def test_confidence_level_above_one_raises(self) -> None:
        rm = ReasoningManager()
        with pytest.raises(InvalidReasoningRecordError):
            rm.add_reasoning("p1", confidence_level=1.1)

    def test_invalid_confidence_level_does_not_store_record(self) -> None:
        rm = ReasoningManager()
        with pytest.raises(InvalidReasoningRecordError):
            rm.add_reasoning("p1", confidence_level=5.0)
        assert len(rm) == 0

    def test_default_metadata_is_empty_dict(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.metadata == {}

    def test_metadata_is_copied_not_aliased(self) -> None:
        rm = ReasoningManager()
        original = {"trace_source": "planner"}
        record = rm.add_reasoning("p1", metadata=original)
        original["trace_source"] = "mutated"
        assert record.metadata == {"trace_source": "planner"}

    def test_record_is_immutable(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        with pytest.raises(AttributeError):
            record.rationale = "changed"  # type: ignore[misc]


class TestRecordOutcome:
    def test_record_outcome_updates_outcome_field(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1", selected_option="postgres")
        updated = rm.record_outcome(record.id, "worked well in production")
        assert updated.outcome == "worked well in production"

    def test_record_outcome_preserves_other_fields(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning(
            "p1", selected_option="postgres", rationale="scales better"
        )
        updated = rm.record_outcome(record.id, "success")
        assert updated.id == record.id
        assert updated.problem_statement == record.problem_statement
        assert updated.selected_option == record.selected_option
        assert updated.rationale == record.rationale
        assert updated.created_at == record.created_at

    def test_record_outcome_replaces_stored_record(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        rm.record_outcome(record.id, "success")
        assert rm.get(record.id).outcome == "success"  # type: ignore[union-attr]
        assert len(rm) == 1

    def test_record_outcome_missing_id_raises(self) -> None:
        rm = ReasoningManager()
        with pytest.raises(ReasoningRecordNotFoundError):
            rm.record_outcome("nonexistent", "success")

    def test_record_outcome_can_overwrite_existing_outcome(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1", outcome="initial")
        updated = rm.record_outcome(record.id, "revised")
        assert updated.outcome == "revised"


class TestGetAndRequire:
    def test_get_returns_record_by_id(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert rm.get(record.id) == record

    def test_get_missing_id_returns_none(self) -> None:
        rm = ReasoningManager()
        assert rm.get("nonexistent") is None

    def test_require_returns_record(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert rm.require(record.id) == record

    def test_require_raises_when_missing(self) -> None:
        rm = ReasoningManager()
        with pytest.raises(ReasoningRecordNotFoundError):
            rm.require("nonexistent")


class TestGetAllRemoveClear:
    def test_get_all_preserves_insertion_order(self) -> None:
        rm = ReasoningManager()
        rm.add_reasoning("p1")
        rm.add_reasoning("p2")
        rm.add_reasoning("p3")
        assert [r.problem_statement for r in rm.get_all()] == ["p1", "p2", "p3"]

    def test_get_all_on_empty_registry(self) -> None:
        rm = ReasoningManager()
        assert rm.get_all() == []

    def test_remove_deletes_record(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        rm.remove(record.id)
        assert rm.get(record.id) is None

    def test_remove_missing_id_is_noop(self) -> None:
        rm = ReasoningManager()
        rm.remove("nonexistent")
        assert len(rm) == 0

    def test_clear_empties_registry(self) -> None:
        rm = ReasoningManager()
        rm.add_reasoning("p1")
        rm.clear()
        assert len(rm) == 0
        assert rm.get_all() == []

    def test_clear_on_empty_registry_is_safe(self) -> None:
        rm = ReasoningManager()
        rm.clear()
        assert len(rm) == 0


class TestLenAndContains:
    def test_len_reflects_record_count(self) -> None:
        rm = ReasoningManager()
        assert len(rm) == 0
        rm.add_reasoning("p1")
        rm.add_reasoning("p2")
        assert len(rm) == 2

    def test_contains_operator(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        assert record.id in rm
        assert "nonexistent" not in rm


class TestThreadSafety:
    def test_concurrent_adds_preserve_count(self) -> None:
        rm = ReasoningManager()
        num_threads = 8
        adds_per_thread = 150

        def worker() -> None:
            for i in range(adds_per_thread):
                rm.add_reasoning(f"p-{i}")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(rm) == num_threads * adds_per_thread

    def test_concurrent_record_outcome_on_same_id_is_consistent(self) -> None:
        rm = ReasoningManager()
        record = rm.add_reasoning("p1")
        num_threads = 8

        def worker(tid: int) -> None:
            rm.record_outcome(record.id, f"outcome-{tid}")

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        final = rm.get(record.id)
        assert final is not None
        assert final.outcome is not None and final.outcome.startswith("outcome-")
        assert len(rm) == 1

    def test_concurrent_reads_do_not_raise(self) -> None:
        rm = ReasoningManager()
        for i in range(100):
            rm.add_reasoning(f"p-{i}")

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    rm.get_all()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


class TestStandaloneIsolation:
    def test_no_cross_module_imports(self) -> None:
        import ast

        import core.agent.reasoning_manager as module

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

        forbidden_substrings = (
            "memory",
            "history",
            "context",
            "knowledge",
            "learning",
            "reflection",
            "skill",
            "agent",
            "problemsolver",
            "problem_solver",
        )
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)
