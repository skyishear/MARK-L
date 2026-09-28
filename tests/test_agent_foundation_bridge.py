"""Tests for v8.10 Foundation → Agent Bridge."""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys

import pytest

import core.agent as agent_module
from core.agent import Agent
from core.execution_orchestrator import ExecutionOrchestrator
from core.execution_pipeline import ExecutionPipeline
from core.execution_planner import ExecutionPlanner
from core.goal_manager import GoalManager
from core.pipeline_engine import PipelineEngine
from core.pipeline_run import PipelineRunManager
from core.planner import PlanningEngine as LegacyPlanningEngine
from core.planning_engine import PlanningEngine as FoundationPlanningEngine
from core.task_graph import TaskGraph

FOUNDATION_PARAMS = (
    "goal_manager", "planning_engine", "task_graph",
    "execution_planner", "pipeline_engine", "pipeline_run_manager",
)
FOUNDATION_TYPES = {
    "goal_manager": GoalManager,
    "planning_engine": FoundationPlanningEngine,
    "task_graph": TaskGraph,
    "execution_planner": ExecutionPlanner,
    "pipeline_engine": PipelineEngine,
    "pipeline_run_manager": PipelineRunManager,
}
V8_MODULES = {
    "core.goal_manager", "core.planning_engine", "core.task_graph",
    "core.execution_planner", "core.pipeline_engine", "core.pipeline_run",
}
LEGACY_EXECUTION_FILES = (
    "execution_pipeline.py", "execution_orchestrator.py",
    "execution_session.py", "execution_coordinator.py",
    "execution_result.py", "execution_progress.py",
    "execution_event.py", "planner.py",
)

HERE = os.path.dirname(__file__)
CORE_DIR = os.path.normpath(os.path.join(HERE, "..", "core"))
AGENT_FILE = os.path.join(CORE_DIR, "agent", "__init__.py")


def _agent_tree() -> ast.AST:
    with open(AGENT_FILE, encoding="utf-8") as f:
        return ast.parse(f.read())


def _agent_imported_modules() -> set[str]:
    return {
        node.module
        for node in ast.walk(_agent_tree())
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    }


