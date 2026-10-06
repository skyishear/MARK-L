"""Tests for v8.42 ``core.production_memory`` — the read-only, one-way bridge from
the production SQLite memory into the Agent's in-process ``MemoryEngine`` (P4).

Owner decisions covered: OD-4 (read-only one-way bridge), OD-5 (nothing is
persisted), and O3 (anything not explicitly non-sensitive is never copied).
The reader is exercised against a real SQLite file in a temp directory.
"""

from __future__ import annotations

import ast
import dataclasses
import sqlite3

import pytest

import core.production_memory as pm
from core.agent import Agent
from core.memory_context import MemoryRequest, select_memories
from core.memory_engine import MemoryEngine
from core.production_memory import SOURCE, ProductionMemoryImport, import_production_memory
from memory import core_memory as cm


def row(key: str = "color", value: str = "blue", **kw: object) -> dict:
    base = {"category": "preferences", "key": key, "value": value, "importance": 3, "confidence": 1.0,
            "project": None, "memory_type": "permanent", "sensitive": 0}
    base.update(kw)
    return base


def entries(engine: MemoryEngine) -> list[dict]:
    return engine.recall(limit=1000)


# ── O3 at the door ──────────────────────────────────────────────────────


class TestSensitivity:
    @pytest.mark.parametrize("flag", [0, False])
    def test_explicitly_non_sensitive_rows_are_copied(self, flag: object) -> None:
        e = MemoryEngine()
        assert import_production_memory(e, [row(sensitive=flag)]) == ProductionMemoryImport(1, 0, 0, 0)
        assert e.count() == 1

    @pytest.mark.parametrize("flag", [1, True, None, "0", "false", 0.0, 2, -1, [], "no"])
    def test_anything_else_is_treated_as_sensitive_and_never_copied(self, flag: object) -> None:
        e = MemoryEngine()
        assert import_production_memory(e, [row(sensitive=flag)]) == ProductionMemoryImport(0, 0, 1, 0)
        assert e.count() == 0

    def test_a_missing_flag_is_sensitive(self) -> None:
        r = row()
        del r["sensitive"]
        e = MemoryEngine()
        assert import_production_memory(e, [r]).skipped_sensitive == 1 and e.count() == 0

    def test_sensitive_values_cannot_reach_injection(self) -> None:
        e = MemoryEngine()
        import_production_memory(e, [row("pin", "secret-1234", sensitive=1), row("pet", "dog")])
        injected = select_memories(MemoryRequest(source=e), "")
        assert [m["key"] for m in injected] == ["pet"]
        assert "secret-1234" not in repr(entries(e))

    def test_copied_entries_are_marked_non_sensitive_and_from_the_production_source(self) -> None:
        e = MemoryEngine()
        import_production_memory(e, [row(importance=5, confidence=0.5, project="p1", memory_type="project")])
        (entry,) = entries(e)
        assert entry["sensitive"] is False and entry["source"] == SOURCE == "production_memory"
        assert (entry["category"], entry["key"], entry["value"]) == ("preferences", "color", "blue")
        assert (entry["importance"], entry["confidence"], entry["project"], entry["memory_type"]) == (5, 0.5, "p1", "project")


# ── idempotency and invalid rows ────────────────────────────────────────


class TestIdempotency:
    def test_a_second_import_adds_nothing(self) -> None:
        e = MemoryEngine()
        rows = [row("a", "1"), row("b", "2", project="x")]
        assert import_production_memory(e, rows) == ProductionMemoryImport(2, 0, 0, 0)
        assert import_production_memory(e, rows) == ProductionMemoryImport(0, 2, 0, 0)
        assert e.count() == 2

    def test_a_changed_value_is_added_as_a_new_entry(self) -> None:
        e = MemoryEngine()
        import_production_memory(e, [row("a", "old")])
        assert import_production_memory(e, [row("a", "new")]).imported == 1
        assert sorted(x["value"] for x in entries(e)) == ["new", "old"]  # snapshot, not a mirror (documented)

    def test_same_key_in_different_projects_are_distinct(self) -> None:
        e = MemoryEngine()
        assert import_production_memory(e, [row("a", "1", project="x"), row("a", "1", project="y"), row("a", "1")]).imported == 3

    def test_other_engine_entries_are_never_touched_or_mistaken_for_imports(self) -> None:
        e = MemoryEngine()
        e.remember("preferences", "color", "blue", source="user_stated")  # same data, other source
        assert import_production_memory(e, [row()]).imported == 1
        assert e.count() == 2

    @pytest.mark.parametrize("bad", [
        row(importance=0), row(importance=9), row(importance="x"), row(confidence=3), row(value=5),
        row(category=""), row(key=" "),
    ])
    def test_rejected_rows_are_counted_and_skipped(self, bad: dict) -> None:
        e = MemoryEngine()
        assert import_production_memory(e, [bad, row("ok", "v")]) == ProductionMemoryImport(1, 0, 0, 1)
        assert [x["key"] for x in entries(e)] == ["ok"]

    def test_empty_input(self) -> None:
        assert import_production_memory(MemoryEngine(), []) == ProductionMemoryImport(0, 0, 0, 0)

    def test_counts_only_never_content(self) -> None:
        fields = [f.name for f in dataclasses.fields(ProductionMemoryImport)]
        assert fields == ["imported", "unchanged", "skipped_sensitive", "skipped_invalid"]

    def test_a_row_with_an_empty_project_means_no_project(self) -> None:
        e = MemoryEngine()
        import_production_memory(e, [row(project="")])
        assert entries(e)[0]["project"] is None


