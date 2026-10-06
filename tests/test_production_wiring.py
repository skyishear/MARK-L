"""Headless tests for v8.44 — production runtime wiring (contract P1, V5).

``main.py`` needs a GUI, audio and the Google SDK, so it is checked by AST (it
**uses** the Agent for tool calls, run recording and memory) and the same wiring
is exercised end to end with fakes: the real production declarations, the
Agent's live tool session with the production confirmation hook and recorder,
batches and ``end_run`` as the receive loop calls them, and a real SQLite file.
"""

from __future__ import annotations

import ast
import asyncio
import os
import sqlite3

import pytest

from core.agent import Agent
from core.live_tools import LiveCall, approve_requested_call
from core.pipeline_run import PipelineRunStatus
from memory import core_memory as cm
from tests.test_live_tools import DECLARATIONS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
TREE = ast.parse(SOURCE)


def method(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    return next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def attr_calls(node: ast.AST) -> set[str]:
    return {n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


class TestMainUsesTheAgent:
    def test_init_builds_the_tool_session_recorder_and_memory_import_from_the_agent(self) -> None:
        init = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == "__init__"
                    and "agent" in [a.arg for a in n.args.args] and "ui" in [a.arg for a in n.args.args])
        calls = attr_calls(init)
        assert {"live_tool_session", "import_production_memory"} <= calls
        text = ast.get_source_segment(SOURCE, init)
        assert "record_live_tool_outcomes" in text and "approve_requested_call" in text
        assert "core_read_memories" in text and "execute=self._run_legacy_tool" in text

    def test_receive_loop_routes_batches_through_the_session_and_ends_the_run_at_turn_complete(self) -> None:
        recv = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and "handle_round" in (ast.get_source_segment(SOURCE, n) or "")
                    and n.name not in {"_run_legacy_tool", "_execute_tool_legacy"})
        calls = attr_calls(recv)
        assert {"handle_round", "end_run", "send_tool_response"} <= calls
        assert "_execute_tool(" not in ast.get_source_segment(SOURCE, recv)

    def test_the_legacy_executor_is_kept_and_only_reached_through_the_session(self) -> None:
        assert not any(isinstance(n, ast.AsyncFunctionDef) and n.name == "_execute_tool" for n in ast.walk(TREE))
        users = [n.name for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and "_execute_tool_legacy(" in (ast.get_source_segment(SOURCE, n) or "") and n.name != "_execute_tool_legacy"]
        assert users == ["_run_legacy_tool"]
        assert "_is_high_risk(name, args)" in ast.get_source_segment(SOURCE, method("_execute_tool_legacy"))

    def test_declarations_are_synced_through_the_session_in_the_live_config(self) -> None:
        text = ast.get_source_segment(SOURCE, method("_build_config"))
        assert "self._tool_session.sync_declarations(" in text and "TOOL_DECLARATIONS" in text

    def test_main_adds_no_logic_beyond_wiring(self) -> None:
        for name in ("_run_legacy_tool",):
            assert method(name).end_lineno - method(name).lineno < 8


class Harness:
    """What ``JarvisLive`` does around a Live session, with a fake executor."""

    def __init__(self) -> None:
        self.agent = Agent()
        self.executed: list[tuple[str, dict]] = []

        async def execute(name: str, args: dict) -> dict:
            self.executed.append((name, args))
            if name == "boom":
                raise OSError("disk exploded")
            return {"result": f"{name} done"}

        self.session = self.agent.live_tool_session(
            execute=execute, confirm=approve_requested_call, recorder=self.agent.record_live_tool_outcomes)
        self.declarations = self.session.sync_declarations(DECLARATIONS)

    def round(self, *calls: LiveCall):
        return asyncio.run(self.session.handle_round(list(calls)))


class TestEndToEndHeadless:
    def test_all_production_declarations_register_and_are_returned_unchanged(self) -> None:
        h = Harness()
        assert h.declarations == DECLARATIONS and len(h.session.registered_names) == len(DECLARATIONS) == 28

    def test_an_executed_call_returns_the_legacy_response_and_is_recorded(self) -> None:
        h = Harness()
        (reply,) = h.round(LiveCall("c1", "web_search", {"query": "x"}))
        assert reply.response == {"result": "web_search done"} and h.executed == [("web_search", {"query": "x"})]
        (run,) = h.agent.pipeline_run_manager.list_runs()
        assert run.status is PipelineRunStatus.COMPLETED and run.metadata["call_id"] == "c1"
        assert [m["value"] for m in h.agent.memory_engine.recall(limit=5)] == ["success"]

    def test_an_unknown_tool_is_refused_without_running_and_recorded_as_skipped(self) -> None:
        h = Harness()
        (reply,) = h.round(LiveCall("c1", "not_a_tool", {}))
        assert reply.response == {"result": "error: refused (not_offered)"} and h.executed == []
        assert h.agent.memory_engine.count() == 0

    def test_a_failing_tool_is_sanitized_and_gets_a_failure_record(self) -> None:
        h = Harness()
        h.session.sync_declarations([{"name": "boom", "description": "x", "parameters": {"type": "OBJECT", "properties": {}}}])
        (reply,) = h.round(LiveCall("c1", "boom", {}))
        assert reply.response == {"result": "error: failed (OSError)"} and "exploded" not in repr(h.agent.reflection.get_all())
        assert [r.status for r in h.agent.pipeline_run_manager.list_runs()] == [PipelineRunStatus.FAILED]

    def test_turn_complete_resets_the_per_run_limit(self) -> None:
        h = Harness()
        for _ in range(4):  # OD-C: the 5th call-bearing response of a run is not executed
            h.round(LiveCall(None, "web_search", {"query": "x"}))
        (limited,) = h.round(LiveCall(None, "web_search", {"query": "x"}))
        assert limited.response == {"result": "error: failed (ToolLoopExhaustedError)"} and len(h.executed) == 4
        h.session.end_run()
        (reply,) = h.round(LiveCall(None, "web_search", {"query": "x"}))
        assert reply.response == {"result": "web_search done"}

    def test_a_batch_is_one_round_with_one_reply_per_call_in_order(self) -> None:
        h = Harness()
        replies = h.round(LiveCall("a", "web_search", {"query": "1"}), LiveCall("b", "system_status", {}))
        assert [(r.call_id, r.name) for r in replies] == [("a", "web_search"), ("b", "system_status")]


class TestProductionMemoryFeedsTheAgent:
    def test_non_sensitive_production_rows_reach_the_agent_and_the_store_is_unchanged(
            self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "core_memory.db"
        monkeypatch.setattr(cm, "DB_PATH", path)
        cm.init_db()
        cm.remember("preferences", "food", "pasta")
        cm.remember("identity", "pin", "1234", sensitive=True)
        with sqlite3.connect(str(path)) as c:
            before = c.execute("SELECT * FROM memories ORDER BY id").fetchall()
        agent = Agent()
        result = agent.import_production_memory(cm.read_memories)
        assert result.imported == 1 and "1234" not in repr(agent.memory_engine.recall(limit=50))
        with sqlite3.connect(str(path)) as c:
            assert c.execute("SELECT * FROM memories ORDER BY id").fetchall() == before
