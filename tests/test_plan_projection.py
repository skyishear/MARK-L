"""Tests for v8.21 Legacy Plan → Foundation Projection Adapter."""

from __future__ import annotations

import ast
import dataclasses
import os
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

import core.plan_projection as projection_module
from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager
from core.pipeline_engine import PipelineEngine
from core.plan_projection import PlanProjection, project_execution_plan
from core.planner import ExecutionPlan, Goal, PlanningEngine as LegacyPlanningEngine, Task
from core.planning_engine import PlanningEngine, PlanStatus
from core.task_graph import TaskGraph

HERE = os.path.dirname(__file__)
CORE_DIR = os.path.normpath(os.path.join(HERE, "..", "core"))
MODULE_PATH = os.path.join(CORE_DIR, "plan_projection.py")


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


# ── fixtures ────────────────────────────────────────────────────────────


class Stores:
    def __init__(self) -> None:
        self.goal_manager = GoalManager()
        self.planning_engine = PlanningEngine()
        self.task_graph = TaskGraph()
        self.execution_planner = ExecutionPlanner(
            goal_manager=self.goal_manager,
            planning_engine=self.planning_engine,
            task_graph=self.task_graph,
        )
        self.pipeline_engine = PipelineEngine(self.execution_planner, task_graph=self.task_graph)

    def kwargs(self) -> dict:
        return {
            "goal_manager": self.goal_manager,
            "planning_engine": self.planning_engine,
            "task_graph": self.task_graph,
            "execution_planner": self.execution_planner,
            "pipeline_engine": self.pipeline_engine,
        }

    def project(self, plan: ExecutionPlan) -> PlanProjection:
        return project_execution_plan(plan, **self.kwargs())


def make_plan(*tasks: tuple[str, tuple[str, ...]], goal: str = "the goal", plan_id: str = "legacy-plan") -> ExecutionPlan:
    now = datetime.now(timezone.utc)
    return ExecutionPlan(
        id=plan_id,
        goal=Goal(id="legacy-goal", description=goal, created_at=now),
        tasks=tuple(Task(id=tid, description=f"do {tid}", depends_on=deps, metadata={}) for tid, deps in tasks),
        created_at=now,
    )


def linear(n: int = 3) -> ExecutionPlan:
    return make_plan(*((f"t{i}", (f"t{i-1}",) if i > 1 else ()) for i in range(1, n + 1)))


def diamond() -> ExecutionPlan:
    return make_plan(("a", ()), ("b", ("a",)), ("c", ("a",)), ("d", ("b", "c")))


def legacy_plan(goal: str = "step one then step two then step three") -> ExecutionPlan:
    return LegacyPlanningEngine().plan(goal)


# ── A. Basic projection ─────────────────────────────────────────────────


