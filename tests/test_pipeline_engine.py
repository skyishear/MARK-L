"""Tests for v8.8 Pipeline Engine (Foundation Layer)."""

from __future__ import annotations

import ast
import dataclasses
import os

import pytest

from core.execution_planner import ExecutionPlanner
from core.pipeline_engine import PipelineEngine, PipelineRecord, PipelineStage
from core.task_graph import TaskGraph


def build_graph() -> TaskGraph:
    g = TaskGraph()
    for nid in ("a", "b", "c", "d"):
        g.create_node(title=nid, node_id=nid)
    # a -> b, a -> c, b -> d, c -> d  (diamond)
    g.connect("a", "b")
    g.connect("a", "c")
    g.connect("b", "d")
    g.connect("c", "d")
    return g


def build_engine(with_graph: bool = True) -> tuple[PipelineEngine, ExecutionPlanner, TaskGraph | None]:
    g = build_graph() if with_graph else None
    planner = ExecutionPlanner(task_graph=g)
    return PipelineEngine(planner, task_graph=g), planner, g


class TestEmpty:
    def test_count_is_zero(self) -> None:
        e, _, _ = build_engine(with_graph=False)
        assert e.count() == 0

    def test_len_is_zero(self) -> None:
        e, _, _ = build_engine(with_graph=False)
        assert len(e) == 0

    def test_list_is_empty(self) -> None:
        e, _, _ = build_engine(with_graph=False)
        assert e.list_pipelines() == ()

    def test_get_unknown_returns_none(self) -> None:
        e, _, _ = build_engine(with_graph=False)
        assert e.get_pipeline("nope") is None


class TestConstruction:
    def test_requires_execution_planner(self) -> None:
        with pytest.raises(TypeError):
            PipelineEngine(None)  # type: ignore[arg-type]

    def test_rejects_wrong_planner_type(self) -> None:
        with pytest.raises(TypeError):
            PipelineEngine(object())  # type: ignore[arg-type]

    def test_rejects_wrong_graph_type(self) -> None:
        with pytest.raises(TypeError):
            PipelineEngine(ExecutionPlanner(), task_graph=object())  # type: ignore[arg-type]

    def test_exposes_collaborators(self) -> None:
        e, planner, g = build_engine()
        assert e.execution_planner is planner
        assert e.task_graph is g

    def test_graph_optional(self) -> None:
        e, _, _ = build_engine(with_graph=False)
        assert e.task_graph is None


