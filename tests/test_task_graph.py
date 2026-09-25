"""Tests for v8.5 Task Graph (Foundation Layer)."""

from __future__ import annotations

import ast
import os

import pytest

from core.task_graph import Node, TaskGraph


def make_node(g, title="t", node_id=None):
    return g.create_node(title=title, node_id=node_id)


class TestEmptyGraph:
    def test_count_is_zero(self) -> None:
        assert TaskGraph().count() == 0

    def test_list_nodes_is_empty(self) -> None:
        assert TaskGraph().list_nodes() == ()

    def test_roots_is_empty(self) -> None:
        assert TaskGraph().roots() == ()

    def test_leaves_is_empty(self) -> None:
        assert TaskGraph().leaves() == ()

    def test_len_is_zero(self) -> None:
        assert len(TaskGraph()) == 0

    def test_get_node_unknown(self) -> None:
        assert TaskGraph().get_node("nope") is None


class TestCreateNode:
    def test_returns_node(self) -> None:
        g = TaskGraph()
        n = g.create_node(title="t")
        assert isinstance(n, Node)
        assert n.title == "t"
        assert n.description == ""
        assert dict(n.metadata) == {}
        assert n.created_at > 0

    def test_id_auto_generated(self) -> None:
        n = TaskGraph().create_node(title="t")
        assert isinstance(n.id, str) and len(n.id) > 0

    def test_explicit_id_preserved(self) -> None:
        n = TaskGraph().create_node(title="t", node_id="n1")
        assert n.id == "n1"

    def test_duplicate_id_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="t", node_id="n1")
        with pytest.raises(ValueError):
            g.create_node(title="t", node_id="n1")

    def test_blank_title_rejected(self) -> None:
        g = TaskGraph()
        with pytest.raises(ValueError):
            g.create_node(title="")
        with pytest.raises(ValueError):
            g.create_node(title="   ")

    def test_invalid_metadata_rejected(self) -> None:
        with pytest.raises(ValueError):
            TaskGraph().create_node(title="t", metadata=["not", "a", "mapping"])


class TestUpdateNode:
    def test_updates_title(self) -> None:
        g = TaskGraph()
        n = g.create_node(title="old", node_id="n1")
        new = g.update_node("n1", title="new")
        assert new.title == "new"
        assert g.get_node("n1").title == "new"

    def test_updates_description(self) -> None:
        g = TaskGraph()
        g.create_node(title="t", node_id="n1")
        new = g.update_node("n1", description="d")
        assert new.description == "d"

    def test_updates_metadata(self) -> None:
        g = TaskGraph()
        g.create_node(title="t", node_id="n1")
        new = g.update_node("n1", metadata={"k": "v"})
        assert dict(new.metadata) == {"k": "v"}

    def test_unknown_id_raises(self) -> None:
        with pytest.raises(KeyError):
            TaskGraph().update_node("missing", title="x")

    def test_blank_title_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="t", node_id="n1")
        with pytest.raises(ValueError):
            g.update_node("n1", title="")

    def test_updated_at_refreshed(self) -> None:
        g = TaskGraph()
        n = g.create_node(title="t", node_id="n1")
        new = g.update_node("n1", title="t2")
        assert new.updated_at >= n.updated_at
        assert new.created_at == n.created_at


class TestRemoveNode:
    def test_remove_existing_returns_true(self) -> None:
        g = TaskGraph()
        g.create_node(title="t", node_id="n1")
        assert g.remove_node("n1") is True
        assert g.count() == 0

    def test_remove_missing_returns_false(self) -> None:
        assert TaskGraph().remove_node("missing") is False

    def test_remove_cleans_up_edges(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        g.create_node(title="c", node_id="c")
        g.create_node(title="g", node_id="g")
        g.connect("p", "c")
        g.connect("c", "g")
        g.remove_node("c")
        assert g.children("p") == ()
        assert g.parents("g") == ()


class TestConnect:
    def test_basic_edge(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        g.create_node(title="c", node_id="c")
        g.connect("p", "c")
        assert g.children("p") == ("c",)
        assert g.parents("c") == ("p",)

    def test_unknown_parent_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="c", node_id="c")
        with pytest.raises(KeyError):
            g.connect("missing", "c")

    def test_unknown_child_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        with pytest.raises(KeyError):
            g.connect("p", "missing")

    def test_self_link_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="n", node_id="n")
        with pytest.raises(ValueError):
            g.connect("n", "n")

    def test_duplicate_edge_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        g.create_node(title="c", node_id="c")
        g.connect("p", "c")
        with pytest.raises(ValueError):
            g.connect("p", "c")