class TestBasicProjection:
    def test_one_task(self) -> None:
        s = Stores()
        p = s.project(make_plan(("t1", ())))
        assert isinstance(p, PlanProjection)
        assert len(p.step_ids) == len(p.node_ids) == 1
        assert s.goal_manager.count() == s.planning_engine.count() == 1
        assert s.task_graph.count() == 1
        assert s.execution_planner.count() == s.pipeline_engine.count() == 1

    def test_multiple_tasks_counts(self) -> None:
        s = Stores()
        p = s.project(linear(4))
        assert len(p.step_ids) == len(p.node_ids) == 4
        assert s.task_graph.count() == 4
        assert len(s.pipeline_engine.get_pipeline(p.pipeline_id).stages) == 4

    def test_linear_chain_edges(self) -> None:
        s = Stores()
        p = s.project(linear(3))
        n = p.task_to_node
        assert s.task_graph.parents(n["t1"]) == ()
        assert s.task_graph.parents(n["t2"]) == (n["t1"],)
        assert s.task_graph.parents(n["t3"]) == (n["t2"],)

    def test_arbitrary_dag(self) -> None:
        s = Stores()
        plan = make_plan(("a", ()), ("b", ()), ("c", ("a", "b")), ("d", ("a",)), ("e", ("c", "d")))
        p = s.project(plan)
        n = p.task_to_node
        assert set(s.task_graph.parents(n["c"])) == {n["a"], n["b"]}
        assert s.task_graph.parents(n["d"]) == (n["a"],)
        assert set(s.task_graph.parents(n["e"])) == {n["c"], n["d"]}
        assert set(s.task_graph.children(n["a"])) == {n["c"], n["d"]}

    def test_diamond(self) -> None:
        s = Stores()
        p = s.project(diamond())
        n = p.task_to_node
        assert set(s.task_graph.parents(n["d"])) == {n["b"], n["c"]}
        assert s.task_graph.parents(n["b"]) == s.task_graph.parents(n["c"]) == (n["a"],)
        assert [x.id for x in s.task_graph.roots()] == [n["a"]]
        assert [x.id for x in s.task_graph.leaves()] == [n["d"]]

    def test_deterministic_structure_across_stores(self) -> None:
        s1, s2 = Stores(), Stores()
        p1, p2 = s1.project(diamond()), s2.project(diamond())
        assert p1.step_ids == p2.step_ids
        assert len(p1.node_ids) == len(p2.node_ids)
        st1 = [x.node_id for x in s1.pipeline_engine.get_pipeline(p1.pipeline_id).stages]
        st2 = [x.node_id for x in s2.pipeline_engine.get_pipeline(p2.pipeline_id).stages]
        # node ids differ (fresh) but the legacy task sequence behind them matches.
        back1 = [s1.task_graph.get_node(n).metadata["task_id"] for n in st1]
        back2 = [s2.task_graph.get_node(n).metadata["task_id"] for n in st2]
        assert back1 == back2 == ["a", "b", "c", "d"]

    def test_real_legacy_planner_plan(self) -> None:
        s = Stores()
        plan = legacy_plan()
        p = s.project(plan)
        assert p.step_ids == tuple(t.id for t in plan.tasks)
        stages = s.pipeline_engine.get_pipeline(p.pipeline_id).stages
        assert [s.task_graph.get_node(st.node_id).metadata["task_id"] for st in stages] == [t.id for t in plan.execution_order()]


# ── B. IDs ──────────────────────────────────────────────────────────────


class TestIds:
    def test_fresh_ids_not_legacy(self) -> None:
        s = Stores()
        plan = legacy_plan()
        p = s.project(plan)
        assert p.goal_id != plan.goal.id
        assert p.plan_id != plan.id
        assert p.mapping_id != plan.id
        assert p.pipeline_id != plan.id
        for task in plan.tasks:
            assert p.task_to_node[task.id] != task.id
        legacy_ids = {plan.id, plan.goal.id, *(t.id for t in plan.tasks)}
        assert not legacy_ids & {p.goal_id, p.plan_id, p.mapping_id, p.pipeline_id, *p.node_ids}

    def test_task_id_reused_only_as_step_id(self) -> None:
        s = Stores()
        plan = linear(3)
        p = s.project(plan)
        steps = s.planning_engine.get_plan(p.plan_id).steps
        assert [st.id for st in steps] == [t.id for t in plan.tasks] == list(p.step_ids)
        assert all(nid not in {t.id for t in plan.tasks} for nid in p.node_ids)

    def test_task_to_node_correct(self) -> None:
        s = Stores()
        plan = linear(3)
        p = s.project(plan)
        assert set(p.task_to_node) == {t.id for t in plan.tasks}
        assert tuple(p.task_to_node[t.id] for t in plan.tasks) == p.node_ids
        for tid, nid in p.task_to_node.items():
            assert s.task_graph.get_node(nid).metadata["task_id"] == tid

    def test_task_to_node_read_only(self) -> None:
        p = Stores().project(linear(2))
        assert isinstance(p.task_to_node, MappingProxyType)
        with pytest.raises(TypeError):
            p.task_to_node["x"] = "y"  # type: ignore[index]

    def test_ids_are_the_stores_ids(self) -> None:
        s = Stores()
        p = s.project(linear(2))
        assert s.goal_manager.get_goal(p.goal_id) is not None
        assert s.planning_engine.get_plan(p.plan_id) is not None
        assert s.execution_planner.get_execution_plan(p.mapping_id) is not None
        assert s.pipeline_engine.get_pipeline(p.pipeline_id) is not None
        assert all(s.task_graph.get_node(n) is not None for n in p.node_ids)


