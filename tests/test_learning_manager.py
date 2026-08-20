"""Tests for core.learning_manager."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from core.agent.learning_manager import (
    LearningCategory,
    LearningManager,
    LearningRecord,
    LearningRecordNotFoundError,
)


class TestObserveNewRecord:
    def test_observe_returns_record(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "subject", "detail")
        assert isinstance(record, LearningRecord)
        assert record.subject == "subject"
        assert record.detail == "detail"

    def test_new_record_has_occurrence_count_one(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        assert record.occurrence_count == 1

    def test_new_record_has_unique_id(self) -> None:
        lm = LearningManager()
        r1 = lm.observe(LearningCategory.OBSERVATION, "s1")
        r2 = lm.observe(LearningCategory.OBSERVATION, "s2")
        assert r1.id != r2.id

    def test_new_record_created_at_is_utc_recent(self) -> None:
        lm = LearningManager()
        before = datetime.now(timezone.utc)
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        after = datetime.now(timezone.utc)
        assert record.created_at.tzinfo == timezone.utc
        assert before <= record.created_at <= after
        assert record.last_observed_at == record.created_at

    def test_default_detail_is_empty_string(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        assert record.detail == ""

    def test_default_metadata_is_empty_dict(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        assert record.metadata == {}

    def test_metadata_is_copied_not_aliased(self) -> None:
        lm = LearningManager()
        original = {"k": "v"}
        record = lm.observe(LearningCategory.OBSERVATION, "s", metadata=original)
        original["k"] = "mutated"
        assert record.metadata == {"k": "v"}

    def test_record_is_immutable(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        with pytest.raises(AttributeError):
            record.detail = "changed"  # type: ignore[misc]


class TestObserveMerging:
    def test_repeated_observation_same_key_increments_count(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert second.occurrence_count == 2
        assert len(lm) == 1

    def test_repeated_observation_preserves_id(self) -> None:
        lm = LearningManager()
        first = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert first.id == second.id

    def test_repeated_observation_preserves_created_at(self) -> None:
        lm = LearningManager()
        first = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert first.created_at == second.created_at

    def test_repeated_observation_updates_last_observed_at(self) -> None:
        lm = LearningManager()
        first = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert second.last_observed_at >= first.last_observed_at

    def test_repeated_observation_updates_detail_when_given(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "dark_mode", "prefers dark")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode", "loves dark")
        assert second.detail == "loves dark"

    def test_repeated_observation_keeps_old_detail_if_new_is_empty(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "dark_mode", "prefers dark")
        second = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert second.detail == "prefers dark"

    def test_same_subject_different_category_creates_separate_records(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "x")
        lm.observe(LearningCategory.CORRECTION, "x")
        assert len(lm) == 2

    def test_third_observation_increments_to_three(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.OBSERVATION, "s")
        lm.observe(LearningCategory.OBSERVATION, "s")
        third = lm.observe(LearningCategory.OBSERVATION, "s")
        assert third.occurrence_count == 3


class TestConvenienceMethods:
    def test_record_correction_sets_category(self) -> None:
        lm = LearningManager()
        record = lm.record_correction("spelling", "user fixed a typo")
        assert record.category == LearningCategory.CORRECTION

    def test_record_successful_pattern_sets_category(self) -> None:
        lm = LearningManager()
        record = lm.record_successful_pattern("retry_logic")
        assert record.category == LearningCategory.SUCCESSFUL_PATTERN

    def test_record_failed_pattern_sets_category(self) -> None:
        lm = LearningManager()
        record = lm.record_failed_pattern("bad_timeout")
        assert record.category == LearningCategory.FAILED_PATTERN

    def test_record_preference_sets_category(self) -> None:
        lm = LearningManager()
        record = lm.record_preference("dark_mode")
        assert record.category == LearningCategory.PREFERENCE

    def test_record_observation_sets_category(self) -> None:
        lm = LearningManager()
        record = lm.record_observation("general_note")
        assert record.category == LearningCategory.OBSERVATION


class TestGetAndRequire:
    def test_get_returns_record_by_id(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        assert lm.get(record.id) == record

    def test_get_missing_id_returns_none(self) -> None:
        lm = LearningManager()
        assert lm.get("nonexistent") is None

    def test_require_returns_record(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "s")
        assert lm.require(record.id) == record

    def test_require_raises_when_missing(self) -> None:
        lm = LearningManager()
        with pytest.raises(LearningRecordNotFoundError):
            lm.require("nonexistent")


class TestLookupByCategoryAndSubject:
    def test_get_by_category_filters_correctly(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "a")
        lm.observe(LearningCategory.CORRECTION, "b")
        lm.observe(LearningCategory.PREFERENCE, "c")
        results = lm.get_by_category(LearningCategory.PREFERENCE)
        assert {r.subject for r in results} == {"a", "c"}

    def test_get_by_category_no_match_returns_empty(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "a")
        assert lm.get_by_category(LearningCategory.FAILED_PATTERN) == []

    def test_get_by_subject_filters_correctly(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        lm.observe(LearningCategory.CORRECTION, "dark_mode")
        lm.observe(LearningCategory.OBSERVATION, "other")
        results = lm.get_by_subject("dark_mode")
        assert len(results) == 2

    def test_get_by_subject_no_match_returns_empty(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "a")
        assert lm.get_by_subject("nonexistent") == []


class TestGetAllRemoveClear:
    def test_get_all_preserves_insertion_order(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.OBSERVATION, "a")
        lm.observe(LearningCategory.OBSERVATION, "b")
        lm.observe(LearningCategory.OBSERVATION, "c")
        assert [r.subject for r in lm.get_all()] == ["a", "b", "c"]

    def test_get_all_on_empty_registry(self) -> None:
        lm = LearningManager()
        assert lm.get_all() == []

    def test_remove_deletes_record(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "a")
        lm.remove(record.id)
        assert lm.get(record.id) is None

    def test_remove_clears_merge_index(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        lm.remove(record.id)
        again = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert again.occurrence_count == 1
        assert again.id != record.id

    def test_remove_missing_id_is_noop(self) -> None:
        lm = LearningManager()
        lm.remove("nonexistent")
        assert len(lm) == 0

    def test_clear_empties_registry(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.OBSERVATION, "a")
        lm.clear()
        assert len(lm) == 0
        assert lm.get_all() == []

    def test_clear_resets_merge_index(self) -> None:
        lm = LearningManager()
        lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        lm.clear()
        fresh = lm.observe(LearningCategory.PREFERENCE, "dark_mode")
        assert fresh.occurrence_count == 1


class TestLenAndContains:
    def test_len_reflects_record_count(self) -> None:
        lm = LearningManager()
        assert len(lm) == 0
        lm.observe(LearningCategory.OBSERVATION, "a")
        lm.observe(LearningCategory.OBSERVATION, "b")
        assert len(lm) == 2

    def test_contains_operator(self) -> None:
        lm = LearningManager()
        record = lm.observe(LearningCategory.OBSERVATION, "a")
        assert record.id in lm
        assert "nonexistent" not in lm


class TestThreadSafety:
    def test_concurrent_observe_same_key_sums_to_expected_count(self) -> None:
        lm = LearningManager()
        num_threads = 8
        observations_per_thread = 100

        def worker() -> None:
            for _ in range(observations_per_thread):
                lm.observe(LearningCategory.PREFERENCE, "shared_subject")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(lm) == 1
        record = lm.get_by_subject("shared_subject")[0]
        assert record.occurrence_count == num_threads * observations_per_thread

    def test_concurrent_observe_distinct_keys_preserve_count(self) -> None:
        lm = LearningManager()
        num_threads = 8
        observations_per_thread = 50

        def worker(tid: int) -> None:
            for i in range(observations_per_thread):
                lm.observe(LearningCategory.OBSERVATION, f"t{tid}-s{i}")

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(lm) == num_threads * observations_per_thread

    def test_concurrent_reads_do_not_raise(self) -> None:
        lm = LearningManager()
        for i in range(100):
            lm.observe(LearningCategory.OBSERVATION, f"s{i}")

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    lm.get_all()
                    lm.get_by_category(LearningCategory.OBSERVATION)
                    lm.get_by_subject("s1")
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

        import core.agent.learning_manager as module

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
            "skill",
            "agent",
        )
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)