class TestCycleDetection:
    def test_direct_cycle_rejected(self) -> None:
        g = TaskGraph()
        g.create_node(title="a", node_id="a")
        g.create_node(title="b", node_id="b")
        g.connect("a", "b")
        with pytest.raises(ValueError):
            g.connect("b", "a")

    def test_indirect_cycle_rejected(self) -> None:
        g = TaskGraph()
        for nid in ("a", "b", "c"):
            g.create_node(title=nid, node_id=nid)
        g.connect("a", "b")
        g.connect("b", "c")
        with pytest.raises(ValueError):
            g.connect("c", "a")

    def test_deep_cycle_rejected(self) -> None:
        g = TaskGraph()
        for nid in ("a", "b", "c", "d", "e"):
            g.create_node(title=nid, node_id=nid)
        g.connect("a", "b")
        g.connect("b", "c")
        g.connect("c", "d")
        g.connect("d", "e")
        with pytest.raises(ValueError):
            g.connect("e", "a")


class TestDisconnect:
    def test_disconnect_existing_edge(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        g.create_node(title="c", node_id="c")
        g.connect("p", "c")
        assert g.disconnect("p", "c") is True
        assert g.children("p") == ()
        assert g.parents("c") == ()

    def test_disconnect_missing_edge(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        g.create_node(title="c", node_id="c")
        assert g.disconnect("p", "c") is False

    def test_disconnect_unknown_node(self) -> None:
        assert TaskGraph().disconnect("a", "b") is False


class TestParentsAndChildren:
    def test_children_of_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            TaskGraph().children("missing")

    def test_parents_of_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            TaskGraph().parents("missing")

    def test_multiple_children_preserve_order(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        for nid in ("c1", "c2", "c3"):
            g.create_node(title=nid, node_id=nid)
            g.connect("p", nid)
        assert g.children("p") == ("c1", "c2", "c3")

    def test_multiple_parents_preserve_order(self) -> None:
        g = TaskGraph()
        for nid in ("p1", "p2", "p3"):
            g.create_node(title=nid, node_id=nid)
        g.create_node(title="c", node_id="c")
        for pid in ("p1", "p2", "p3"):
            g.connect(pid, "c")
        assert g.parents("c") == ("p1", "p2", "p3")


class TestRootsAndLeaves:
    def test_roots(self) -> None:
        g = TaskGraph()
        g.create_node(title="a", node_id="a")
        g.create_node(title="b", node_id="b")
        g.create_node(title="c", node_id="c")
        g.connect("a", "b")
        # a is root, b has parent, c is isolated → also a root.
        assert [n.id for n in g.roots()] == ["a", "c"]

    def test_leaves(self) -> None:
        g = TaskGraph()
        g.create_node(title="a", node_id="a")
        g.create_node(title="b", node_id="b")
        g.create_node(title="c", node_id="c")
        g.connect("a", "b")
        # b is leaf; c is isolated → also a leaf.
        assert [n.id for n in g.leaves()] == ["b", "c"]


class TestInsertionOrder:
    def test_list_nodes_preserves_order(self) -> None:
        g = TaskGraph()
        for nid in ("a", "b", "c", "d"):
            g.create_node(title=nid, node_id=nid)
        assert [n.id for n in g.list_nodes()] == ["a", "b", "c", "d"]


class TestClear:
    def test_clear_empties_graph(self) -> None:
        g = TaskGraph()
        g.create_node(title="a", node_id="a")
        g.create_node(title="b", node_id="b")
        g.connect("a", "b")
        g.clear()
        assert g.count() == 0
        assert g.list_nodes() == ()
        assert g.roots() == ()
        assert g.leaves() == ()


class TestImmutableSnapshots:
    def test_node_is_frozen(self) -> None:
        n = TaskGraph().create_node(title="t")
        with pytest.raises(Exception):
            n.title = "x"  # type: ignore[misc]

    def test_list_nodes_returns_tuple(self) -> None:
        g = TaskGraph()
        g.create_node(title="t")
        assert isinstance(g.list_nodes(), tuple)

    def test_children_returns_tuple(self) -> None:
        g = TaskGraph()
        g.create_node(title="p", node_id="p")
        assert isinstance(g.children("p"), tuple)

    def test_parents_returns_tuple(self) -> None:
        g = TaskGraph()
        g.create_node(title="c", node_id="c")
        assert isinstance(g.parents("c"), tuple)

    def test_roots_returns_tuple(self) -> None:
        g = TaskGraph()
        g.create_node(title="t")
        assert isinstance(g.roots(), tuple)

    def test_leaves_returns_tuple(self) -> None:
        g = TaskGraph()
        g.create_node(title="t")
        assert isinstance(g.leaves(), tuple)

    def test_snapshot_does_not_track_later_inserts(self) -> None:
        g = TaskGraph()
        g.create_node(title="a", node_id="a")
        snap = g.list_nodes()
        g.create_node(title="b", node_id="b")
        assert len(snap) == 1


class TestDeterministicBehavior:
    def test_two_graphs_are_independent(self) -> None:
        a, b = TaskGraph(), TaskGraph()
        a.create_node(title="x")
        assert b.count() == 0

    def test_get_node_returns_same_value(self) -> None:
        g = TaskGraph()
        n = g.create_node(title="t", node_id="n1")
        assert g.get_node("n1") is n


class TestPublicAPISurface:
    def test_engine_exposes_expected_methods(self) -> None:
        g = TaskGraph()
        for name in (
            "create_node", "update_node", "remove_node",
            "connect", "disconnect", "children", "parents",
            "roots", "leaves", "get_node", "list_nodes",
            "clear", "count",
        ):
            assert callable(getattr(g, name)), name

    def test_no_forbidden_attributes(self) -> None:
        g = TaskGraph()
        for attr in (
            "memory_engine", "reflection_engine", "planning_engine",
            "ai_service", "agent", "router", "registry", "engine",
            "context_manager",
        ):
            assert not hasattr(g, attr), attr


class TestArchitecturalIsolation:
    def test_task_graph_imports_only_stdlib(self) -> None:
        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "task_graph.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        allowed_roots = {
            "__future__", "dataclasses", "enum", "threading", "time",
            "typing", "uuid", "collections.abc", "types", "contextlib",
        }
        forbidden_roots = {"core", "memory"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root in allowed_roots, (
                    f"TaskGraph must not import {node.module!r}"
                )
                assert root not in forbidden_roots
            elif isinstance(node, ast.Import):
                for n in node.names:
                    root = n.name.split(".")[0]
                    assert root not in forbidden_roots, (
                        f"TaskGraph must not import {n.name}"
                    )

    def test_task_graph_does_not_reference_forbidden_modules(self) -> None:
        import ast as _ast

        here = os.path.dirname(__file__)
        mod_path = os.path.normpath(
            os.path.join(here, "..", "core", "task_graph.py")
        )
        with open(mod_path, encoding="utf-8") as f:
            tree = _ast.parse(f.read())
        forbidden = (
            "core.agent", "core.ai_service", "core.ai_provider",
            "core.ai_conversation_engine", "core.ai_provider_router",
            "core.context_manager", "core.conversation_history",
            "core.memory_engine", "core.reflection_engine",
            "core.problem_solver", "core.planner", "core.planning_engine",
            "core.skill_dispatch", "core.skill_registry",
        )
        for node in _ast.walk(tree):
            target = None
            if isinstance(node, _ast.ImportFrom) and node.module:
                target = node.module
            elif isinstance(node, _ast.Import):
                for n in node.names:
                    for f in forbidden:
                        assert not n.name.startswith(f), (
                            f"task_graph.py must not import {n.name}"
                        )
                continue
            if target is not None:
                for f in forbidden:
                    assert not target.startswith(f), (
                        f"task_graph.py must not import {target}"
                    )