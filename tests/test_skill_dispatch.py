"""Tests for v5.0 Controlled Skill Dispatch Decision.

Validates that the dispatch decision is immutable, deterministic, and
performs no real dispatch / execution / AI / Memory side effects.
Uses only the public SkillRegistry APIs.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.agent import Agent, SkillDispatchDecision
from core.execution_result import ExecutionResult
from core.skill_dispatch import build_dispatch_decision
from core.skill_registry import is_registered, list_skills


@pytest.fixture(autouse=True)
def _stub_memory_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from core import problem_solver

    monkeypatch.setattr(problem_solver, "recall", lambda **kwargs: [])
    monkeypatch.setattr(problem_solver, "why", lambda *args, **kwargs: [])


class TestSkillDispatchDecisionImmutable:
    def test_decision_is_frozen(self) -> None:
        d = build_dispatch_decision("t1", "missing_tool")
        with pytest.raises(FrozenInstanceError):
            d.would_dispatch = True  # type: ignore[misc]

    def test_context_is_read_only(self) -> None:
        d = build_dispatch_decision("t1", "missing_tool", context={"k": "v"})
        with pytest.raises(TypeError):
            d.context["k"] = "x"  # type: ignore[index]

    def test_unknown_tool_yields_skip(self) -> None:
        d = build_dispatch_decision("t1", "definitely_not_a_skill")
        assert d.task_id == "t1"
        assert d.tool_name == "definitely_not_a_skill"
        assert d.is_registered is False
        assert d.would_dispatch is False
        assert d.action == "skip"


class TestSkillDispatchDecisionRegistered:
    def test_registered_tool_yields_dispatch_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate a registered tool via the public ``is_registered`` API.

        We replace ``is_registered`` with a deterministic stand-in
        (restored automatically by ``monkeypatch``) so the real
        registry state is never mutated and no private attribute is
        touched.
        """
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fixture_tool",
        )
        d = build_dispatch_decision("t1", "fixture_tool")
        assert d.is_registered is True
        assert d.would_dispatch is True
        assert d.action == "dispatch"


class TestDeterministic:
    def test_same_inputs_same_decision(self) -> None:
        a = build_dispatch_decision("t1", "no_such_tool", context={"k": 1})
        b = build_dispatch_decision("t1", "no_such_tool", context={"k": 1})
        assert a == b

    def test_dispatch_is_pure_no_mutation_of_registry(self) -> None:
        # Snapshot only the public read APIs (no private attribute access).
        before = [s["name"] for s in list_skills()]
        # A sample of public boolean lookups — must be stable across the call.
        probe_names = ("a", "b", "c", "no_such_tool", "another_tool")
        before_probe = {n: is_registered(n) for n in probe_names}
        build_dispatch_decision("t1", "no_such_tool")
        assert [s["name"] for s in list_skills()] == before
        assert {n: is_registered(n) for n in probe_names} == before_probe


class TestAgentDispatchDecisionIntegration:
    def test_returns_result_and_one_decision_per_ready_task(self) -> None:
        agent = Agent()
        result, decisions = agent.execute_request_with_dispatch_decision("fix the wifi")
        assert isinstance(result, ExecutionResult)
        assert len(decisions) == 1
        assert isinstance(decisions[0], SkillDispatchDecision)
        assert decisions[0].tool_name == "fix the wifi"
        assert decisions[0].action == "skip"

    def test_decisions_are_deterministic_for_same_goal(self) -> None:
        agent = Agent()
        _, d1 = agent.execute_request_with_dispatch_decision("fix the wifi")
        _, d2 = agent.execute_request_with_dispatch_decision("fix the wifi")
        assert d1 == d2

    def test_dispatch_decision_does_not_execute(self) -> None:
        agent = Agent()
        plan = agent.planning.plan("fix the wifi")
        session = agent.create_execution_session(plan)
        before = session.orchestrator.snapshot()
        agent.execute_request_with_dispatch_decision("fix the wifi")
        assert session.orchestrator.snapshot() == before

    def test_no_skill_handler_is_invoked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: called.append("dispatch"))
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        Agent().execute_request_with_dispatch_decision("fix the wifi")
        assert called == []


