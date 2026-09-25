"""Tests for v8.17 Tool Dispatch Decision."""

from __future__ import annotations

import ast
import dataclasses
import os
import threading
from types import MappingProxyType

import pytest

import core.tool_dispatch as dispatch_module
from core.tool_dispatch import ToolDispatchDecision, build_tool_dispatch_decision
from core.tool_interface import StaticMockTool
from core.tool_registry import ToolRegistry

HERE = os.path.dirname(__file__)
CORE_DIR = os.path.normpath(os.path.join(HERE, "..", "core"))
MODULE_PATH = os.path.join(CORE_DIR, "tool_dispatch.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


def registry_with(*names: str) -> tuple[ToolRegistry, list[StaticMockTool]]:
    r = ToolRegistry()
    tools = [StaticMockTool(name=n) for n in names]
    for t in tools:
        r.register(t)
    return r, tools


class TestDecisionRecord:
    def test_frozen(self) -> None:
        r, _ = registry_with()
        d = build_tool_dispatch_decision("t1", "x", registry=r)
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.would_dispatch = True  # type: ignore[misc]

    def test_slots(self) -> None:
        r, _ = registry_with()
        d = build_tool_dispatch_decision("t1", "x", registry=r)
        assert not hasattr(d, "__dict__")
        with pytest.raises((AttributeError, TypeError)):
            d.extra = 1  # type: ignore[attr-defined]

    def test_field_names_exact(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(ToolDispatchDecision)) == (
            "task_id", "tool_name", "is_registered", "would_dispatch", "action", "context",
        )

    def test_equality_by_value(self) -> None:
        r, _ = registry_with("x")
        a = build_tool_dispatch_decision("t1", "x", registry=r, context={"p": 1})
        b = build_tool_dispatch_decision("t1", "x", registry=r, context={"p": 1})
        assert a == b


class TestPredicate:
    def test_registered_yields_dispatch(self) -> None:
        r, _ = registry_with("weather")
        d = build_tool_dispatch_decision("t1", "weather", registry=r)
        assert d.is_registered is True
        assert d.would_dispatch is True
        assert d.action == "dispatch"

    def test_unregistered_yields_skip(self) -> None:
        r, _ = registry_with("weather")
        d = build_tool_dispatch_decision("t1", "other", registry=r)
        assert d.is_registered is False
        assert d.would_dispatch is False
        assert d.action == "skip"

    def test_would_dispatch_equals_is_registered(self) -> None:
        r, _ = registry_with("a")
        for name in ("a", "b"):
            d = build_tool_dispatch_decision("t", name, registry=r)
            assert d.would_dispatch is d.is_registered

    def test_uses_registry_has(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r, _ = registry_with()
        calls: list[str] = []
        monkeypatch.setattr(r, "has", lambda name: calls.append(name) or True)
        d = build_tool_dispatch_decision("t", "probe", registry=r)
        assert calls == ["probe"]
        assert d.would_dispatch is True

    def test_reflects_live_registry_state(self) -> None:
        r, _ = registry_with()
        assert build_tool_dispatch_decision("t", "x", registry=r).action == "skip"
        r.register(StaticMockTool(name="x"))
        assert build_tool_dispatch_decision("t", "x", registry=r).action == "dispatch"
        r.unregister("x")
        assert build_tool_dispatch_decision("t", "x", registry=r).action == "skip"

    def test_task_and_tool_names_preserved(self) -> None:
        r, _ = registry_with()
        d = build_tool_dispatch_decision("task-9", "fix the wifi", registry=r)
        assert d.task_id == "task-9"
        assert d.tool_name == "fix the wifi"


class TestValidation:
    def test_registry_required_keyword(self) -> None:
        with pytest.raises(TypeError):
            build_tool_dispatch_decision("t", "x")  # type: ignore[call-arg]

    def test_registry_type_checked(self) -> None:
        for bad in (None, object(), {}):
            with pytest.raises(TypeError):
                build_tool_dispatch_decision("t", "x", registry=bad)  # type: ignore[arg-type]

    def test_blank_task_id_rejected(self) -> None:
        r, _ = registry_with()
        for bad in ("", "  ", 3):
            with pytest.raises(ValueError):
                build_tool_dispatch_decision(bad, "x", registry=r)  # type: ignore[arg-type]

    def test_blank_tool_name_rejected(self) -> None:
        r, _ = registry_with()
        for bad in ("", "  ", None):
            with pytest.raises(ValueError):
                build_tool_dispatch_decision("t", bad, registry=r)  # type: ignore[arg-type]

    def test_non_mapping_context_rejected(self) -> None:
        r, _ = registry_with()
        with pytest.raises(ValueError):
            build_tool_dispatch_decision("t", "x", registry=r, context=["p"])  # type: ignore[arg-type]


class TestContext:
    def test_default_context_empty_read_only(self) -> None:
        r, _ = registry_with()
        d = build_tool_dispatch_decision("t", "x", registry=r)
        assert isinstance(d.context, MappingProxyType)
        assert dict(d.context) == {}

    def test_context_copied(self) -> None:
        r, _ = registry_with()
        ctx = {"project": "p"}
        d = build_tool_dispatch_decision("t", "x", registry=r, context=ctx)
        ctx["project"] = "changed"
        ctx["new"] = 1
        assert dict(d.context) == {"project": "p"}

    def test_context_read_only(self) -> None:
        r, _ = registry_with()
        d = build_tool_dispatch_decision("t", "x", registry=r, context={"project": "p"})
        with pytest.raises(TypeError):
            d.context["project"] = "q"  # type: ignore[index]

    def test_context_values_keep_identity(self) -> None:
        r, _ = registry_with()
        obj = object()
        d = build_tool_dispatch_decision("t", "x", registry=r, context={"o": obj})
        assert d.context["o"] is obj

    def test_context_does_not_affect_decision(self) -> None:
        r, _ = registry_with("x")
        a = build_tool_dispatch_decision("t", "x", registry=r, context={"project": None})
        b = build_tool_dispatch_decision("t", "x", registry=r, context={"project": "other"})
        assert a.action == b.action == "dispatch"

    def test_empty_context_mapping_equals_default(self) -> None:
        r, _ = registry_with()
        a = build_tool_dispatch_decision("t", "x", registry=r, context={})
        b = build_tool_dispatch_decision("t", "x", registry=r)
        assert a == b


class TestNoInvocation:
    def test_no_tool_invoked(self) -> None:
        r, tools = registry_with("a", "b")
        build_tool_dispatch_decision("t", "a", registry=r)
        build_tool_dispatch_decision("t", "b", registry=r)
        build_tool_dispatch_decision("t", "c", registry=r)
        assert all(t.call_count == 0 for t in tools)

    def test_registry_not_mutated(self) -> None:
        r, _ = registry_with("a")
        before = (r.names(), r.list_tools())
        build_tool_dispatch_decision("t", "a", registry=r)
        build_tool_dispatch_decision("t", "zzz", registry=r)
        assert (r.names(), r.list_tools()) == before


class TestDeterminism:
    def test_same_inputs_same_decision(self) -> None:
        r, _ = registry_with("a")
        d1 = build_tool_dispatch_decision("t", "a", registry=r, context={"p": 1})
        d2 = build_tool_dispatch_decision("t", "a", registry=r, context={"p": 1})
        assert d1 == d2

    def test_independent_registries(self) -> None:
        r1, _ = registry_with("a")
        r2, _ = registry_with()
        assert build_tool_dispatch_decision("t", "a", registry=r1).action == "dispatch"
        assert build_tool_dispatch_decision("t", "a", registry=r2).action == "skip"

    def test_concurrent_reads_consistent(self) -> None:
        r, _ = registry_with("a")
        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(50):
                d = build_tool_dispatch_decision("t", "a", registry=r)
                with lock:
                    results.append(d.action)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        assert results == ["dispatch"] * 400


class TestPublicAPI:
    def test_all_exact(self) -> None:
        assert dispatch_module.__all__ == ["ToolDispatchDecision", "build_tool_dispatch_decision"]

    def test_no_forbidden_surface(self) -> None:
        for attr in (
            "dispatch", "route", "invoke", "execute", "SkillDispatchDecision",
            "build_dispatch_decision", "is_registered", "ToolRouter",
        ):
            assert not hasattr(dispatch_module, attr), attr


class TestArchitecture:
    def test_import_allowlist(self) -> None:
        allowed_roots = {"__future__", "dataclasses", "types", "typing"}
        allowed_full = {"core.tool_registry"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    node.module.split(".")[0] in allowed_roots
                    or node.module in allowed_full
                ), node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_forbidden_modules(self) -> None:
        forbidden = {
            "core.agent", "core.skill_dispatch", "core.skill_registry",
            "core.skill_tool_adapter", "core.tool_router", "core.ai_service",
            "core.ai_provider", "core.memory_engine", "core.reflection_engine",
            "core.planner", "core.planning_engine", "core.execution_pipeline",
            "core.execution_orchestrator", "core.execution_session",
            "core.execution_coordinator", "core.execution_result",
            "core.problem_solver", "os", "sys", "io", "socket", "asyncio",
            "threading", "subprocess", "logging", "pathlib", "json", "time",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, node.module
                assert node.module.split(".")[0] not in forbidden, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] not in forbidden, n.name

    def test_no_legacy_identifiers(self) -> None:
        # ``is_registered`` is a *field* of the decision (shape mirrors the
        # legacy decision by design); it must never be *called*.
        forbidden = {"dispatch", "register_skill", "_skills", "_tool_index", "invoke", "route"}
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden, node.id
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden, node.attr
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                assert called != "is_registered"

    def test_only_has_used_on_registry(self) -> None:
        used = {
            node.attr for node in ast.walk(_tree())
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "registry"
        }
        assert used == {"has"}

    def test_no_async_or_io(self) -> None:
        for node in ast.walk(_tree()):
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "exec", "eval", "input"}

    def test_no_module_level_mutable_state(self) -> None:
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if isinstance(node, ast.Assign)
                    else [node.target.id] if isinstance(node.target, ast.Name) else []
                )
                assert targets == ["__all__"], targets
        for name, value in vars(dispatch_module).items():
            if not name.startswith("__"):
                assert not isinstance(value, (dict, list, set)), name

    def test_no_core_module_imports_tool_dispatch_except_agent(self) -> None:
        # stage_dispatch.py (v8.22) is the one sanctioned in-core consumer.
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name not in ("tool_dispatch.py", "stage_dispatch.py"):
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "tool_dispatch" not in f.read(), name

    def test_skill_dispatch_untouched_and_distinct(self) -> None:
        from core.skill_dispatch import SkillDispatchDecision, build_dispatch_decision

        assert SkillDispatchDecision is not ToolDispatchDecision
        assert build_dispatch_decision is not build_tool_dispatch_decision
        # Same public field shape, different types — parallel runtimes.
        assert [f.name for f in dataclasses.fields(SkillDispatchDecision)] == [
            f.name for f in dataclasses.fields(ToolDispatchDecision)
        ]
