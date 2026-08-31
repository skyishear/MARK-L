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