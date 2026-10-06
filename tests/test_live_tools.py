"""Tests for v8.41 ``core.live_tools`` — the production tool bridge (P2, P3).

Covers the declaration conversion for every real production tool (read from
``main.py`` and ``skills/`` by AST, so no GUI / audio import is needed), the
registration of callback tools, and the Gemini Live adapter: each ``tool_call``
batch is one model round executed through the router under the C8 per-call
policy (O1 hook, O2 strings, O9 records, OD-C limits per run).
"""

from __future__ import annotations

import ast
import asyncio
import os
import threading

import pytest

import core.live_tools as lt
from core.agent import Agent
from core.live_tools import (
    READ_ONLY_TOOLS,
    CallbackTool,
    LiveCall,
    LiveReply,
    LiveToolSession,
    approve_requested_call,
    declaration_to_spec,
)
from core.tool_calling import ToolCall
from core.tool_catalog import InvalidToolSchemaError, ToolCatalog, ToolSpec
from core.tool_interface import ToolRequest
from core.tool_registry import ToolRegistry
from core.tool_router import ToolRouter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _production_declarations() -> list[dict]:
    tree = ast.parse(open(os.path.join(ROOT, "main.py"), encoding="utf-8").read())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "TOOL_DECLARATIONS")
    declarations = ast.literal_eval(node.value)
    for path in ("skills/weather.py", "skills/spotify.py"):
        module = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
        for call in ast.walk(module):
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "SkillManifest":
                for keyword in call.keywords:
                    if keyword.arg == "tools":
                        declarations += ast.literal_eval(keyword.value)
    return declarations


DECLARATIONS = _production_declarations()


def decl(name: str = "open_app", **extra: object) -> dict:
    return {"name": name, "description": f"{name} tool", "parameters": {
        "type": "OBJECT", "properties": {"app_name": {"type": "STRING", "description": "the app"}}, "required": ["app_name"]}, **extra}


# ── declaration conversion ──────────────────────────────────────────────