# ── the production reader (real SQLite) ─────────────────────────────────


@pytest.fixture()
def db(tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> str:
    path = tmp_path / "core_memory.db"
    monkeypatch.setattr(cm, "DB_PATH", path)
    cm.init_db()
    cm.remember("preferences", "color", "blue", importance=4)
    cm.remember("notes", "pet", "dog", project="home")
    cm.remember("identity", "pin_hint", "private", sensitive=True)
    cm.remember("notes", "temp", "short lived", ttl_days=1, memory_type="temporary")
    with sqlite3.connect(str(path)) as conn:  # an already-expired row
        conn.execute("INSERT INTO memories (category,key,value,memory_type,importance,confidence,source,project,sensitive,created_at,last_used,expires_at)"
                     " VALUES ('notes','old','gone','temporary',3,1.0,'x',NULL,0,'2020-01-01 00:00:00','2020-01-01 00:00:00','2020-01-02 00:00:00')")
    return str(path)


def dump(path: str) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT * FROM memories ORDER BY id").fetchall()


class TestProductionReader:
    def test_excludes_sensitive_and_expired_rows_by_default(self, db: str) -> None:
        rows = cm.read_memories()
        assert sorted(r["key"] for r in rows) == ["color", "pet", "temp"]
        assert all(r["sensitive"] == 0 for r in rows)

    def test_sensitive_rows_only_when_asked(self, db: str) -> None:
        assert "pin_hint" in {r["key"] for r in cm.read_memories(include_sensitive=True)}

    def test_never_writes_to_the_production_store(self, db: str) -> None:
        before = dump(db)
        cm.read_memories()
        cm.read_memories(include_sensitive=True, limit=2)
        assert dump(db) == before  # last_used untouched, nothing pruned, nothing added

    def test_recall_does_touch_last_used_which_is_why_the_bridge_does_not_use_it(self, db: str) -> None:
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE memories SET last_used = '2000-01-01 00:00:00'")
        cm.recall(query="color")
        with sqlite3.connect(db) as conn:
            touched = dict(conn.execute("SELECT key, last_used FROM memories").fetchall())
        assert touched["color"] != "2000-01-01 00:00:00" and touched["pet"] == "2000-01-01 00:00:00"

    def test_respects_the_limit_and_the_importance_order(self, db: str) -> None:
        rows = cm.read_memories(limit=2)
        assert len(rows) == 2 and rows[0]["key"] == "color"  # importance 4 first

    def test_end_to_end_into_an_engine(self, db: str) -> None:
        e = MemoryEngine()
        result = import_production_memory(e, cm.read_memories())
        assert result.imported == 3 and result.skipped_sensitive == 0
        before = dump(db)
        assert {x["key"] for x in entries(e)} == {"color", "pet", "temp"} and "private" not in repr(entries(e))
        import_production_memory(MemoryEngine(), cm.read_memories())
        assert dump(db) == before  # reading and importing never changes the production store

    def test_the_bridge_through_the_unfiltered_reader_still_never_copies_sensitive_rows(self, db: str) -> None:
        e = MemoryEngine()
        result = import_production_memory(e, cm.read_memories(include_sensitive=True))
        assert result.skipped_sensitive == 1 and "pin_hint" not in {x["key"] for x in entries(e)}


# ── Agent wiring and architecture ───────────────────────────────────────


class TestAgentWiring:
    def test_the_agent_imports_into_its_own_memory_engine(self) -> None:
        agent = Agent()
        result = agent.import_production_memory(lambda: [row("a", "1"), row("b", "2", sensitive=1)])
        assert result == ProductionMemoryImport(1, 0, 1, 0)
        assert [x["key"] for x in agent.memory_engine.recall()] == ["a"]

    def test_injection_into_a_request_sees_only_the_copied_non_sensitive_memory(self) -> None:
        agent = Agent()
        agent.import_production_memory(lambda: [row("food", "likes pasta"), row("pin", "1234", sensitive=1)])
        chosen = select_memories(MemoryRequest(source=agent.memory_engine), "pasta")
        assert [m["key"] for m in chosen] == ["food"]

    def test_the_agent_method_is_thin(self) -> None:
        import inspect

        import core.agent as agent_module

        tree = ast.parse(inspect.getsource(agent_module))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "import_production_memory")
        assert node.end_lineno - node.lineno < 15 and len(agent_module.__all__) == 16

    def test_the_leaf_is_stdlib_only_stateless_and_database_free(self) -> None:
        tree = ast.parse(open(pm.__file__, encoding="utf-8").read())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert mods == {"__future__", "collections.abc", "dataclasses", "typing"}
        assert "sqlite3" not in {n for n in mods}
        assert pm.__all__ == ["ProductionMemoryImport", "SOURCE", "import_production_memory"]

    def test_production_memory_stays_untouched_by_the_v8_memory_modules(self) -> None:
        for name in ("memory_engine.py", "memory_context.py"):
            source = open(pm.__file__.replace("production_memory.py", name), encoding="utf-8").read()
            assert "production_memory" not in source and "core_memory" not in source