# ── C. Traceability ─────────────────────────────────────────────────────


class TestTraceability:
    def test_node_metadata(self) -> None:
        s = Stores()
        plan = linear(2)
        p = s.project(plan)
        for task in plan.tasks:
            node = s.task_graph.get_node(p.task_to_node[task.id])
            assert dict(node.metadata) == {"task_id": task.id, "plan_id": plan.id}
            assert node.title == task.description

    def test_mapping_metadata(self) -> None:
        s = Stores()
        plan = linear(2)
        p = s.project(plan)
        m = s.execution_planner.get_execution_plan(p.mapping_id)
        assert dict(m.metadata) == {"legacy_plan_id": plan.id, "legacy_goal_id": plan.goal.id}
        assert m.goal_reference == p.goal_id
        assert m.plan_reference == p.plan_id
        assert m.graph_reference == p.plan_id

    def test_goal_record(self) -> None:
        s = Stores()
        plan = linear(1)
        p = s.project(plan)
        g = s.goal_manager.get_goal(p.goal_id)
        assert g.title == plan.goal.description
        assert g.tags == (plan.goal.id,)
        assert g.plan_reference == p.plan_id
        assert g.graph_reference == p.plan_id

    def test_graph_reference_is_projected_plan_id(self) -> None:
        p = Stores().project(linear(1))
        assert p.graph_reference == p.plan_id

    def test_foundation_plan_content(self) -> None:
        s = Stores()
        plan = linear(3)
        p = s.project(plan)
        fp = s.planning_engine.get_plan(p.plan_id)
        assert fp.goal == plan.goal.description
        assert fp.status is PlanStatus.DRAFT
        assert [(st.index, st.title, st.status) for st in fp.steps] == [
            (i, t.description, PlanStatus.DRAFT) for i, t in enumerate(plan.tasks)
        ]


# ── D. Execution order ──────────────────────────────────────────────────


class TestExecutionOrder:
    def test_explicit_ordered_node_ids_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = Stores()
        seen: dict = {}
        original = s.execution_planner.create_execution_plan

        def spy(**kwargs):
            seen.update(kwargs)
            return original(**kwargs)

        monkeypatch.setattr(s.execution_planner, "create_execution_plan", spy)
        p = s.project(diamond())
        assert seen["ordered_node_ids"] is not None
        assert tuple(seen["ordered_node_ids"]) == s.execution_planner.execution_order(p.mapping_id)

    def test_stage_order_matches_legacy_execution_order(self) -> None:
        s = Stores()
        plan = diamond()
        p = s.project(plan)
        stages = s.pipeline_engine.get_pipeline(p.pipeline_id).stages
        expected = [p.task_to_node[t.id] for t in plan.execution_order()]
        assert [st.node_id for st in stages] == expected
        assert [st.index for st in stages] == list(range(4))

    def test_stage_depends_on_from_graph(self) -> None:
        s = Stores()
        p = s.project(diamond())
        n = p.task_to_node
        by_node = {st.node_id: st for st in s.pipeline_engine.get_pipeline(p.pipeline_id).stages}
        assert by_node[n["a"]].depends_on == ()
        assert set(by_node[n["d"]].depends_on) == {n["b"], n["c"]}

    def test_unrelated_graph_nodes_do_not_leak(self) -> None:
        s = Stores()
        s.task_graph.create_node(title="pre-existing", node_id="stranger")
        s.project(linear(2))  # unrelated earlier projection
        plan = make_plan(("x", ()), ("y", ("x",)), plan_id="second")
        p = s.project(plan)
        order = s.execution_planner.execution_order(p.mapping_id)
        assert order == tuple(p.node_ids)
        assert "stranger" not in order
        stages = s.pipeline_engine.get_pipeline(p.pipeline_id).stages
        assert [st.node_id for st in stages] == list(p.node_ids)
        assert s.task_graph.count() == 1 + 2 + 2


# ── E. Dependencies ─────────────────────────────────────────────────────


