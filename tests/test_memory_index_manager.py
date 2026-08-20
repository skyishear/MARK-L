"""Tests for core.memory_index_manager."""

from __future__ import annotations

import threading

from core.agent.memory_index_manager import MemoryIndexManager


class TestIndex:
    def test_index_associates_item_with_keys(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b"})
        assert mim.lookup("a") == {"item1"}
        assert mim.lookup("b") == {"item1"}

    def test_index_multiple_items_same_key(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"shared"})
        mim.index("item2", {"shared"})
        assert mim.lookup("shared") == {"item1", "item2"}

    def test_index_adds_to_existing_associations(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.index("item1", {"b"})
        assert mim.keys_for("item1") == {"a", "b"}

    def test_index_with_empty_keys_is_noop(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", set())
        assert "item1" not in mim
        assert len(mim) == 0

    def test_index_duplicate_key_is_idempotent(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.index("item1", {"a"})
        assert mim.keys_for("item1") == {"a"}
        assert mim.lookup("a") == {"item1"}


class TestLookup:
    def test_lookup_missing_key_returns_empty_set(self) -> None:
        mim = MemoryIndexManager()
        assert mim.lookup("nonexistent") == set()

    def test_lookup_returns_copy_not_internal_set(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        result = mim.lookup("a")
        result.add("item2")
        assert mim.lookup("a") == {"item1"}

    def test_lookup_any_returns_union(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.index("item2", {"b"})
        mim.index("item3", {"c"})
        assert mim.lookup_any({"a", "b"}) == {"item1", "item2"}

    def test_lookup_any_with_empty_keys_returns_empty(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        assert mim.lookup_any(set()) == set()

    def test_lookup_any_with_no_matches_returns_empty(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        assert mim.lookup_any({"z"}) == set()

    def test_lookup_all_returns_intersection(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b"})
        mim.index("item2", {"a"})
        assert mim.lookup_all({"a", "b"}) == {"item1"}

    def test_lookup_all_with_empty_keys_returns_empty(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        assert mim.lookup_all(set()) == set()

    def test_lookup_all_with_no_overlap_returns_empty(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.index("item2", {"b"})
        assert mim.lookup_all({"a", "b"}) == set()

    def test_lookup_all_single_key(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.index("item2", {"a"})
        assert mim.lookup_all({"a"}) == {"item1", "item2"}


class TestKeysFor:
    def test_keys_for_returns_all_associated_keys(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b", "c"})
        assert mim.keys_for("item1") == {"a", "b", "c"}

    def test_keys_for_missing_item_returns_empty(self) -> None:
        mim = MemoryIndexManager()
        assert mim.keys_for("nonexistent") == set()

    def test_keys_for_returns_copy_not_internal_set(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        result = mim.keys_for("item1")
        result.add("b")
        assert mim.keys_for("item1") == {"a"}


class TestUnindex:
    def test_unindex_specific_keys(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b"})
        mim.unindex("item1", {"a"})
        assert mim.keys_for("item1") == {"b"}
        assert mim.lookup("a") == set()
        assert mim.lookup("b") == {"item1"}

    def test_unindex_all_keys_removes_item_entirely(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b"})
        mim.unindex("item1")
        assert "item1" not in mim
        assert mim.keys_for("item1") == set()

    def test_unindex_last_key_removes_item_from_index(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.unindex("item1", {"a"})
        assert "item1" not in mim

    def test_unindex_missing_item_is_noop(self) -> None:
        mim = MemoryIndexManager()
        mim.unindex("nonexistent")
        assert len(mim) == 0

    def test_unindex_cleans_up_empty_key_bucket(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"solo_key"})
        mim.unindex("item1", {"solo_key"})
        assert mim.lookup("solo_key") == set()

    def test_unindex_key_not_associated_is_noop_for_that_key(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.unindex("item1", {"z"})
        assert mim.keys_for("item1") == {"a"}


class TestRemoveItem:
    def test_remove_item_deletes_all_associations(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a", "b"})
        mim.remove_item("item1")
        assert "item1" not in mim
        assert mim.lookup("a") == set()
        assert mim.lookup("b") == set()

    def test_remove_item_leaves_other_items_intact(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"shared"})
        mim.index("item2", {"shared"})
        mim.remove_item("item1")
        assert mim.lookup("shared") == {"item2"}

    def test_remove_missing_item_is_noop(self) -> None:
        mim = MemoryIndexManager()
        mim.remove_item("nonexistent")
        assert len(mim) == 0


class TestClearLenContains:
    def test_len_reflects_indexed_item_count(self) -> None:
        mim = MemoryIndexManager()
        assert len(mim) == 0
        mim.index("item1", {"a"})
        mim.index("item2", {"b"})
        assert len(mim) == 2

    def test_contains_operator(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        assert "item1" in mim
        assert "nonexistent" not in mim

    def test_clear_empties_index(self) -> None:
        mim = MemoryIndexManager()
        mim.index("item1", {"a"})
        mim.clear()
        assert len(mim) == 0
        assert mim.lookup("a") == set()

    def test_clear_on_empty_index_is_safe(self) -> None:
        mim = MemoryIndexManager()
        mim.clear()
        assert len(mim) == 0


class TestThreadSafety:
    def test_concurrent_index_distinct_items_preserve_count(self) -> None:
        mim = MemoryIndexManager()
        num_threads = 8
        items_per_thread = 100

        def worker(tid: int) -> None:
            for i in range(items_per_thread):
                mim.index(f"t{tid}-i{i}", {f"key{i % 5}"})

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(mim) == num_threads * items_per_thread

    def test_concurrent_index_same_key_accumulates(self) -> None:
        mim = MemoryIndexManager()
        num_threads = 8
        items_per_thread = 50

        def worker(tid: int) -> None:
            for i in range(items_per_thread):
                mim.index(f"t{tid}-i{i}", {"shared"})

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(mim.lookup("shared")) == num_threads * items_per_thread

    def test_concurrent_reads_do_not_raise(self) -> None:
        mim = MemoryIndexManager()
        for i in range(100):
            mim.index(f"item{i}", {f"key{i % 5}"})

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    mim.lookup("key1")
                    mim.lookup_any({"key1", "key2"})
                    mim.lookup_all({"key1"})
                    mim.keys_for("item1")
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

        import core.agent.memory_index_manager as module

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
            "memoryengine",
            "history",
            "context",
            "knowledge",
            "learning",
            "skill",
            "agent",
        )
        for name in imported_names:
            lowered = name.lower().replace("_", "")
            assert not any(term in lowered for term in forbidden_substrings)
