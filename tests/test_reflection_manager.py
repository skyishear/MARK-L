"""Tests for core.reflection_manager."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from core.agent.reflection_manager import (
    InvalidReflectionRecordError,
    ReflectionManager,
    ReflectionRecord,
    ReflectionRecordNotFoundError,
)


class TestAddReflection:
    def test_add_reflection_returns_record(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection(subject="task_a", what_worked="clean design")
        assert isinstance(record, ReflectionRecord)
        assert record.subject == "task_a"
        assert record.what_worked == "clean design"

    def test_add_reflection_generates_unique_ids(self) -> None:
        rm = ReflectionManager()
        r1 = rm.add_reflection("task_a")
        r2 = rm.add_reflection("task_b")
        assert r1.id != r2.id

    def test_add_reflection_sets_utc_timestamp(self) -> None:
        rm = ReflectionManager()
        before = datetime.now(timezone.utc)
        record = rm.add_reflection("task_a")
        after = datetime.now(timezone.utc)
        assert record.created_at.tzinfo == timezone.utc
        assert before <= record.created_at <= after

    def test_default_string_fields_are_empty(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert record.what_worked == ""
        assert record.what_failed == ""
        assert record.completion_summary == ""

    def test_default_list_fields_are_empty_tuples(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert record.mistakes_identified == ()
        assert record.uncertainties == ()
        assert record.improvement_suggestions == ()

    def test_default_confidence_level_is_zero(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert record.confidence_level == 0.0

    def test_list_fields_stored_as_tuples(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection(
            "task_a",
            mistakes_identified=["off by one"],
            uncertainties=["edge case unclear"],
            improvement_suggestions=["add more tests"],
        )
        assert record.mistakes_identified == ("off by one",)
        assert record.uncertainties == ("edge case unclear",)
        assert record.improvement_suggestions == ("add more tests",)

    def test_confidence_level_boundaries_accepted(self) -> None:
        rm = ReflectionManager()
        low = rm.add_reflection("task_a", confidence_level=0.0)
        high = rm.add_reflection("task_b", confidence_level=1.0)
        assert low.confidence_level == 0.0
        assert high.confidence_level == 1.0

    def test_confidence_level_below_zero_raises(self) -> None:
        rm = ReflectionManager()
        with pytest.raises(InvalidReflectionRecordError):
            rm.add_reflection("task_a", confidence_level=-0.1)

    def test_confidence_level_above_one_raises(self) -> None:
        rm = ReflectionManager()
        with pytest.raises(InvalidReflectionRecordError):
            rm.add_reflection("task_a", confidence_level=1.1)

    def test_invalid_confidence_level_does_not_store_record(self) -> None:
        rm = ReflectionManager()
        with pytest.raises(InvalidReflectionRecordError):
            rm.add_reflection("task_a", confidence_level=5.0)
        assert len(rm) == 0

    def test_default_metadata_is_empty_dict(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert record.metadata == {}

    def test_metadata_is_copied_not_aliased(self) -> None:
        rm = ReflectionManager()
        original = {"reviewer": "self"}
        record = rm.add_reflection("task_a", metadata=original)
        original["reviewer"] = "mutated"
        assert record.metadata == {"reviewer": "self"}

    def test_record_is_immutable(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        with pytest.raises(AttributeError):
            record.what_worked = "changed"  # type: ignore[misc]


class TestGetAndRequire:
    def test_get_returns_record_by_id(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert rm.get(record.id) == record

    def test_get_missing_id_returns_none(self) -> None:
        rm = ReflectionManager()
        assert rm.get("nonexistent") is None

    def test_require_returns_record(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert rm.require(record.id) == record

    def test_require_raises_when_missing(self) -> None:
        rm = ReflectionManager()
        with pytest.raises(ReflectionRecordNotFoundError):
            rm.require("nonexistent")


class TestGetBySubject:
    def test_get_by_subject_filters_correctly(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection("task_a", what_worked="x")
        rm.add_reflection("task_b", what_worked="y")
        rm.add_reflection("task_a", what_worked="z")
        results = rm.get_by_subject("task_a")
        assert [r.what_worked for r in results] == ["x", "z"]

    def test_get_by_subject_no_match_returns_empty(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection("task_a")
        assert rm.get_by_subject("task_z") == []


class TestGetAllRemoveClear:
    def test_get_all_preserves_insertion_order(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection("a")
        rm.add_reflection("b")
        rm.add_reflection("c")
        assert [r.subject for r in rm.get_all()] == ["a", "b", "c"]

    def test_get_all_on_empty_registry(self) -> None:
        rm = ReflectionManager()
        assert rm.get_all() == []

    def test_remove_deletes_record(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        rm.remove(record.id)
        assert rm.get(record.id) is None

    def test_remove_missing_id_is_noop(self) -> None:
        rm = ReflectionManager()
        rm.remove("nonexistent")
        assert len(rm) == 0

    def test_clear_empties_registry(self) -> None:
        rm = ReflectionManager()
        rm.add_reflection("task_a")
        rm.clear()
        assert len(rm) == 0
        assert rm.get_all() == []

    def test_clear_on_empty_registry_is_safe(self) -> None:
        rm = ReflectionManager()
        rm.clear()
        assert len(rm) == 0


class TestLenAndContains:
    def test_len_reflects_record_count(self) -> None:
        rm = ReflectionManager()
        assert len(rm) == 0
        rm.add_reflection("a")
        rm.add_reflection("b")
        assert len(rm) == 2

    def test_contains_operator(self) -> None:
        rm = ReflectionManager()
        record = rm.add_reflection("task_a")
        assert record.id in rm
        assert "nonexistent" not in rm


class TestThreadSafety:
    def test_concurrent_adds_preserve_count(self) -> None:
        rm = ReflectionManager()
        num_threads = 8
        adds_per_thread = 150

        def worker() -> None:
            for i in range(adds_per_thread):
                rm.add_reflection("subject", completion_summary=f"s-{i}")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(rm) == num_threads * adds_per_thread

    def test_concurrent_reads_do_not_raise(self) -> None:
        rm = ReflectionManager()
        for i in range(100):
            rm.add_reflection("subject", completion_summary=f"s-{i}")

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    rm.get_all()
                    rm.get_by_subject("subject")
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

        import core.agent.reflection_manager as module

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
            "skill",
            "agent",
        )
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)