class TestDeclarationToSpec:
    def test_types_are_lowercased_and_the_rest_is_kept(self) -> None:
        spec = declaration_to_spec(decl())
        assert spec.name == "open_app" and spec.description == "open_app tool"
        assert spec.parameters["type"] == "object" and spec.parameters["properties"]["app_name"]["type"] == "string"
        assert list(spec.parameters["required"]) == ["app_name"] and spec.parameters["properties"]["app_name"]["description"] == "the app"

    def test_nested_items_and_enums(self) -> None:
        d = {"name": "t", "description": "d", "parameters": {"type": "OBJECT", "properties": {
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}}, "kind": {"type": "STRING", "enum": ["a", "b"]}}}}
        spec = declaration_to_spec(d)
        assert spec.parameters["properties"]["tags"]["items"]["type"] == "string"
        assert list(spec.parameters["properties"]["kind"]["enum"]) == ["a", "b"]

    def test_missing_parameters_become_an_empty_object_schema(self) -> None:
        spec = declaration_to_spec({"name": "t", "description": "d"})
        assert spec.parameters["type"] == "object"

    def test_flags_are_restrictive_except_the_read_only_tools(self) -> None:
        spec = declaration_to_spec(decl())
        assert (spec.model_invocable, spec.side_effects, spec.idempotent) == (True, True, False)
        ro = declaration_to_spec(decl("web_search"))
        assert (ro.model_invocable, ro.side_effects, ro.idempotent) == (True, False, False)

    def test_unknown_keywords_fail_loudly_and_nothing_is_repaired(self) -> None:
        bad = decl()
        bad["parameters"]["properties"]["app_name"]["nullable"] = True
        with pytest.raises(InvalidToolSchemaError):
            declaration_to_spec(bad)

    @pytest.mark.parametrize("bad", [None, "x", [], {"description": "no name"}, {"name": " ", "description": "d"}])
    def test_invalid_declarations_raise(self, bad: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            declaration_to_spec(bad)  # type: ignore[arg-type]

    def test_every_production_tool_converts(self) -> None:
        assert len(DECLARATIONS) == 28  # 26 in main.py + weather_report + the spotify tool(s)
        specs = [declaration_to_spec(d) for d in DECLARATIONS]
        assert len({s.name for s in specs}) == len(specs)
        assert all(s.model_invocable and not s.idempotent for s in specs)
        assert {s.name for s in specs if not s.side_effects} == set(READ_ONLY_TOOLS)

    def test_the_read_only_set_names_real_production_tools(self) -> None:
        assert READ_ONLY_TOOLS <= {d["name"] for d in DECLARATIONS}


# ── callback tool ───────────────────────────────────────────────────────


class TestCallbackTool:
    def test_invokes_the_executor_with_name_and_a_plain_dict(self) -> None:
        seen: list[tuple[str, dict]] = []
        tool = CallbackTool("open_app", "d", lambda name, args: seen.append((name, args)) or "opened")
        result = tool.invoke(ToolRequest("open_app", {"app_name": "calc"}))
        assert (result.tool_name, result.output) == ("open_app", "opened")
        assert seen == [("open_app", {"app_name": "calc"})] and type(seen[0][1]) is dict

    def test_registers_in_a_tool_registry(self) -> None:
        registry = ToolRegistry()
        registry.register(CallbackTool("t", "d", lambda n, a: "x"))
        assert registry.has("t")


# ── session helpers ─────────────────────────────────────────────────────


class Harness:
    """A session wired to a real registry / router / catalog and a fake executor."""

    def __init__(self, *, confirm: object = approve_requested_call, recorder: object = None, responses: dict | None = None,
                 fail: dict[str, Exception] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.threads: list[str] = []
        self.responses = responses or {}
        self.fail = fail or {}
        self.registry = ToolRegistry()
        self.catalog = ToolCatalog()
        self.router = ToolRouter(self.registry)

        async def execute(name: str, arguments: dict) -> dict:
            self.threads.append(threading.current_thread().name)
            self.calls.append((name, arguments))
            if name in self.fail:
                raise self.fail[name]
            return self.responses.get(name, {"result": f"{name} done"})

        self.session = LiveToolSession(router=self.router, registry=self.registry, catalog=self.catalog,
                                       execute=execute, confirm=confirm, recorder=recorder)  # type: ignore[arg-type]
        self.session.sync_declarations(DECLARATIONS)

    def round(self, *calls: LiveCall) -> tuple[LiveReply, ...]:
        async def go() -> tuple[LiveReply, ...]:
            return await self.session.handle_round(calls)

        return asyncio.run(go())

    def rounds(self, batches: list[tuple[LiveCall, ...]]) -> list[tuple[LiveReply, ...]]:
        async def go() -> list[tuple[LiveReply, ...]]:
            return [await self.session.handle_round(b) for b in batches]

        return asyncio.run(go())


def live(call_id: str | None, name: str, **arguments: object) -> LiveCall:
    return LiveCall(call_id, name, arguments)


# ── registration (P2) ───────────────────────────────────────────────────


class TestRegistration:
    def test_every_declaration_is_registered_in_registry_and_catalog(self) -> None:
        h = Harness()
        names = {d["name"] for d in DECLARATIONS}
        assert h.session.registered_names == names
        assert all(h.registry.has(n) for n in names)
        assert {s.name for s in h.catalog.list()} == names and all(s.model_invocable for s in h.catalog.list())

    def test_sync_returns_the_declarations_unchanged_and_is_idempotent(self) -> None:
        h = Harness()
        assert h.session.sync_declarations(DECLARATIONS) is DECLARATIONS
        assert len(h.catalog.list()) == len(DECLARATIONS)

    def test_new_declarations_are_added_later(self) -> None:
        h = Harness()
        h.session.sync_declarations([{"name": "late_tool", "description": "d", "parameters": {"type": "OBJECT", "properties": {}}}])
        assert h.registry.has("late_tool") and "late_tool" in h.session.registered_names

    def test_a_bad_declaration_raises_instead_of_being_skipped(self) -> None:
        h = Harness()
        with pytest.raises(InvalidToolSchemaError):
            h.session.sync_declarations([{"name": "bad", "description": "d", "parameters": {"type": "OBJECT", "properties": {
                "x": {"type": "STRING", "format": "date"}}}}])
        assert not h.registry.has("bad")


# ── execution through the router (P3) ───────────────────────────────────


class TestExecution:
    def test_an_executed_call_returns_the_production_response_exactly(self) -> None:
        h = Harness(responses={"save_memory": {"result": "ok", "silent": True}})
        (reply,) = h.round(live("c1", "save_memory", category="notes", key="k", value="v"))
        assert reply == LiveReply("c1", "save_memory", {"result": "ok", "silent": True})
        assert h.calls == [("save_memory", {"category": "notes", "key": "k", "value": "v"})]

    def test_the_executor_runs_on_the_event_loop_thread_not_the_worker(self) -> None:
        h = Harness()
        h.round(live("c1", "system_status"))
        assert h.threads == ["MainThread"]

    def test_calls_of_a_batch_run_in_order_with_ordered_replies(self) -> None:
        h = Harness()
        replies = h.round(live("a", "system_status"), live("b", "web_search", query="x"), live("c", "recall_memory"))
        assert [r.call_id for r in replies] == ["a", "b", "c"] and [c[0] for c in h.calls] == ["system_status", "web_search", "recall_memory"]
        assert [r.response["result"] for r in replies] == ["system_status done", "web_search done", "recall_memory done"]

    def test_an_unknown_tool_is_refused_with_the_sanitized_string(self) -> None:
        h = Harness()
        (reply,) = h.round(live("c1", "format_disk"))
        assert reply.response == {"result": "error: refused (not_offered)"} and h.calls == []

    def test_a_missing_call_id_is_kept_as_none_in_the_reply(self) -> None:
        h = Harness()
        (reply,) = h.round(live(None, "system_status"))
        assert reply.call_id is None and reply.response == {"result": "system_status done"}

    def test_malformed_calls_are_never_executed(self) -> None:
        h = Harness()
        replies = h.round(live("c1", "open_app", app_name=object()), LiveCall("c2", "", {}))
        assert h.calls == [] and all(r.response == {"result": "error: refused (not_offered)"} for r in replies)

    def test_a_failing_production_executor_becomes_a_sanitized_failure(self) -> None:
        h = Harness(fail={"open_app": RuntimeError("secret path C:/Users/x")})
        (reply,) = h.round(live("c1", "open_app", app_name="calc"))
        assert reply.response == {"result": "error: failed (RuntimeError)"} and "secret" not in repr(reply)

    def test_non_string_production_results_are_returned_as_text_to_the_policy(self) -> None:
        h = Harness(responses={"system_status": {"result": 42}})
        (reply,) = h.round(live("c1", "system_status"))
        assert reply.response == {"result": 42}  # the production response is passed through untouched


# ── O1: confirmation ────────────────────────────────────────────────────


class TestConfirmation:
    def test_read_only_tools_need_no_hook(self) -> None:
        h = Harness(confirm=None)
        (reply,) = h.round(live("c1", "web_search", query="x"))
        assert reply.response == {"result": "web_search done"}

    def test_side_effecting_tools_are_refused_without_a_hook(self) -> None:
        h = Harness(confirm=None)
        (reply,) = h.round(live("c1", "open_app", app_name="calc"))
        assert reply.response == {"result": "error: refused (confirmation_denied)"} and h.calls == []

    def test_the_production_hook_defers_to_the_executor_gate(self) -> None:
        h = Harness()  # approve_requested_call
        (reply,) = h.round(live("c1", "send_message", receiver="a", message_text="b", platform="x"))
        assert reply.response == {"result": "send_message done"} and len(h.calls) == 1
        assert approve_requested_call(ToolCall("c", "n", {}), declaration_to_spec(decl())) is True

    def test_a_denying_hook_refuses(self) -> None:
        h = Harness(confirm=lambda call, spec: False)
        (reply,) = h.round(live("c1", "open_app", app_name="calc"))
        assert reply.response == {"result": "error: refused (confirmation_denied)"} and h.calls == []


# ── OD-C limits in a Live run ───────────────────────────────────────────


class TestLimits:
    def test_the_fifth_batch_with_calls_is_not_run(self) -> None:
        h = Harness()
        batches = [(live(f"c{i}", "system_status"),) for i in range(6)]
        out = h.rounds(batches)
        assert [r[0].response["result"] for r in out[:4]] == ["system_status done"] * 4
        assert out[4][0].response == {"result": "error: failed (ToolLoopExhaustedError)"}
        assert len(h.calls) == 4  # the fifth batch's call was not executed

    def test_the_run_stays_exhausted_until_it_ends(self) -> None:
        h = Harness()
        h.rounds([(live(f"c{i}", "system_status"),) for i in range(5)])
        (later,) = h.round(live("x", "system_status"))
        assert later.response == {"result": "error: failed (ToolLoopExhaustedError)"} and len(h.calls) == 4

    def test_end_run_starts_a_fresh_run(self) -> None:
        h = Harness()
        h.rounds([(live(f"c{i}", "system_status"),) for i in range(5)])
        h.session.end_run()
        (reply,) = h.round(live("y", "system_status"))
        assert reply.response == {"result": "system_status done"} and len(h.calls) == 5

    def test_counters_are_shared_by_the_batches_of_one_run(self) -> None:
        h = Harness()
        out = h.rounds([tuple(live(f"b{b}-{i}", "system_status") for i in range(4)) for b in range(3)])
        # 4 + 4 + 2 executions = 10; the 11th is refused mid-batch
        assert len(h.calls) == 10
        assert [r.response["result"] for r in out[2]] == ["system_status done"] * 2 + ["error: failed (ToolLoopExhaustedError)"] * 2

    def test_executed_calls_before_the_limit_keep_their_real_answer(self) -> None:
        h = Harness()
        (first, second) = h.round(*[live(f"a{i}", "system_status") for i in range(10)])[:2]
        assert first.response == second.response == {"result": "system_status done"}
        replies = h.round(live("z1", "system_status"), live("z2", "system_status"))
        assert all(r.response == {"result": "error: failed (ToolLoopExhaustedError)"} for r in replies)

    def test_refused_calls_do_not_count_as_executions(self) -> None:
        h = Harness()
        replies = h.round(*[live(f"g{i}", "ghost_tool") for i in range(20)])
        assert len(replies) == 20 and h.calls == []
        assert h.round(live("ok", "system_status"))[0].response == {"result": "system_status done"}

    def test_a_failing_executor_still_counts_as_an_execution(self) -> None:
        h = Harness(fail={"system_status": RuntimeError("x")})
        replies = h.round(*[live(f"f{i}", "system_status") for i in range(11)])
        assert len(h.calls) == 10 and replies[10].response == {"result": "error: failed (ToolLoopExhaustedError)"}


# ── O9 records ──────────────────────────────────────────────────────────


class TestRecorder:
    def test_the_recorder_gets_the_new_outcomes_after_each_round(self) -> None:
        seen: list[tuple] = []
        h = Harness(recorder=seen.append, fail={"open_app": ValueError("hidden")})
        h.round(live("a", "system_status"), live("b", "ghost"), live("c", "open_app", app_name="x"))
        h.round(live("d", "recall_memory"))
        assert [[(o.call_id, o.outcome, o.exception_type) for o in batch] for batch in seen] == [
            [("a", "executed", None), ("b", "refused", None), ("c", "failed", "ValueError")],
            [("d", "executed", None)],
        ]
        assert "hidden" not in repr(seen)

    def test_outcomes_before_exhaustion_are_still_recorded(self) -> None:
        seen: list[tuple] = []
        h = Harness(recorder=seen.append)
        h.round(*[live(f"a{i}", "system_status") for i in range(11)])
        assert sum(len(batch) for batch in seen) == 10

    def test_a_recorder_exception_never_breaks_a_tool_call(self) -> None:
        def boom(outcomes: tuple) -> None:
            raise RuntimeError("recorder down")

        h = Harness(recorder=boom)
        (reply,) = h.round(live("a", "system_status"))
        assert reply.response == {"result": "system_status done"}

    def test_recorder_must_be_callable_or_none(self) -> None:
        with pytest.raises(TypeError):
            LiveToolSession(router=object(), registry=object(), catalog=object(), execute=lambda n, a: None, recorder="x")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            LiveToolSession(router=object(), registry=object(), catalog=object(), execute="x")  # type: ignore[arg-type]


# ── Agent wiring ────────────────────────────────────────────────────────


class TestAgentWiring:
    def test_the_session_uses_the_agents_router_registry_and_catalog(self) -> None:
        agent = Agent()

        async def execute(name: str, arguments: dict) -> dict:
            return {"result": "ran"}

        session = agent.live_tool_session(execute=execute, confirm=approve_requested_call)
        session.sync_declarations(DECLARATIONS)
        assert agent.tool_registry.has("open_app") and agent.tool_catalog.get("open_app") is not None
        reply = asyncio.run(session.handle_round((live("c1", "system_status"),)))
        assert reply[0].response == {"result": "ran"}

    def test_the_agent_method_is_thin(self) -> None:
        import inspect

        import core.agent as agent_module

        tree = ast.parse(inspect.getsource(agent_module))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "live_tool_session")
        assert node.end_lineno - node.lineno < 30
        attrs = {a.attr for a in ast.walk(node) if isinstance(a, ast.Attribute)}
        assert not attrs & {"_tool_router", "_tool_registry", "route", "has"}
        assert {"tool_router", "tool_registry", "tool_catalog"} <= attrs
        assert len(agent_module.__all__) == 16


# ── architecture ────────────────────────────────────────────────────────


class TestArchitecture:
    def _tree(self) -> ast.Module:
        return ast.parse(open(lt.__file__, encoding="utf-8").read())

    def test_no_sdk_gui_or_legacy_imports(self) -> None:
        tree = self._tree()
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert mods == {"__future__", "asyncio", "collections.abc", "dataclasses", "typing", "core.tool_calling",
                        "core.tool_catalog", "core.tool_interface", "core.tool_runtime"}

    def test_router_and_registry_are_injected_not_imported(self) -> None:
        source = open(lt.__file__, encoding="utf-8").read()
        assert "tool_router" not in source and "tool_registry" not in source

    def test_module_level_state_is_a_single_immutable_set(self) -> None:
        for node in self._tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                names = [t.id for t in (node.targets if isinstance(node, ast.Assign) else [node.target])]
                assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp)) or names == ["__all__"], names
        assert isinstance(READ_ONLY_TOOLS, frozenset)

    def test_public_surface(self) -> None:
        assert lt.__all__ == ["CallbackTool", "LiveCall", "LiveReply", "LiveToolSession", "READ_ONLY_TOOLS",
                              "approve_requested_call", "declaration_to_spec"]

    def test_the_policy_is_the_shared_toolrun_not_a_copy(self) -> None:
        tree = self._tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "ToolRun" in names
        # the per-call rules (limits, hook, execution counting) are not re-implemented here
        assert not {"MAX_MODEL_ROUNDS", "MAX_TOOL_EXECUTIONS"} & names
        assert not {"side_effects", "confirm"} & attrs and "route" not in attrs
