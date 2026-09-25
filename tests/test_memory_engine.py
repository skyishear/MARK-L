"""Tests for the in-process MemoryEngine and Agent wiring."""

from __future__ import annotations

import pytest

from core.agent import Agent
from core.memory_engine import MemoryEngine


class TestMemoryEngineRemember:
    def test_remember_returns_id(self) -> None:
        e = MemoryEngine()
        rid = e.remember("cat", "k", "v")
        assert isinstance(rid, str) and len(rid) > 0
        assert e.count() == 1

    def test_remember_stores_canonical_fields(self) -> None:
        e = MemoryEngine()
        rid = e.remember("facts", "k", "v", importance=5, confidence=0.9,
                         source="test", project="mark-l",
                         memory_type="permanent", sensitive=True, ttl_days=30)
        rows = e.recall(category="facts")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == rid
        assert row["category"] == "facts"
        assert row["key"] == "k"
        assert row["value"] == "v"
        assert row["importance"] == 5
        assert row["confidence"] == 0.9
        assert row["source"] == "test"
        assert row["project"] == "mark-l"
        assert row["memory_type"] == "permanent"
        assert row["sensitive"] is True
        assert row["ttl_days"] == 30

    @pytest.mark.parametrize("bad", ["", "  ", None])
    def test_remember_rejects_blank_category(self, bad) -> None:
        e = MemoryEngine()
        with pytest.raises(ValueError):
            e.remember(bad, "k", "v")

    @pytest.mark.parametrize("bad", ["", "  "])
    def test_remember_rejects_blank_key(self, bad) -> None:
        e = MemoryEngine()
        with pytest.raises(ValueError):
            e.remember("cat", bad, "v")

    def test_remember_rejects_importance_out_of_range(self) -> None:
        e = MemoryEngine()
        with pytest.raises(ValueError):
            e.remember("cat", "k", "v", importance=0)
        with pytest.raises(ValueError):
            e.remember("cat", "k", "v", importance=6)

    def test_remember_rejects_confidence_out_of_range(self) -> None:
        e = MemoryEngine()
        with pytest.raises(ValueError):
            e.remember("cat", "k", "v", confidence=-0.1)
        with pytest.raises(ValueError):
            e.remember("cat", "k", "v", confidence=1.5)


class TestMemoryEngineRecall:
    def test_recall_empty_engine_returns_empty(self) -> None:
        assert MemoryEngine().recall() == []

    def test_recall_filter_by_category(self) -> None:
        e = MemoryEngine()
        e.remember("a", "k1", "v1")
        e.remember("b", "k2", "v2")
        assert [r["key"] for r in e.recall(category="a")] == ["k1"]
        assert [r["key"] for r in e.recall(category="b")] == ["k2"]

    def test_recall_filter_by_project(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1", project="p1")
        e.remember("c", "k2", "v2", project="p2")
        assert [r["key"] for r in e.recall(project="p1")] == ["k1"]

    def test_recall_filter_by_memory_type(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1", memory_type="episodic")
        e.remember("c", "k2", "v2", memory_type="permanent")
        assert [r["key"] for r in e.recall(memory_type="episodic")] == ["k1"]

    def test_recall_query_substring_in_key(self) -> None:
        e = MemoryEngine()
        e.remember("c", "alpha_key", "x")
        e.remember("c", "beta_key", "y")
        assert [r["key"] for r in e.recall(query="alpha")] == ["alpha_key"]

    def test_recall_query_substring_in_value(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "hello world")
        e.remember("c", "k2", "goodbye")
        assert [r["key"] for r in e.recall(query="WORLD")] == ["k1"]

    def test_recall_respects_limit(self) -> None:
        e = MemoryEngine()
        for i in range(10):
            e.remember("c", f"k{i}", f"v{i}")
        assert len(e.recall(limit=3)) == 3

    def test_recall_returns_snapshots_not_internal_refs(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1")
        snap = e.recall()[0]
        snap["value"] = "mutated"
        assert e.recall()[0]["value"] == "v1"


class TestMemoryEngineForget:
    def test_forget_by_key(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1")
        e.remember("c", "k2", "v2")
        assert e.forget(key="k1") == 1
        assert e.count() == 1

    def test_forget_by_category(self) -> None:
        e = MemoryEngine()
        e.remember("a", "k1", "v1")
        e.remember("b", "k2", "v2")
        assert e.forget(category="a") == 1
        assert e.count() == 1

    def test_forget_by_project(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1", project="p1")
        e.remember("c", "k2", "v2", project="p2")
        assert e.forget(project="p1") == 1
        assert e.count() == 1

    def test_forget_combined_filters(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1", project="p1")
        e.remember("c", "k1", "v2", project="p2")
        assert e.forget(key="k1", project="p1") == 1
        assert e.count() == 1

    def test_forget_requires_at_least_one_filter(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k", "v")
        with pytest.raises(ValueError):
            e.forget()
        assert e.count() == 1


class TestMemoryEngineIntrospection:
    def test_count_tracks_inserts_and_forgets(self) -> None:
        e = MemoryEngine()
        assert e.count() == 0
        e.remember("c", "k", "v")
        assert e.count() == 1
        e.forget(key="k")
        assert e.count() == 0

    def test_clear_empties_engine(self) -> None:
        e = MemoryEngine()
        e.remember("c", "k1", "v1")
        e.remember("c", "k2", "v2")
        e.clear()
        assert e.count() == 0

    def test_recall_order_is_insertion_order(self) -> None:
        e = MemoryEngine()
        for k in ("a", "b", "c", "d"):
            e.remember("c", k, k)
        assert [r["key"] for r in e.recall()] == ["a", "b", "c", "d"]


class TestAgentMemoryEngineWiring:
    def test_agent_owns_one_memory_engine(self) -> None:
        a = Agent()
        assert isinstance(a.memory_engine, MemoryEngine)

    def test_injected_memory_engine_is_used(self) -> None:
        e = MemoryEngine()
        a = Agent(memory_engine=e)
        assert a.memory_engine is e

    def test_default_memory_engine_is_fresh(self) -> None:
        a1, a2 = Agent(), Agent()
        assert a1.memory_engine is not a2.memory_engine

    def test_agent_clear_all_does_not_touch_memory_engine(self) -> None:
        a = Agent()
        a.memory_engine.remember("c", "k", "v")
        a.clear_all()
        assert a.memory_engine.count() == 1