class TestBuildPipeline:
    def test_returns_record(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan(mapping_id="m1")
        r = e.build_pipeline(m.id)
        assert isinstance(r, PipelineRecord)
        assert r.execution_mapping_reference == "m1"

    def test_id_auto_generated(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert isinstance(r.id, str) and r.id

    def test_explicit_id_preserved(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id, pipeline_id="p1")
        assert r.id == "p1"

    def test_duplicate_id_rejected(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id, pipeline_id="p1")
        with pytest.raises(ValueError):
            e.build_pipeline(m.id, pipeline_id="p1")

    def test_blank_pipeline_id_rejected(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        with pytest.raises(ValueError):
            e.build_pipeline(m.id, pipeline_id="   ")

    def test_blank_mapping_id_rejected(self) -> None:
        e, _, _ = build_engine()
        with pytest.raises(ValueError):
            e.build_pipeline("")
        with pytest.raises(ValueError):
            e.build_pipeline("   ")

    def test_non_string_mapping_id_rejected(self) -> None:
        e, _, _ = build_engine()
        with pytest.raises(ValueError):
            e.build_pipeline(123)  # type: ignore[arg-type]

    def test_missing_mapping_raises_key_error(self) -> None:
        e, _, _ = build_engine()
        with pytest.raises(KeyError):
            e.build_pipeline("missing")

    def test_missing_mapping_stores_nothing(self) -> None:
        e, _, _ = build_engine()
        with pytest.raises(KeyError):
            e.build_pipeline("missing")
        assert e.count() == 0

    def test_build_increments_count(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id)
        e.build_pipeline(m.id)
        assert e.count() == 2
        assert len(e) == 2

    def test_timestamps_set(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert isinstance(r.created_at, float)
        assert r.created_at == r.updated_at

    def test_empty_mapping_yields_no_stages(self) -> None:
        e, planner, _ = build_engine(with_graph=False)
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert r.stages == ()


class TestStageOrdering:
    def test_stages_follow_execution_order(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert tuple(s.node_id for s in r.stages) == planner.execution_order(m.id)

    def test_stage_indexes_are_sequential(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert [s.index for s in r.stages] == list(range(len(r.stages)))

    def test_explicit_order_preserved(self) -> None:
        e, planner, _ = build_engine(with_graph=False)
        m = planner.create_execution_plan(ordered_node_ids=("z", "y", "x"))
        r = e.build_pipeline(m.id)
        assert tuple(s.node_id for s in r.stages) == ("z", "y", "x")

    def test_diamond_dependency_graph(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        ids = [s.node_id for s in r.stages]
        assert ids[0] == "a"
        assert ids[-1] == "d"
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")


class TestDependsOn:
    def test_depends_on_from_graph_parents(self) -> None:
        e, planner, g = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        by_id = {s.node_id: s for s in r.stages}
        assert by_id["a"].depends_on == ()
        assert by_id["b"].depends_on == ("a",)
        assert by_id["c"].depends_on == ("a",)
        assert by_id["d"].depends_on == g.parents("d")
        assert set(by_id["d"].depends_on) == {"b", "c"}

    def test_depends_on_empty_when_graph_unwired(self) -> None:
        e, planner, _ = build_engine(with_graph=False)
        m = planner.create_execution_plan(ordered_node_ids=("a", "b", "c"))
        r = e.build_pipeline(m.id)
        assert all(s.depends_on == () for s in r.stages)
        assert len(r.stages) == 3

    def test_unknown_node_in_wired_graph_raises_key_error(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan(ordered_node_ids=("a", "ghost"))
        with pytest.raises(KeyError):
            e.build_pipeline(m.id)
        assert e.count() == 0

    def test_depends_on_is_tuple(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert all(isinstance(s.depends_on, tuple) for s in r.stages)


class TestReadRemoveClear:
    def test_get_pipeline_returns_stored(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id, pipeline_id="p1")
        assert e.get_pipeline("p1") is r

    def test_list_pipelines_returns_all(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id, pipeline_id="p1")
        e.build_pipeline(m.id, pipeline_id="p2")
        assert [p.id for p in e.list_pipelines()] == ["p1", "p2"]

    def test_remove_existing_returns_true(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id, pipeline_id="p1")
        assert e.remove_pipeline("p1") is True
        assert e.get_pipeline("p1") is None
        assert e.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        e, _, _ = build_engine()
        assert e.remove_pipeline("missing") is False

    def test_clear_empties_engine(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id)
        e.build_pipeline(m.id)
        e.clear()
        assert e.count() == 0
        assert len(e) == 0
        assert e.list_pipelines() == ()


class TestInsertionOrder:
    def test_list_preserves_order(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        for pid in ("a", "b", "c"):
            e.build_pipeline(m.id, pipeline_id=pid)
        assert [p.id for p in e.list_pipelines()] == ["a", "b", "c"]

    def test_remove_preserves_relative_order(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        for pid in ("a", "b", "c"):
            e.build_pipeline(m.id, pipeline_id=pid)
        e.remove_pipeline("b")
        assert [p.id for p in e.list_pipelines()] == ["a", "c"]


class TestImmutability:
    def test_record_is_frozen(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.id = "x"  # type: ignore[misc]

    def test_stage_is_frozen(self) -> None:
        s = PipelineStage(index=0, node_id="n")
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.node_id = "x"  # type: ignore[misc]

    def test_stages_is_tuple(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert isinstance(r.stages, tuple)
        assert all(isinstance(s, PipelineStage) for s in r.stages)

    def test_list_returns_tuple(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id)
        assert isinstance(e.list_pipelines(), tuple)

    def test_snapshot_does_not_track_later_builds(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        e.build_pipeline(m.id, pipeline_id="a")
        snap = e.list_pipelines()
        e.build_pipeline(m.id, pipeline_id="b")
        assert len(snap) == 1

    def test_record_survives_later_graph_changes(self) -> None:
        e, planner, g = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        d_before = next(s for s in r.stages if s.node_id == "d").depends_on
        g.disconnect("c", "d")
        d_after = next(s for s in r.stages if s.node_id == "d").depends_on
        assert d_before == d_after
        assert set(d_before) == {"b", "c"}


class TestNoMutationOfCollaborators:
    def test_planner_unchanged_after_build(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        before = planner.list_execution_plans()
        e.build_pipeline(m.id)
        e.build_pipeline(m.id)
        assert planner.list_execution_plans() == before
        assert planner.count() == 1
        assert planner.get_execution_plan(m.id) is m

    def test_graph_unchanged_after_build(self) -> None:
        e, planner, g = build_engine()
        m = planner.create_execution_plan()
        nodes_before = g.list_nodes()
        edges_before = {n.id: g.children(n.id) for n in nodes_before}
        e.build_pipeline(m.id)
        assert g.list_nodes() == nodes_before
        assert {n.id: g.children(n.id) for n in g.list_nodes()} == edges_before
        assert g.count() == 4

    def test_build_failure_leaves_collaborators_unchanged(self) -> None:
        e, planner, g = build_engine()
        m = planner.create_execution_plan(ordered_node_ids=("a", "ghost"))
        with pytest.raises(KeyError):
            e.build_pipeline(m.id)
        assert planner.count() == 1
        assert g.count() == 4


class TestDeterminism:
    def test_repeated_builds_are_identical(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r1 = e.build_pipeline(m.id)
        r2 = e.build_pipeline(m.id)
        assert r1.stages == r2.stages
        assert r1.execution_mapping_reference == r2.execution_mapping_reference

    def test_two_engines_over_equal_inputs_agree(self) -> None:
        e1, p1, _ = build_engine()
        e2, p2, _ = build_engine()
        m1 = p1.create_execution_plan(mapping_id="m")
        m2 = p2.create_execution_plan(mapping_id="m")
        assert e1.build_pipeline(m1.id).stages == e2.build_pipeline(m2.id).stages

    def test_engines_are_independent(self) -> None:
        e1, p1, _ = build_engine()
        e2, _, _ = build_engine()
        m = p1.create_execution_plan()
        e1.build_pipeline(m.id)
        assert e2.count() == 0

    def test_records_are_independent(self) -> None:
        e, planner, _ = build_engine()
        m1 = planner.create_execution_plan(ordered_node_ids=("a",))
        m2 = planner.create_execution_plan(ordered_node_ids=("b", "c"))
        r1 = e.build_pipeline(m1.id)
        r2 = e.build_pipeline(m2.id)
        assert r1.id != r2.id
        assert len(r1.stages) == 1
        assert len(r2.stages) == 2
        e.remove_pipeline(r1.id)
        assert e.get_pipeline(r2.id) is r2


class TestPublicAPISurface:
    def test_exposes_expected_methods(self) -> None:
        e, _, _ = build_engine()
        for name in (
            "build_pipeline", "get_pipeline", "list_pipelines",
            "remove_pipeline", "clear", "count", "__len__",
        ):
            assert callable(getattr(e, name)), name

    def test_no_update_operation(self) -> None:
        e, _, _ = build_engine()
        assert not hasattr(e, "update_pipeline")

    def test_no_forbidden_attributes(self) -> None:
        e, _, _ = build_engine()
        for attr in (
            "memory_engine", "reflection_engine", "ai_service", "agent",
            "router", "registry", "context_manager", "conversation_history",
            "orchestrator", "session", "coordinator", "mark_running",
            "mark_completed", "mark_failed", "next_ready_task",
            "ready_task_ids", "ready_descriptors", "run", "execute",
        ):
            assert not hasattr(e, attr), attr

    def test_record_holds_only_opaque_data(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert isinstance(r.execution_mapping_reference, str)
        assert r.execution_mapping_reference == m.id
        for s in r.stages:
            assert isinstance(s.index, int)
            assert isinstance(s.node_id, str)
            assert all(isinstance(d, str) for d in s.depends_on)

    def test_record_field_names(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(PipelineRecord)) == (
            "id", "execution_mapping_reference", "stages", "created_at", "updated_at",
        )
        assert tuple(f.name for f in dataclasses.fields(PipelineStage)) == (
            "index", "node_id", "depends_on",
        )


class TestArchitecturalIsolation:
    def test_pipeline_engine_imports_only_allowed_modules(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "pipeline_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        allowed_roots = {
            "__future__", "dataclasses", "enum", "threading", "time",
            "typing", "uuid", "collections", "collections.abc",
            "types", "contextlib",
        }
        allowed_full = {"core.execution_planner", "core.task_graph"}
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
            "memory", "os", "sys", "io", "socket", "asyncio",
            "logging", "subprocess", "pathlib", "json", "pickle",
            "http", "urllib", "concurrent",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                root = module.split(".")[0]
                assert root in allowed_roots or module in allowed_full, (
                    f"PipelineEngine must not import {module!r}"
                )
                assert not any(
                    module.startswith(f + ".") or module == f
                    for f in forbidden_roots
                ), f"PipelineEngine must not import {module!r}"
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root in allowed_roots, (
                        f"PipelineEngine must not import {n.name!r}"
                    )
                    assert root not in forbidden_roots, (
                        f"PipelineEngine must not import {n.name!r}"
                    )

    def test_no_async_or_io_constructs(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "pipeline_engine.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            assert not isinstance(
                node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)
            ), "PipelineEngine must not use async constructs"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "exec", "eval"}, (
                    f"PipelineEngine must not call {node.func.id}()"
                )

    def test_legacy_modules_do_not_import_pipeline_engine(self) -> None:
        here = os.path.dirname(__file__)
        core_dir = os.path.normpath(os.path.join(here, "..", "core"))
        legacy = (
            "execution_pipeline.py", "execution_orchestrator.py",
            "execution_session.py", "execution_coordinator.py",
            "execution_result.py", "execution_progress.py",
            "execution_event.py", "planner.py",
        )
        for rel in legacy:
            with open(os.path.join(core_dir, rel), encoding="utf-8") as f:
                assert "pipeline_engine" not in f.read(), rel

    def test_does_not_embed_records(self) -> None:
        e, planner, _ = build_engine()
        m = planner.create_execution_plan()
        r = e.build_pipeline(m.id)
        assert not any(
            dataclasses.is_dataclass(getattr(r, f.name))
            and not isinstance(getattr(r, f.name), tuple)
            for f in dataclasses.fields(r)
        )
        for s in r.stages:
            assert not hasattr(s, "node")
            assert not hasattr(s, "mapping")


class TestCoexistenceWithLegacyExecutionPipeline:
    def test_legacy_execution_pipeline_still_importable(self) -> None:
        from core.execution_pipeline import ExecutionPipeline as LegacyPipeline
        assert LegacyPipeline is not PipelineEngine
        assert LegacyPipeline.__name__ == "ExecutionPipeline"
        assert PipelineEngine.__name__ == "PipelineEngine"

    def test_legacy_descriptor_distinct_from_pipeline_record(self) -> None:
        from core.execution_pipeline import PipelineExecutionDescriptor
        assert PipelineExecutionDescriptor is not PipelineRecord
        assert PipelineExecutionDescriptor is not PipelineStage