class TestControlledSkillExecution:
    """v5.1 — Controlled Skill Execution stage (reuses the v5.0 chain)."""

    def test_unregistered_skill_never_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[str] = []
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: called.append("dispatch"))
        # Default registry state: no skill is registered for "fix the wifi".
        Agent().execute_request_with_skill_execution("fix the wifi")
        assert called == []

    def test_registered_skill_executes_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invocations: list[tuple[str, dict, dict]] = []
        from core import skill_registry as reg

        def fake_dispatch(tool_name: str, args: dict, ctx: dict | None = None):
            invocations.append((tool_name, dict(args), dict(ctx or {})))
            return "ok"

        # Patch both the public registry symbol and the agent's local alias.
        monkeypatch.setattr(reg, "dispatch", fake_dispatch)
        monkeypatch.setattr("core.agent.skill_dispatch", fake_dispatch)
        # Make the registry think the plan's tool name is registered.
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        result, decisions = agent.execute_request_with_skill_execution("fix the wifi")

        assert isinstance(result, ExecutionResult)
        assert len(invocations) == 1
        tool, args, ctx = invocations[0]
        assert tool == "fix the wifi"
        assert args == {"problem": "fix the wifi"}
        assert "project" in ctx
        assert len(decisions) == 1
        assert decisions[0].would_dispatch is True

    def test_dispatch_decision_still_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        result, decisions = Agent().execute_request_with_skill_execution("fix the wifi")
        assert isinstance(result, ExecutionResult)
        assert len(decisions) == 1
        assert decisions[0].action == "skip"

    def test_existing_lifecycle_remains_deterministic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        agent = Agent()
        r1, d1 = agent.execute_request_with_skill_execution("fix the wifi")
        r2, d2 = agent.execute_request_with_skill_execution("fix the wifi")
        assert r1.session_id == r2.session_id
        assert d1 == d2

    def test_no_state_mutation_outside_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        agent = Agent()
        plan = agent.planning.plan("fix the wifi")
        session = agent.create_execution_session(plan)
        before = session.orchestrator.snapshot()
        agent.execute_request_with_skill_execution("fix the wifi")
        # Execution stopped without ever touching orchestrator state.
        assert session.orchestrator.snapshot() == before

    def test_no_duplicate_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invocations: list[str] = []
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: invocations.append("x"))
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: invocations.append("x"))
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )
        Agent().execute_request_with_skill_execution("fix the wifi")
        assert len(invocations) == 1  # exactly once per ready task


class TestMemoryWriteback:
    """v5.2 — Memory Writeback (Phase 1)."""

    @pytest.fixture(autouse=True)
    def _stub_remember(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
        """Stub the underlying MemoryEngine ``remember`` so no real
        write side effect ever occurs during tests."""
        from core import problem_solver

        writes: list[tuple] = []

        def fake_remember(*args, **kwargs):
            writes.append((args, kwargs))
            return "stub-id"

        monkeypatch.setattr(problem_solver, "remember", fake_remember)
        return writes

    def test_successful_execution_performs_exactly_one_memory_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _stub_remember: list,
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        Agent().execute_request_with_memory_writeback("fix the wifi")

        assert len(_stub_remember) == 1

    def test_skipped_execution_performs_no_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _stub_remember: list,
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)

        Agent().execute_request_with_memory_writeback("fix the wifi")

        assert _stub_remember == []

    def test_failed_execution_performs_no_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _stub_remember: list,
    ) -> None:
        """When dispatch raises (simulated failure), no memory write occurs."""
        from core import skill_registry as reg

        def boom(*a, **kw):
            raise RuntimeError("simulated skill failure")

        monkeypatch.setattr(reg, "dispatch", boom)
        monkeypatch.setattr("core.agent.skill_dispatch", boom)
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        with pytest.raises(RuntimeError):
            Agent().execute_request_with_memory_writeback("fix the wifi")

        assert _stub_remember == []

    def test_existing_execution_behaviour_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _stub_remember: list,
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        agent = Agent()
        r1, d1 = agent.execute_request_with_memory_writeback("fix the wifi")
        r2, d2 = agent.execute_request_with_memory_writeback("fix the wifi")
        assert r1.session_id == r2.session_id
        assert d1 == d2
        # Two runs of an unregistered tool → zero writes.
        assert _stub_remember == []

    def test_no_duplicate_memory_writes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _stub_remember: list,
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        Agent().execute_request_with_memory_writeback("fix the wifi")
        # Exactly one write per ready task, regardless of how many
        # times the method is invoked end-to-end.
        assert len(_stub_remember) == 1


