"""Tests for v8.9 Pipeline Run Status Records (Foundation Layer)."""

from __future__ import annotations

import ast
import dataclasses
import os
from types import MappingProxyType

import pytest

from core.execution_planner import ExecutionPlanner
from core.pipeline_engine import PipelineEngine
from core.pipeline_run import (
    ALLOWED_TRANSITIONS,
    PipelineRun,
    PipelineRunManager,
    PipelineRunStatus,
)

S = PipelineRunStatus


def build_engine_with_pipeline(pipeline_id: str = "pipe1") -> PipelineEngine:
    planner = ExecutionPlanner()
    m = planner.create_execution_plan(ordered_node_ids=("a", "b"))
    engine = PipelineEngine(planner)
    engine.build_pipeline(m.id, pipeline_id=pipeline_id)
    return engine


class TestEmpty:
    def test_count_is_zero(self) -> None:
        assert PipelineRunManager().count() == 0

    def test_len_is_zero(self) -> None:
        assert len(PipelineRunManager()) == 0

    def test_list_is_empty(self) -> None:
        assert PipelineRunManager().list_runs() == ()

    def test_get_unknown_returns_none(self) -> None:
        assert PipelineRunManager().get_run("nope") is None


class TestConstruction:
    def test_engine_optional(self) -> None:
        assert PipelineRunManager().pipeline_engine is None

    def test_engine_injected(self) -> None:
        e = build_engine_with_pipeline()
        assert PipelineRunManager(e).pipeline_engine is e

    def test_rejects_wrong_engine_type(self) -> None:
        with pytest.raises(TypeError):
            PipelineRunManager(object())  # type: ignore[arg-type]


class TestStatusEnum:
    def test_values(self) -> None:
        assert [s.value for s in S] == [
            "created", "running", "completed", "failed", "cancelled",
        ]

    def test_is_str_enum(self) -> None:
        assert isinstance(S.CREATED, str)
        assert S("running") is S.RUNNING

    def test_allowed_transitions_exact(self) -> None:
        assert ALLOWED_TRANSITIONS == frozenset({
            (S.CREATED, S.RUNNING),
            (S.CREATED, S.CANCELLED),
            (S.RUNNING, S.COMPLETED),
            (S.RUNNING, S.FAILED),
            (S.RUNNING, S.CANCELLED),
        })

    def test_terminal_states_have_no_outgoing_transitions(self) -> None:
        for terminal in (S.COMPLETED, S.FAILED, S.CANCELLED):
            assert not any(src == terminal for src, _ in ALLOWED_TRANSITIONS)