class TestDefaultComposition:
    def test_agent_creates_all_six(self) -> None:
        a = Agent()
        for name, typ in FOUNDATION_TYPES.items():
            assert isinstance(getattr(a, name), typ), name

    def test_fresh_per_agent(self) -> None:
        a, b = Agent(), Agent()
        for name in FOUNDATION_PARAMS:
            assert getattr(a, name) is not getattr(b, name), name

    def test_all_six_params_default_to_none(self) -> None:
        params = inspect.signature(Agent.__init__).parameters
        for name in FOUNDATION_PARAMS:
            assert name in params, name
            assert params[name].default is None, name
            assert params[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    def test_six_params_appended_after_existing(self) -> None:
        names = list(inspect.signature(Agent.__init__).parameters)
        # v8.10 six are contiguous and directly follow the v7.x params;
        # later milestones (v8.15 tool bridge) append after them.
        start = names.index("goal_manager")
        assert names[start:start + 6] == list(FOUNDATION_PARAMS)
        assert names.index("reflection_engine") < names.index("goal_manager")


class TestWiring:
    def test_execution_planner_wired_to_agent_stores(self) -> None:
        a = Agent()
        assert a.execution_planner.goal_manager is a.goal_manager
        assert a.execution_planner.planning_engine is a.planning_engine
        assert a.execution_planner.task_graph is a.task_graph

    def test_pipeline_engine_wired_to_agent_stores(self) -> None:
        a = Agent()
        assert a.pipeline_engine.execution_planner is a.execution_planner
        assert a.pipeline_engine.task_graph is a.task_graph

    def test_pipeline_run_manager_wired_to_pipeline_engine(self) -> None:
        a = Agent()
        assert a.pipeline_run_manager.pipeline_engine is a.pipeline_engine

    def test_wiring_end_to_end_through_agent(self) -> None:
        a = Agent()
        a.task_graph.create_node(title="n", node_id="n1")
        m = a.execution_planner.create_execution_plan()
        assert m.ordered_node_ids == ("n1",)
        p = a.pipeline_engine.build_pipeline(m.id)
        assert [s.node_id for s in p.stages] == ["n1"]
        r = a.pipeline_run_manager.create_run(p.id)
        assert r.pipeline_reference == p.id


class TestInjection:
    def test_injected_instances_used_verbatim(self) -> None:
        gm, pe, tg = GoalManager(), FoundationPlanningEngine(), TaskGraph()
        ep = ExecutionPlanner(goal_manager=gm, planning_engine=pe, task_graph=tg)
        pipe = PipelineEngine(ep, task_graph=tg)
        prm = PipelineRunManager(pipe)
        a = Agent(
            goal_manager=gm, planning_engine=pe, task_graph=tg,
            execution_planner=ep, pipeline_engine=pipe, pipeline_run_manager=prm,
        )
        assert a.goal_manager is gm
        assert a.planning_engine is pe
        assert a.task_graph is tg
        assert a.execution_planner is ep
        assert a.pipeline_engine is pipe
        assert a.pipeline_run_manager is prm

    def test_injected_leaf_stores_propagate_into_defaults(self) -> None:
        gm, pe, tg = GoalManager(), FoundationPlanningEngine(), TaskGraph()
        a = Agent(goal_manager=gm, planning_engine=pe, task_graph=tg)
        assert a.execution_planner.goal_manager is gm
        assert a.execution_planner.planning_engine is pe
        assert a.execution_planner.task_graph is tg
        assert a.pipeline_engine.task_graph is tg

    def test_partial_injection_does_not_reconcile(self) -> None:
        own_graph = TaskGraph()
        ep = ExecutionPlanner(task_graph=own_graph)
        a = Agent(execution_planner=ep)
        # Injected planner keeps its own collaborators.
        assert a.execution_planner is ep
        assert a.execution_planner.task_graph is own_graph
        assert a.execution_planner.goal_manager is None
        # Agent's task_graph is independently resolved, not rewritten.
        assert isinstance(a.task_graph, TaskGraph)
        assert a.task_graph is not own_graph
        # Downstream defaults use Agent's resolved siblings as specified.
        assert a.pipeline_engine.execution_planner is ep
        assert a.pipeline_engine.task_graph is a.task_graph

    def test_injected_pipeline_engine_without_planner(self) -> None:
        pipe = PipelineEngine(ExecutionPlanner())
        a = Agent(pipeline_engine=pipe)
        assert a.pipeline_engine is pipe
        assert a.pipeline_engine.execution_planner is not a.execution_planner
        assert a.pipeline_run_manager.pipeline_engine is pipe

    def test_shared_store_between_agents(self) -> None:
        gm = GoalManager()
        a, b = Agent(goal_manager=gm), Agent(goal_manager=gm)
        a.goal_manager.create_goal(title="t", goal_id="g1")
        assert b.goal_manager.get_goal("g1") is not None


class TestPlanningDistinction:
    def test_planning_remains_legacy(self) -> None:
        a = Agent()
        assert isinstance(a.planning, LegacyPlanningEngine)
        assert type(a.planning).__module__ == "core.planner"

    def test_planning_engine_is_foundation(self) -> None:
        a = Agent()
        assert isinstance(a.planning_engine, FoundationPlanningEngine)
        assert type(a.planning_engine).__module__ == "core.planning_engine"

    def test_planning_and_planning_engine_distinct(self) -> None:
        a = Agent()
        assert a.planning is not a.planning_engine
        assert type(a.planning) is not type(a.planning_engine)
        assert LegacyPlanningEngine is not FoundationPlanningEngine
        assert not isinstance(a.planning, FoundationPlanningEngine)
        assert not isinstance(a.planning_engine, LegacyPlanningEngine)

    def test_legacy_planning_injection_unchanged(self) -> None:
        legacy = LegacyPlanningEngine()
        a = Agent(planning=legacy)
        assert a.planning is legacy
        assert isinstance(a.planning_engine, FoundationPlanningEngine)

    def test_exported_planning_engine_is_legacy(self) -> None:
        assert agent_module.PlanningEngine is LegacyPlanningEngine


class TestPublicSurface:
    def test_all_unchanged(self) -> None:
        assert set(agent_module.__all__) == {
            "Agent", "CoordinationSnapshot", "ContextManager",
            "ExecutionCoordinator", "ExecutionOrchestrator",
            "ExecutionPipeline", "ExecutionResult", "ExecutionSession",
            "HistoryManager", "KnowledgeManager", "LearningManager",
            "MemoryIndexManager", "PlanningEngine", "ReasoningManager",
            "ReflectionManager", "SkillDispatchDecision",
        }
        for name in (
            "GoalManager", "FoundationPlanningEngine", "TaskGraph",
            "ExecutionPlanner", "PipelineEngine", "PipelineRunManager",
        ):
            assert name not in agent_module.__all__, name

    def test_read_only_properties_exist(self) -> None:
        for name in FOUNDATION_PARAMS:
            attr = inspect.getattr_static(Agent, name)
            assert isinstance(attr, property), name
            assert attr.fget is not None, name

    def test_no_setters(self) -> None:
        a = Agent()
        for name in FOUNDATION_PARAMS:
            prop = inspect.getattr_static(Agent, name)
            assert prop.fset is None, name
            assert prop.fdel is None, name
            with pytest.raises(AttributeError):
                setattr(a, name, None)

    def test_no_foundation_operations_on_agent(self) -> None:
        a = Agent()
        for attr in (
            "create_goal", "create_plan", "create_node", "build_pipeline",
            "create_run", "update_run", "run_pipeline", "execute_pipeline",
            "foundation", "container", "stores",
        ):
            assert not hasattr(a, attr), attr


class TestLegacyCompositionIntact:
    def test_legacy_defaults_unchanged(self) -> None:
        a = Agent()
        assert isinstance(a.execution_orchestrator, ExecutionOrchestrator)
        assert isinstance(a.execution_pipeline, ExecutionPipeline)
        assert a.execution_orchestrator.order == ()
        assert a.execution_orchestrator.snapshot() == ()
        assert a.execution_pipeline.ready_task_ids() == ()

    def test_legacy_injection_unchanged(self) -> None:
        orch = ExecutionOrchestrator([])
        a = Agent(execution_orchestrator=orch)
        assert a.execution_orchestrator is orch
        assert isinstance(a.execution_pipeline, ExecutionPipeline)

    def test_foundation_injection_does_not_touch_legacy(self) -> None:
        a = Agent(goal_manager=GoalManager(), pipeline_engine=PipelineEngine(ExecutionPlanner()))
        assert a.execution_orchestrator.snapshot() == ()
        assert a.execution_pipeline.ready_task_ids() == ()
        assert isinstance(a.planning, LegacyPlanningEngine)

    def test_handle_request_unaffected(self) -> None:
        a = Agent()
        snap = a.handle_request("fix the wifi")
        assert snap.ready_task_ids == Agent().handle_request("fix the wifi").ready_task_ids
        # Legacy flow leaves the v8.x stores untouched.
        for name in FOUNDATION_PARAMS:
            assert getattr(a, name).count() == 0, name

    def test_existing_construction_patterns_compatible(self) -> None:
        # Bare, legacy keyword, and mixed keyword construction all work.
        Agent()
        Agent(planning=LegacyPlanningEngine(), execution_orchestrator=ExecutionOrchestrator([]))
        Agent(execution_orchestrator=ExecutionOrchestrator([]), task_graph=TaskGraph())


class TestNoStateMutationOnConstruction:
    def test_all_stores_start_empty(self) -> None:
        a = Agent()
        for name in FOUNDATION_PARAMS:
            store = getattr(a, name)
            assert store.count() == 0, name
            assert len(store) == 0, name

    def test_no_records_auto_created(self) -> None:
        a = Agent()
        assert a.goal_manager.list_goals() == ()
        assert a.planning_engine.list_plans() == ()
        assert a.task_graph.list_nodes() == ()
        assert a.execution_planner.list_execution_plans() == ()
        assert a.pipeline_engine.list_pipelines() == ()
        assert a.pipeline_run_manager.list_runs() == ()

    def test_property_access_does_not_mutate(self) -> None:
        a = Agent()
        for name in FOUNDATION_PARAMS:
            getattr(a, name)
            getattr(a, name)
        for name in FOUNDATION_PARAMS:
            assert getattr(a, name).count() == 0, name


class TestImportArchitecture:
    def test_agent_imports_exactly_the_six_v8_modules(self) -> None:
        imported = _agent_imported_modules()
        assert V8_MODULES <= imported
        # No other new v8.x-style or unexpected modules leaked in.
        core_imports = {m for m in imported if m.startswith("core.")}
        allowed_legacy = {
            "core.agent.context_manager", "core.agent.history_manager",
            "core.agent.knowledge_manager", "core.agent.learning_manager",
            "core.agent.memory_index_manager", "core.agent.reasoning_manager",
            "core.agent.reflection_manager", "core.ai_provider", "core.ai_service",
            "core.conversation_history", "core.memory_engine", "core.problem_solver",
            "core.reflection_engine", "core.execution_coordinator",
            "core.execution_orchestrator", "core.execution_pipeline",
            "core.execution_result", "core.execution_session", "core.planner",
            "core.planner_execution_orchestrator_adapter", "core.skill_dispatch",
            "core.skill_registry",
        }
        # v8.15 tool bridge adds exactly these two on top of the v8.10 six.
        v8_15_modules = {"core.tool_registry", "core.tool_router"}
        v8_16_modules = {"core.tool_interface"}  # ToolRequest for the opt-in route
        v8_17_modules = {"core.tool_dispatch"}  # ToolDispatchDecision for the tool chain
        v8_21_modules = {"core.plan_projection"}  # legacy plan -> Foundation projection
        v8_22_modules = {"core.stage_dispatch"}  # pipeline-stage tool dispatch
        v8_25_modules = {"core.lifecycle_reflection"}  # goal/plan lifecycle reflection
        v8_26_modules = {"core.step_lifecycle"}  # step lifecycle reflection
        v8_28_modules = {"core.execution_failure"}  # shared failure normalization
        assert core_imports == allowed_legacy | V8_MODULES | v8_15_modules | v8_16_modules | v8_17_modules | v8_21_modules | v8_22_modules | v8_25_modules | v8_26_modules | v8_28_modules

    def test_foundation_planning_engine_is_aliased(self) -> None:
        aliases = {
            (node.module, n.name, n.asname)
            for node in ast.walk(_agent_tree())
            if isinstance(node, ast.ImportFrom)
            for n in node.names
        }
        assert ("core.planning_engine", "PlanningEngine", "FoundationPlanningEngine") in aliases
        assert ("core.planner", "PlanningEngine", None) in aliases

    def test_no_v8_module_imports_agent(self) -> None:
        for mod in V8_MODULES:
            path = os.path.join(CORE_DIR, mod.split(".")[1] + ".py")
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("core.agent"), (mod, node.module)
                    assert node.module not in {
                        "core." + f[:-3] for f in LEGACY_EXECUTION_FILES
                    }, (mod, node.module)
                elif isinstance(node, ast.Import):
                    for n in node.names:
                        assert not n.name.startswith("core"), (mod, n.name)

    def test_legacy_execution_modules_do_not_reference_v8(self) -> None:
        for rel in LEGACY_EXECUTION_FILES:
            with open(os.path.join(CORE_DIR, rel), encoding="utf-8") as f:
                src = f.read()
            for token in (
                "goal_manager", "planning_engine", "task_graph",
                "execution_planner", "pipeline_engine", "pipeline_run",
            ):
                assert token not in src, (rel, token)

    def test_no_circular_import_in_fresh_interpreter(self) -> None:
        # Importing each v8.x module first, then Agent, must succeed in a
        # clean process — proves there is no import cycle.
        code = (
            "import core.pipeline_run, core.pipeline_engine, core.execution_planner, "
            "core.goal_manager, core.planning_engine, core.task_graph; "
            "import core.agent; print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.normpath(os.path.join(HERE, "..")),
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"