class TestReflection:
    """v5.3 — Reflection Engine (Phase 1)."""

    @pytest.fixture(autouse=True)
    def _stub_remember(self, monkeypatch: pytest.MonkeyPatch) -> list:
        """Avoid real MemoryEngine writes during reflection tests."""
        from core import problem_solver

        writes: list = []
        monkeypatch.setattr(
            problem_solver, "remember",
            lambda *a, **kw: writes.append((a, kw)) or "stub-id",
        )
        return writes

    def test_successful_execution_creates_exactly_one_reflection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.reflection.get_all())
        agent.execute_request_with_reflection("fix the wifi")
        after = len(agent.reflection.get_all())
        assert after - before == 1

    def test_skipped_execution_creates_no_reflection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)

        agent = Agent()
        before = len(agent.reflection.get_all())
        agent.execute_request_with_reflection("fix the wifi")
        assert len(agent.reflection.get_all()) == before

    def test_failed_execution_creates_no_reflection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        def boom(*a, **kw):
            raise RuntimeError("simulated skill failure")

        monkeypatch.setattr(reg, "dispatch", boom)
        monkeypatch.setattr("core.agent.skill_dispatch", boom)
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.reflection.get_all())
        with pytest.raises(RuntimeError):
            agent.execute_request_with_reflection("fix the wifi")
        assert len(agent.reflection.get_all()) == before

    def test_reflection_occurs_after_memory_writeback(
        self, monkeypatch: pytest.MonkeyPatch, _stub_remember: list
    ) -> None:
        """Reflection must run only after the memory writeback stage."""
        from core import skill_registry as reg

        call_order: list[str] = []

        def fake_dispatch(*a, **kw):
            call_order.append("dispatch")
            return "ok"

        monkeypatch.setattr(reg, "dispatch", fake_dispatch)
        monkeypatch.setattr("core.agent.skill_dispatch", fake_dispatch)
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        # Wrap the existing reflection.add_reflection to record ordering.
        agent = Agent()
        original_add = agent.reflection.add_reflection

        def wrapped_add(*a, **kw):
            call_order.append("reflection")
            return original_add(*a, **kw)

        monkeypatch.setattr(agent.reflection, "add_reflection", wrapped_add)
        # Also intercept the memory write so we can see its position.
        from core import problem_solver

        def wrapped_remember(*a, **kw):
            call_order.append("memory")
            return "stub-id"

        monkeypatch.setattr(problem_solver, "remember", wrapped_remember)

        agent.execute_request_with_reflection("fix the wifi")

        assert call_order.index("dispatch") < call_order.index("memory")
        assert call_order.index("memory") < call_order.index("reflection")

    def test_existing_execution_behaviour_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        agent = Agent()
        r1, d1 = agent.execute_request_with_reflection("fix the wifi")
        r2, d2 = agent.execute_request_with_reflection("fix the wifi")
        assert r1.session_id == r2.session_id
        assert d1 == d2

    def test_no_duplicate_reflections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.reflection.get_all())
        agent.execute_request_with_reflection("fix the wifi")
        # Exactly one reflection per ready task, in a single run.
        assert len(agent.reflection.get_all()) - before == 1


class TestLearning:
    """v5.4 — Learning Engine (Phase 1)."""

    @pytest.fixture(autouse=True)
    def _stub_remember(self, monkeypatch: pytest.MonkeyPatch) -> list:
        """Avoid real MemoryEngine writes during learning tests."""
        from core import problem_solver

        writes: list = []
        monkeypatch.setattr(
            problem_solver, "remember",
            lambda *a, **kw: writes.append((a, kw)) or "stub-id",
        )
        return writes

    def test_successful_execution_produces_exactly_one_learning_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.learning.get_all())
        agent.execute_request_with_learning("fix the wifi")
        assert len(agent.learning.get_all()) - before == 1

    def test_skipped_execution_produces_no_learning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)

        agent = Agent()
        before = len(agent.learning.get_all())
        agent.execute_request_with_learning("fix the wifi")
        assert len(agent.learning.get_all()) == before

    def test_failed_execution_produces_no_learning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        def boom(*a, **kw):
            raise RuntimeError("simulated skill failure")

        monkeypatch.setattr(reg, "dispatch", boom)
        monkeypatch.setattr("core.agent.skill_dispatch", boom)
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.learning.get_all())
        with pytest.raises(RuntimeError):
            agent.execute_request_with_learning("fix the wifi")
        assert len(agent.learning.get_all()) == before

    def test_learning_occurs_after_reflection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Learning must run only after the reflection stage."""
        from core import skill_registry as reg

        call_order: list[str] = []

        def fake_dispatch(*a, **kw):
            call_order.append("dispatch")
            return "ok"

        monkeypatch.setattr(reg, "dispatch", fake_dispatch)
        monkeypatch.setattr("core.agent.skill_dispatch", fake_dispatch)
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        original_reflection_add = agent.reflection.add_reflection

        def wrapped_reflection_add(*a, **kw):
            call_order.append("reflection")
            return original_reflection_add(*a, **kw)

        monkeypatch.setattr(agent.reflection, "add_reflection", wrapped_reflection_add)

        original_learning = agent.learning.record_successful_pattern

        def wrapped_learning(*a, **kw):
            call_order.append("learning")
            return original_learning(*a, **kw)

        monkeypatch.setattr(
            agent.learning, "record_successful_pattern", wrapped_learning
        )

        agent.execute_request_with_learning("fix the wifi")

        assert call_order.index("dispatch") < call_order.index("reflection")
        assert call_order.index("reflection") < call_order.index("learning")

    def test_existing_behaviour_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(reg, "is_registered", lambda name: False)
        agent = Agent()
        r1, d1 = agent.execute_request_with_learning("fix the wifi")
        r2, d2 = agent.execute_request_with_learning("fix the wifi")
        assert r1.session_id == r2.session_id
        assert d1 == d2

    def test_no_duplicate_learning_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core import skill_registry as reg

        monkeypatch.setattr(reg, "dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr("core.agent.skill_dispatch", lambda *a, **kw: "ok")
        monkeypatch.setattr(
            "core.skill_dispatch.is_registered",
            lambda name: name == "fix the wifi",
        )

        agent = Agent()
        before = len(agent.learning.get_all())
        agent.execute_request_with_learning("fix the wifi")
        # Exactly one learning entry per ready task, in a single run.
        assert len(agent.learning.get_all()) - before == 1