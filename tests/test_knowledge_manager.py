"""Tests for core.knowledge_manager."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest

from core.agent.knowledge_manager import (
    KnowledgeManager,
    KnowledgeReference,
    KnowledgeReferenceNotFoundError,
)


class TestAdd:
    def test_add_returns_reference(self) -> None:
        km = KnowledgeManager()
        ref = km.add(topic="python", content="uses indentation")
        assert isinstance(ref, KnowledgeReference)
        assert ref.topic == "python"
        assert ref.content == "uses indentation"

    def test_add_generates_unique_ids(self) -> None:
        km = KnowledgeManager()
        r1 = km.add("t", "a")
        r2 = km.add("t", "b")
        assert r1.id != r2.id

    def test_add_sets_utc_timestamp(self) -> None:
        km = KnowledgeManager()
        before = datetime.now(timezone.utc)
        ref = km.add("t", "c")
        after = datetime.now(timezone.utc)
        assert ref.created_at.tzinfo == timezone.utc
        assert before <= ref.created_at <= after

    def test_add_defaults_source_to_none(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert ref.source is None

    def test_add_stores_source(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c", source="web_search")
        assert ref.source == "web_search"

    def test_add_defaults_tags_to_empty_frozenset(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert ref.tags == frozenset()

    def test_add_stores_tags_as_frozenset(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c", tags={"a", "b"})
        assert ref.tags == frozenset({"a", "b"})

    def test_add_defaults_metadata_to_empty_dict(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert ref.metadata == {}

    def test_add_stores_metadata_copy_not_aliased(self) -> None:
        km = KnowledgeManager()
        original = {"confidence": 0.9}
        ref = km.add("t", "c", metadata=original)
        original["confidence"] = 0.1
        assert ref.metadata == {"confidence": 0.9}

    def test_reference_is_immutable(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        with pytest.raises(AttributeError):
            ref.content = "changed"  # type: ignore[misc]


class TestGetAndRequire:
    def test_get_returns_reference_by_id(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert km.get(ref.id) == ref

    def test_get_missing_id_returns_none(self) -> None:
        km = KnowledgeManager()
        assert km.get("nonexistent") is None

    def test_require_returns_reference(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert km.require(ref.id) == ref

    def test_require_raises_when_missing(self) -> None:
        km = KnowledgeManager()
        with pytest.raises(KnowledgeReferenceNotFoundError):
            km.require("nonexistent")


class TestLookupByTopicAndTag:
    def test_get_by_topic_filters_correctly(self) -> None:
        km = KnowledgeManager()
        km.add("python", "a")
        km.add("rust", "b")
        km.add("python", "c")
        results = km.get_by_topic("python")
        assert [r.content for r in results] == ["a", "c"]

    def test_get_by_topic_no_match_returns_empty(self) -> None:
        km = KnowledgeManager()
        km.add("python", "a")
        assert km.get_by_topic("go") == []

    def test_get_by_tag_filters_correctly(self) -> None:
        km = KnowledgeManager()
        km.add("t1", "a", tags={"lang", "typed"})
        km.add("t2", "b", tags={"lang"})
        km.add("t3", "c", tags={"tool"})
        results = km.get_by_tag("lang")
        assert {r.content for r in results} == {"a", "b"}

    def test_get_by_tag_no_match_returns_empty(self) -> None:
        km = KnowledgeManager()
        km.add("t", "a", tags={"x"})
        assert km.get_by_tag("y") == []


class TestGetAllRemoveClear:
    def test_get_all_preserves_insertion_order(self) -> None:
        km = KnowledgeManager()
        km.add("t1", "a")
        km.add("t2", "b")
        km.add("t3", "c")
        assert [r.content for r in km.get_all()] == ["a", "b", "c"]

    def test_get_all_on_empty_registry(self) -> None:
        km = KnowledgeManager()
        assert km.get_all() == []

    def test_remove_deletes_reference(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        km.remove(ref.id)
        assert km.get(ref.id) is None

    def test_remove_missing_id_is_noop(self) -> None:
        km = KnowledgeManager()
        km.remove("nonexistent")
        assert len(km) == 0

    def test_clear_empties_registry(self) -> None:
        km = KnowledgeManager()
        km.add("t", "c")
        km.clear()
        assert len(km) == 0
        assert km.get_all() == []

    def test_clear_on_empty_registry_is_safe(self) -> None:
        km = KnowledgeManager()
        km.clear()
        assert len(km) == 0


class TestLenAndContains:
    def test_len_reflects_reference_count(self) -> None:
        km = KnowledgeManager()
        assert len(km) == 0
        km.add("t", "a")
        km.add("t", "b")
        assert len(km) == 2

    def test_contains_operator(self) -> None:
        km = KnowledgeManager()
        ref = km.add("t", "c")
        assert ref.id in km
        assert "nonexistent" not in km


class TestThreadSafety:
    def test_concurrent_adds_preserve_count(self) -> None:
        km = KnowledgeManager()
        num_threads = 8
        adds_per_thread = 150

        def worker() -> None:
            for i in range(adds_per_thread):
                km.add("topic", f"c-{i}")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(km) == num_threads * adds_per_thread

    def test_concurrent_reads_do_not_raise(self) -> None:
        km = KnowledgeManager()
        for i in range(100):
            km.add("topic", f"c-{i}", tags={"x"})

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    km.get_all()
                    km.get_by_topic("topic")
                    km.get_by_tag("x")
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

        import core.agent.knowledge_manager as module

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

        forbidden_substrings = ("memory", "history", "context", "skill", "agent")
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)
