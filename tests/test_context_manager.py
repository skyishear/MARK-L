"""Tests for core.context_manager."""

from __future__ import annotations

import threading

import pytest

from core.agent.context_manager import ContextKeyNotFoundError, ContextManager


class TestSetAndGet:
    def test_set_then_get_returns_value(self) -> None:
        cm = ContextManager()
        cm.set("active_project", "mark_l")
        assert cm.get("active_project") == "mark_l"

    def test_get_missing_key_returns_none_by_default(self) -> None:
        cm = ContextManager()
        assert cm.get("missing") is None

    def test_get_missing_key_returns_given_default(self) -> None:
        cm = ContextManager()
        assert cm.get("missing", "fallback") == "fallback"

    def test_set_overwrites_existing_value(self) -> None:
        cm = ContextManager()
        cm.set("k", "v1")
        cm.set("k", "v2")
        assert cm.get("k") == "v2"

    def test_set_accepts_arbitrary_value_types(self) -> None:
        cm = ContextManager()
        cm.set("list_val", [1, 2, 3])
        cm.set("dict_val", {"nested": True})
        cm.set("none_val", None)
        assert cm.get("list_val") == [1, 2, 3]
        assert cm.get("dict_val") == {"nested": True}
        assert cm.get("none_val") is None
        assert cm.has("none_val") is True


class TestRequire:
    def test_require_returns_value_when_present(self) -> None:
        cm = ContextManager()
        cm.set("k", "v")
        assert cm.require("k") == "v"

    def test_require_raises_when_missing(self) -> None:
        cm = ContextManager()
        with pytest.raises(ContextKeyNotFoundError):
            cm.require("missing")


class TestHasAndContains:
    def test_has_true_for_present_key(self) -> None:
        cm = ContextManager()
        cm.set("k", "v")
        assert cm.has("k") is True

    def test_has_false_for_missing_key(self) -> None:
        cm = ContextManager()
        assert cm.has("k") is False

    def test_contains_operator(self) -> None:
        cm = ContextManager()
        cm.set("k", "v")
        assert "k" in cm
        assert "missing" not in cm


class TestRemove:
    def test_remove_deletes_key(self) -> None:
        cm = ContextManager()
        cm.set("k", "v")
        cm.remove("k")
        assert cm.has("k") is False

    def test_remove_missing_key_is_noop(self) -> None:
        cm = ContextManager()
        cm.remove("missing")  # should not raise
        assert len(cm) == 0


class TestUpdate:
    def test_update_merges_multiple_keys(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        cm.update({"b": 2, "c": 3})
        assert cm.get("a") == 1
        assert cm.get("b") == 2
        assert cm.get("c") == 3

    def test_update_overwrites_conflicting_keys(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        cm.update({"a": 99})
        assert cm.get("a") == 99

    def test_update_with_empty_mapping_is_noop(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        cm.update({})
        assert len(cm) == 1


class TestSnapshot:
    def test_snapshot_returns_copy_of_state(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        snap = cm.snapshot()
        assert snap == {"a": 1}

    def test_snapshot_mutation_does_not_affect_manager(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        snap = cm.snapshot()
        snap["a"] = 999
        snap["b"] = "new"
        assert cm.get("a") == 1
        assert cm.has("b") is False

    def test_snapshot_on_empty_context(self) -> None:
        cm = ContextManager()
        assert cm.snapshot() == {}


class TestClearAndLen:
    def test_len_reflects_key_count(self) -> None:
        cm = ContextManager()
        assert len(cm) == 0
        cm.set("a", 1)
        cm.set("b", 2)
        assert len(cm) == 2

    def test_clear_empties_context(self) -> None:
        cm = ContextManager()
        cm.set("a", 1)
        cm.clear()
        assert len(cm) == 0
        assert cm.snapshot() == {}

    def test_clear_on_empty_context_is_safe(self) -> None:
        cm = ContextManager()
        cm.clear()
        assert len(cm) == 0


class TestThreadSafety:
    def test_concurrent_sets_preserve_all_keys(self) -> None:
        cm = ContextManager()
        num_threads = 8
        keys_per_thread = 100

        def worker(tid: int) -> None:
            for i in range(keys_per_thread):
                cm.set(f"t{tid}-k{i}", i)

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(cm) == num_threads * keys_per_thread

    def test_concurrent_reads_do_not_raise(self) -> None:
        cm = ContextManager()
        for i in range(100):
            cm.set(f"k{i}", i)

        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    cm.snapshot()
                    cm.get("k1")
                    cm.has("k2")
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

        import core.agent.context_manager as module

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

        forbidden_substrings = ("memory", "history", "knowledge", "skill", "agent")
        for name in imported_names:
            lowered = name.lower()
            assert not any(term in lowered for term in forbidden_substrings)