class TestDependencies:
    def test_every_depends_on_becomes_edge(self) -> None:
        s = Stores()
        plan = diamond()
        p = s.project(plan)
        for task in plan.tasks:
            assert set(s.task_graph.parents(p.task_to_node[task.id])) == {p.task_to_node[d] for d in task.depends_on}

    def test_edge_direction_parent_to_child(self) -> None:
        s = Stores()
        p = s.project(linear(2))
        n = p.task_to_node
        assert s.task_graph.children(n["t1"]) == (n["t2"],)
        assert s.task_graph.children(n["t2"]) == ()

    def test_unknown_dependency_rejected_before_writes(self) -> None:
        # ExecutionPlan validates this itself; construct a plan that bypasses
        # __post_init__ to prove the adapter's own pre-flight also rejects it.
        s = Stores()
        plan = linear(1)
        bad_task = Task(id="t2", description="do t2", depends_on=("ghost",), metadata={})
        object.__setattr__(plan, "tasks", (plan.tasks[0], bad_task))
        with pytest.raises(ValueError, match="unknown task"):
            s.project(plan)
        assert s.planning_engine.count() == 0 and s.task_graph.count() == 0


# ── F. Empty plan ───────────────────────────────────────────────────────


class TestEmptyPlan:
    def test_empty_plan_projects(self) -> None:
        s = Stores()
        p = s.project(make_plan())
        assert p.step_ids == () and p.node_ids == () and dict(p.task_to_node) == {}
        assert s.planning_engine.get_plan(p.plan_id).steps == ()
        assert s.task_graph.count() == 0
        assert s.execution_planner.execution_order(p.mapping_id) == ()
        assert s.pipeline_engine.get_pipeline(p.pipeline_id).stages == ()
        assert s.goal_manager.get_goal(p.goal_id).tags == ("legacy-goal",)


# ── G. Re-projection ────────────────────────────────────────────────────


class TestReprojection:
    def test_same_plan_twice_creates_independent_records(self) -> None:
        s = Stores()
        plan = legacy_plan()
        p1 = s.project(plan)
        p2 = s.project(plan)
        assert p1.goal_id != p2.goal_id
        assert p1.plan_id != p2.plan_id
        assert p1.mapping_id != p2.mapping_id
        assert p1.pipeline_id != p2.pipeline_id
        assert not set(p1.node_ids) & set(p2.node_ids)
        assert p1.step_ids == p2.step_ids  # plan-scoped reuse is fine
        assert s.goal_manager.count() == 2
        assert s.task_graph.count() == 2 * len(plan.tasks)

    def test_reprojection_traceability_intact(self) -> None:
        s = Stores()
        plan = linear(2)
        p1, p2 = s.project(plan), s.project(plan)
        for p in (p1, p2):
            for tid, nid in p.task_to_node.items():
                assert s.task_graph.get_node(nid).metadata == {"task_id": tid, "plan_id": plan.id}
            assert s.goal_manager.get_goal(p.goal_id).tags == (plan.goal.id,)

    def test_reprojection_order_isolated(self) -> None:
        s = Stores()
        plan = diamond()
        p1, p2 = s.project(plan), s.project(plan)
        assert s.execution_planner.execution_order(p1.mapping_id) == tuple(p1.task_to_node[t.id] for t in plan.execution_order())
        assert s.execution_planner.execution_order(p2.mapping_id) == tuple(p2.task_to_node[t.id] for t in plan.execution_order())


# ── H. Failure / atomicity ──────────────────────────────────────────────