class TestCreateRun:
    def test_creates_record(self) -> None:
        r = PipelineRunManager().create_run("p1")
        assert isinstance(r, PipelineRun)
        assert r.pipeline_reference == "p1"

    def test_default_status_is_created(self) -> None:
        assert PipelineRunManager().create_run("p1").status is S.CREATED

    def test_id_auto_generated(self) -> None:
        r = PipelineRunManager().create_run("p1")
        assert isinstance(r.id, str) and r.id

    def test_explicit_id_preserved(self) -> None:
        assert PipelineRunManager().create_run("p1", run_id="r1").id == "r1"

    def test_duplicate_id_rejected(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1", run_id="r1")
        with pytest.raises(ValueError):
            m.create_run("p1", run_id="r1")

    def test_blank_run_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PipelineRunManager().create_run("p1", run_id="   ")

    def test_blank_pipeline_id_rejected(self) -> None:
        m = PipelineRunManager()
        with pytest.raises(ValueError):
            m.create_run("")
        with pytest.raises(ValueError):
            m.create_run("   ")

    def test_non_string_pipeline_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PipelineRunManager().create_run(42)  # type: ignore[arg-type]

    def test_timestamps_set(self) -> None:
        r = PipelineRunManager().create_run("p1")
        assert isinstance(r.created_at, float)
        assert r.created_at == r.updated_at

    def test_default_metadata_empty(self) -> None:
        assert dict(PipelineRunManager().create_run("p1").metadata) == {}

    def test_metadata_stored(self) -> None:
        r = PipelineRunManager().create_run("p1", metadata={"k": "v"})
        assert dict(r.metadata) == {"k": "v"}

    def test_non_mapping_metadata_rejected(self) -> None:
        with pytest.raises(ValueError):
            PipelineRunManager().create_run("p1", metadata=["x"])  # type: ignore[arg-type]

    def test_create_increments_count(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1")
        m.create_run("p1")
        assert m.count() == 2
        assert len(m) == 2


class TestPipelineReferenceValidation:
    def test_unwired_stores_reference_verbatim(self) -> None:
        r = PipelineRunManager().create_run("unknown-pipe")
        assert r.pipeline_reference == "unknown-pipe"

    def test_wired_known_pipeline_accepted(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        r = PipelineRunManager(e).create_run("pipe1")
        assert r.pipeline_reference == "pipe1"

    def test_wired_unknown_pipeline_rejected(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        m = PipelineRunManager(e)
        with pytest.raises(ValueError):
            m.create_run("missing")
        assert m.count() == 0

    def test_wired_engine_not_mutated(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        before = e.list_pipelines()
        PipelineRunManager(e).create_run("pipe1")
        assert e.list_pipelines() == before
        assert e.count() == 1


class TestReadListOrder:
    def test_get_returns_stored(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1", run_id="r1")
        assert m.get_run("r1") is r

    def test_list_preserves_insertion_order(self) -> None:
        m = PipelineRunManager()
        for rid in ("a", "b", "c"):
            m.create_run("p1", run_id=rid)
        assert [r.id for r in m.list_runs()] == ["a", "b", "c"]

    def test_remove_preserves_relative_order(self) -> None:
        m = PipelineRunManager()
        for rid in ("a", "b", "c"):
            m.create_run("p1", run_id=rid)
        m.remove_run("b")
        assert [r.id for r in m.list_runs()] == ["a", "c"]

    def test_list_filters_by_status(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1", run_id="a")
        m.create_run("p1", run_id="b")
        m.update_run("b", status=S.RUNNING)
        assert [r.id for r in m.list_runs(S.RUNNING)] == ["b"]
        assert [r.id for r in m.list_runs("created")] == ["a"]

    def test_list_filter_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            PipelineRunManager().list_runs("bogus")


class TestUpdateRun:
    def test_unknown_id_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            PipelineRunManager().update_run("missing", status=S.RUNNING)

    def test_status_updated_and_stored(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        new = m.update_run(r.id, status=S.RUNNING)
        assert new.status is S.RUNNING
        assert m.get_run(r.id) is new
        assert m.get_run(r.id).status is S.RUNNING

    def test_status_accepts_string(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        assert m.update_run(r.id, status="running").status is S.RUNNING

    def test_invalid_status_value_rejected(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        with pytest.raises(ValueError):
            m.update_run(r.id, status="bogus")
        with pytest.raises(ValueError):
            m.update_run(r.id, status=3)  # type: ignore[arg-type]

    def test_none_leaves_unchanged(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1", metadata={"k": 1})
        new = m.update_run(r.id)
        assert new.status is r.status
        assert dict(new.metadata) == {"k": 1}
        assert new.created_at == r.created_at

    def test_metadata_replaced(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1", metadata={"k": 1})
        new = m.update_run(r.id, metadata={"z": 2})
        assert dict(new.metadata) == {"z": 2}

    def test_pipeline_reference_immutable_across_update(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        assert m.update_run(r.id, status=S.RUNNING).pipeline_reference == "p1"

    def test_created_at_preserved_updated_at_set(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        new = m.update_run(r.id, status=S.RUNNING)
        assert new.created_at == r.created_at
        assert new.updated_at >= r.updated_at

    def test_returns_new_record_instance(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        assert m.update_run(r.id, status=S.RUNNING) is not r
        assert r.status is S.CREATED  # old snapshot unchanged


class TestStatusTransitions:
    @pytest.mark.parametrize("src,dst", sorted(ALLOWED_TRANSITIONS, key=lambda t: (t[0].value, t[1].value)))
    def test_allowed_transition(self, src: S, dst: S) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        if src is S.RUNNING:
            m.update_run(r.id, status=S.RUNNING)
        assert m.get_run(r.id).status is src
        assert m.update_run(r.id, status=dst).status is dst

    @pytest.mark.parametrize(
        "src,dst",
        sorted(
            (
                (a, b) for a in S for b in S
                if (a, b) not in ALLOWED_TRANSITIONS
            ),
            key=lambda t: (t[0].value, t[1].value),
        ),
    )
    def test_rejected_transition(self, src: S, dst: S) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        # Drive the run to ``src`` via allowed edges only.
        path = {
            S.CREATED: (),
            S.RUNNING: (S.RUNNING,),
            S.COMPLETED: (S.RUNNING, S.COMPLETED),
            S.FAILED: (S.RUNNING, S.FAILED),
            S.CANCELLED: (S.CANCELLED,),
        }[src]
        for step in path:
            m.update_run(r.id, status=step)
        assert m.get_run(r.id).status is src
        with pytest.raises(ValueError):
            m.update_run(r.id, status=dst)
        assert m.get_run(r.id).status is src  # unchanged after rejection

    def test_full_success_lifecycle(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        assert m.update_run(r.id, status=S.RUNNING).status is S.RUNNING
        assert m.update_run(r.id, status=S.COMPLETED).status is S.COMPLETED

    def test_rejected_transition_does_not_touch_metadata(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1", metadata={"k": 1})
        with pytest.raises(ValueError):
            m.update_run(r.id, status=S.COMPLETED, metadata={"z": 9})
        assert dict(m.get_run(r.id).metadata) == {"k": 1}


class TestRemoveClear:
    def test_remove_existing_returns_true(self) -> None:
        m = PipelineRunManager()
        r = m.create_run("p1")
        assert m.remove_run(r.id) is True
        assert m.get_run(r.id) is None
        assert m.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        assert PipelineRunManager().remove_run("missing") is False

    def test_clear_empties_manager(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1")
        m.create_run("p1")
        m.clear()
        assert m.count() == 0
        assert len(m) == 0
        assert m.list_runs() == ()


class TestImmutability:
    def test_run_is_frozen(self) -> None:
        r = PipelineRunManager().create_run("p1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.status = S.RUNNING  # type: ignore[misc]

    def test_run_uses_slots(self) -> None:
        r = PipelineRunManager().create_run("p1")
        with pytest.raises((AttributeError, TypeError)):
            r.extra = 1  # type: ignore[attr-defined]

    def test_metadata_is_read_only_view(self) -> None:
        r = PipelineRunManager().create_run("p1", metadata={"k": 1})
        assert isinstance(r.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            r.metadata["k"] = 2  # type: ignore[index]

    def test_metadata_does_not_alias_caller_mapping(self) -> None:
        src = {"k": 1}
        r = PipelineRunManager().create_run("p1", metadata=src)
        src["k"] = 99
        src["new"] = 1
        assert dict(r.metadata) == {"k": 1}

    def test_list_returns_tuple(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1")
        assert isinstance(m.list_runs(), tuple)

    def test_snapshot_does_not_track_later_inserts(self) -> None:
        m = PipelineRunManager()
        m.create_run("p1", run_id="a")
        snap = m.list_runs()
        m.create_run("p1", run_id="b")
        assert len(snap) == 1

    def test_old_snapshot_unchanged_after_update(self) -> None:
        m = PipelineRunManager()
        snap = m.create_run("p1")
        m.update_run(snap.id, status=S.RUNNING)
        assert snap.status is S.CREATED

    def test_record_field_names(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(PipelineRun)) == (
            "id", "pipeline_reference", "status", "created_at", "updated_at", "metadata",
        )


class TestDeterminismAndIndependence:
    def test_managers_are_independent(self) -> None:
        a, b = PipelineRunManager(), PipelineRunManager()
        a.create_run("p1")
        assert b.count() == 0

    def test_runs_are_independent(self) -> None:
        m = PipelineRunManager()
        r1 = m.create_run("p1", run_id="r1")
        r2 = m.create_run("p2", run_id="r2")
        m.update_run("r1", status=S.RUNNING)
        assert m.get_run("r2").status is S.CREATED
        m.remove_run("r1")
        assert m.get_run("r2") is r2

    def test_multiple_runs_same_pipeline(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        m = PipelineRunManager(e)
        m.create_run("pipe1", run_id="r1")
        m.create_run("pipe1", run_id="r2")
        assert [r.pipeline_reference for r in m.list_runs()] == ["pipe1", "pipe1"]

    def test_same_sequence_yields_same_statuses(self) -> None:
        def drive() -> list[S]:
            m = PipelineRunManager()
            m.create_run("p", run_id="a")
            m.create_run("p", run_id="b")
            m.update_run("a", status=S.RUNNING)
            m.update_run("a", status=S.FAILED)
            m.update_run("b", status=S.CANCELLED)
            return [r.status for r in m.list_runs()]
        assert drive() == drive() == [S.FAILED, S.CANCELLED]

    def test_no_automatic_transition(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        m = PipelineRunManager(e)
        r = m.create_run("pipe1")
        # Nothing here or in the engine advances a run on its own.
        assert m.get_run(r.id).status is S.CREATED
        assert e.get_pipeline("pipe1") is not None
        assert m.get_run(r.id).status is S.CREATED


class TestPublicAPISurface:
    def test_exposes_expected_methods(self) -> None:
        m = PipelineRunManager()
        for name in (
            "create_run", "update_run", "get_run", "list_runs",
            "remove_run", "clear", "count", "__len__",
        ):
            assert callable(getattr(m, name)), name

    def test_no_execution_or_forbidden_attributes(self) -> None:
        m = PipelineRunManager()
        for attr in (
            "run", "execute", "start", "schedule", "retry", "cancel",
            "emit", "subscribe", "progress", "save", "load", "persist",
            "mark_running", "mark_completed", "mark_failed", "next_ready_task",
            "agent", "ai_service", "memory_engine", "reflection_engine",
            "orchestrator", "session", "coordinator", "task_graph",
            "execution_planner",
        ):
            assert not hasattr(m, attr), attr

    def test_record_holds_only_opaque_data(self) -> None:
        e = build_engine_with_pipeline("pipe1")
        r = PipelineRunManager(e).create_run("pipe1")
        assert isinstance(r.pipeline_reference, str)
        assert not any(
            dataclasses.is_dataclass(getattr(r, f.name))
            for f in dataclasses.fields(r)
        )
        assert not hasattr(r, "pipeline")
        assert not hasattr(r, "engine")


class TestArchitecturalIsolation:
    @staticmethod
    def _tree() -> ast.AST:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(os.path.join(here, "..", "core", "pipeline_run.py"))
        with open(mod_path, encoding="utf-8") as f:
            return ast.parse(f.read())

    def test_imports_only_allowed_modules(self) -> None:
        allowed_roots = {
            "__future__", "dataclasses", "enum", "threading", "time",
            "typing", "uuid", "collections", "collections.abc",
            "types", "contextlib",
        }
        allowed_full = {"core.pipeline_engine"}
        forbidden_roots = {
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.ai_provider_registry", "core.default_ai_provider_registry",
            "core.claude_provider", "core.openai_provider",
            "core.gemini_provider", "core.ollama_provider",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.reflection_engine",
            "core.problem_solver", "core.planner",
            "core.skill_dispatch", "core.skill_registry",
            "core.execution_coordinator", "core.execution_orchestrator",
            "core.execution_pipeline", "core.execution_session",
            "core.execution_result", "core.execution_progress",
            "core.execution_event",
            "core.planner_execution_orchestrator_adapter",
            "core.planner_problem_solver_adapter",
            "core.goal_manager", "core.planning_engine",
            "core.task_graph", "core.execution_planner",
            "memory", "os", "sys", "io", "socket", "asyncio",
            "logging", "subprocess", "pathlib", "json", "pickle",
            "http", "urllib", "concurrent", "sqlite3", "shelve",
            "multiprocessing", "sched", "signal",
        }
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                root = module.split(".")[0]
                assert root in allowed_roots or module in allowed_full, (
                    f"PipelineRunManager must not import {module!r}"
                )
                assert not any(
                    module.startswith(f + ".") or module == f
                    for f in forbidden_roots
                ), f"PipelineRunManager must not import {module!r}"
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root in allowed_roots, n.name
                    assert root not in forbidden_roots, n.name

    def test_no_async_or_io_constructs(self) -> None:
        for node in ast.walk(self._tree()):
            assert not isinstance(
                node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
            ), "PipelineRunManager must not use async constructs"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "exec", "eval"}, node.func.id

    def test_legacy_modules_do_not_import_pipeline_run(self) -> None:
        here = os.path.dirname(__file__)
        core_dir = os.path.normpath(os.path.join(here, "..", "core"))
        for rel in (
            "execution_pipeline.py", "execution_orchestrator.py",
            "execution_session.py", "execution_coordinator.py",
            "execution_result.py", "execution_progress.py",
            "execution_event.py", "planner.py", "pipeline_engine.py",
            "execution_planner.py",
        ):
            with open(os.path.join(core_dir, rel), encoding="utf-8") as f:
                assert "pipeline_run" not in f.read(), rel


class TestCoexistenceWithLegacyExecutionStack:
    def test_legacy_execution_pipeline_still_importable(self) -> None:
        from core.execution_pipeline import ExecutionPipeline
        assert ExecutionPipeline is not PipelineRunManager
        assert ExecutionPipeline.__name__ == "ExecutionPipeline"

    def test_status_enum_distinct_from_legacy_task_state(self) -> None:
        from core.execution_orchestrator import TaskState
        assert TaskState is not PipelineRunStatus
        assert S.RUNNING is not TaskState.RUNNING