class TestPreflightAndAtomicity:
    def test_non_plan_rejected_before_writes(self) -> None:
        s = Stores()
        with pytest.raises(TypeError):
            s.project("not a plan")  # type: ignore[arg-type]
        assert s.goal_manager.count() == s.planning_engine.count() == s.task_graph.count() == 0

    def test_blank_goal_rejected_before_writes(self) -> None:
        s = Stores()
        plan = make_plan(("t1", ()))
        object.__setattr__(plan.goal, "description", "   ")
        with pytest.raises(ValueError, match="goal.description"):
            s.project(plan)
        assert s.planning_engine.count() == 0

    def test_blank_task_description_rejected_before_writes(self) -> None:
        s = Stores()
        plan = make_plan(("t1", ()))
        object.__setattr__(plan.tasks[0], "description", "")
        with pytest.raises(ValueError, match="non-empty description"):
            s.project(plan)
        assert s.planning_engine.count() == 0 and s.task_graph.count() == 0

    def test_wrong_store_types_rejected(self) -> None:
        s = Stores()
        for key in ("goal_manager", "planning_engine", "task_graph", "execution_planner", "pipeline_engine"):
            kwargs = s.kwargs()
            kwargs[key] = object()
            with pytest.raises(TypeError):
                project_execution_plan(linear(1), **kwargs)
        assert s.planning_engine.count() == 0

    def test_downstream_exception_propagates_no_rollback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = Stores()

        def boom(**kwargs):
            raise RuntimeError("store failure")

        monkeypatch.setattr(s.execution_planner, "create_execution_plan", boom)
        with pytest.raises(RuntimeError, match="store failure"):
            s.project(linear(2))
        # Non-atomic: earlier writes remain, no rollback exists.
        assert s.planning_engine.count() == 1
        assert s.task_graph.count() == 2
        assert s.goal_manager.count() == 1
        assert s.execution_planner.count() == 0
        assert s.pipeline_engine.count() == 0

    def test_no_rollback_or_transaction_code(self) -> None:
        names = {n.id for n in ast.walk(_tree()) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)
        }
        for forbidden in ("remove_goal", "remove_plan", "remove_node", "remove_execution_plan",
                          "remove_pipeline", "clear", "rollback", "transaction", "disconnect"):
            assert forbidden not in names, forbidden
        for n in ast.walk(_tree()):
            assert not isinstance(n, (ast.Try, ast.ExceptHandler))


# ── I. Dependency injection ─────────────────────────────────────────────


class TestInjection:
    def test_exact_instances_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        s = Stores()
        touched: list[str] = []
        for name in ("goal_manager", "planning_engine", "task_graph", "execution_planner", "pipeline_engine"):
            store = getattr(s, name)
            method = {"goal_manager": "create_goal", "planning_engine": "create_plan",
                      "task_graph": "create_node", "execution_planner": "create_execution_plan",
                      "pipeline_engine": "build_pipeline"}[name]
            original = getattr(store, method)

            def wrapped(*a, _n=name, _o=original, **k):
                touched.append(_n)
                return _o(*a, **k)

            monkeypatch.setattr(store, method, wrapped)
        s.project(linear(1))
        assert touched == ["planning_engine", "task_graph", "goal_manager", "execution_planner", "pipeline_engine"]

    def test_planner_wired_elsewhere_fails_loudly(self) -> None:
        s = Stores()
        other = ExecutionPlanner(goal_manager=GoalManager(), planning_engine=s.planning_engine, task_graph=s.task_graph)
        kwargs = s.kwargs()
        kwargs["execution_planner"] = other
        kwargs["pipeline_engine"] = PipelineEngine(other, task_graph=s.task_graph)
        with pytest.raises(ValueError, match="execution_planner.goal_manager"):
            project_execution_plan(linear(1), **kwargs)
        assert s.planning_engine.count() == 0

    def test_pipeline_engine_wired_elsewhere_fails_loudly(self) -> None:
        s = Stores()
        kwargs = s.kwargs()
        kwargs["pipeline_engine"] = PipelineEngine(ExecutionPlanner(), task_graph=s.task_graph)
        with pytest.raises(ValueError, match="pipeline_engine.execution_planner"):
            project_execution_plan(linear(1), **kwargs)

    def test_pipeline_engine_without_graph_rejected(self) -> None:
        s = Stores()
        kwargs = s.kwargs()
        kwargs["pipeline_engine"] = PipelineEngine(s.execution_planner)
        with pytest.raises(ValueError, match="wired to a TaskGraph"):
            project_execution_plan(linear(1), **kwargs)

    def test_pipeline_engine_other_graph_rejected(self) -> None:
        s = Stores()
        kwargs = s.kwargs()
        kwargs["pipeline_engine"] = PipelineEngine(s.execution_planner, task_graph=TaskGraph())
        with pytest.raises(ValueError, match="pipeline_engine.task_graph"):
            project_execution_plan(linear(1), **kwargs)

    def test_unwired_planner_allowed(self) -> None:
        # ExecutionPlanner with no collaborators performs no validation; the
        # adapter still supplies explicit order so projection succeeds.
        s = Stores()
        planner = ExecutionPlanner()
        engine = PipelineEngine(planner, task_graph=s.task_graph)
        kwargs = s.kwargs()
        kwargs["execution_planner"], kwargs["pipeline_engine"] = planner, engine
        p = project_execution_plan(diamond(), **kwargs)
        assert planner.execution_order(p.mapping_id) == tuple(p.task_to_node[t.id] for t in diamond().execution_order())

    def test_stores_are_keyword_only(self) -> None:
        import inspect
        params = inspect.signature(project_execution_plan).parameters
        assert [p.kind for p in list(params.values())[1:]] == [inspect.Parameter.KEYWORD_ONLY] * 5


# ── Record / API / architecture ─────────────────────────────────────────


class TestRecordAndArchitecture:
    def test_projection_frozen_slots(self) -> None:
        p = Stores().project(linear(1))
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.goal_id = "x"  # type: ignore[misc]
        assert not hasattr(p, "__dict__")

    def test_projection_fields_exact(self) -> None:
        assert tuple(f.name for f in dataclasses.fields(PlanProjection)) == (
            "goal_id", "plan_id", "graph_reference", "mapping_id", "pipeline_id",
            "step_ids", "node_ids", "task_to_node",
        )

    def test_projection_holds_only_ids(self) -> None:
        p = Stores().project(linear(2))
        for f in dataclasses.fields(p):
            v = getattr(p, f.name)
            assert isinstance(v, (str, tuple, MappingProxyType)), f.name
            assert not dataclasses.is_dataclass(v)

    def test_all_exact(self) -> None:
        assert projection_module.__all__ == ["PlanProjection", "project_execution_plan"]

    def test_import_allowlist(self) -> None:
        allowed_roots = {"__future__", "dataclasses", "types", "typing"}
        allowed_full = {
            "core.planner", "core.goal_manager", "core.planning_engine",
            "core.task_graph", "core.execution_planner", "core.pipeline_engine",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] in allowed_roots or node.module in allowed_full, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] in allowed_roots, n.name

    def test_forbidden_imports(self) -> None:
        forbidden = {
            "core.agent", "core.pipeline_run", "core.tool_interface", "core.tool_registry",
            "core.tool_router", "core.tool_dispatch", "core.skill_tool_adapter",
            "core.skill_registry", "core.skill_dispatch", "core.ai_service", "core.ai_provider",
            "core.memory_engine", "core.reflection_engine", "core.execution_pipeline",
            "core.execution_orchestrator", "core.execution_session", "core.execution_coordinator",
            "core.execution_result", "core.problem_solver", "os", "sys", "io", "socket",
            "asyncio", "threading", "subprocess", "logging", "pathlib", "json", "time", "uuid",
        }
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden and node.module.split(".")[0] not in forbidden, node.module
            elif isinstance(node, ast.Import):
                for n in node.names:
                    assert n.name.split(".")[0] not in forbidden, n.name

    def test_no_forbidden_runtime_identifiers(self) -> None:
        forbidden = {"create_run", "update_run", "mark_running", "mark_completed", "mark_failed",
                     "route", "invoke", "dispatch", "plan"}
        # ``plan`` appears only as a variable/parameter name, never as a call.
        for node in ast.walk(_tree()):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                assert name not in forbidden, name

    def test_no_async_io_or_module_state(self) -> None:
        for node in ast.walk(_tree()):
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "exec", "eval", "input"}
        for node in _tree().body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                           if isinstance(node, ast.Assign)
                           else [node.target.id] if isinstance(node.target, ast.Name) else [])
                assert targets == ["__all__"], targets

    def test_no_core_module_imports_projection_except_agent(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "plan_projection.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "plan_projection" not in f.read(), name

    def test_legacy_planner_untouched_and_read_only(self) -> None:
        # The adapter never calls a mutating/planning API on core.planner objects.
        used = {n.attr for n in ast.walk(_tree()) if isinstance(n, ast.Attribute)}
        assert "plan" not in {n.func.attr for n in ast.walk(_tree()) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert {"tasks", "id", "goal", "description", "depends_on", "execution_order"} <= used
