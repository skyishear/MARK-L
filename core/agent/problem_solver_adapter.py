"""Integration adapter bridging ProblemSolver to the Foundation modules.

Part of MARK L V3 Phase 2 (Integration), Step 4.

ProblemSolver (core/problem_solver.py) remains the only reasoning
engine — this adapter performs no diagnosis, no decision-making, and
no verification of its own. It only translates data ProblemSolver's
existing public functions already produced (the context bundle from
``gather_context()``, an ``ExecutionResult`` from
``execute_and_verify()``) into the shape ReasoningManager,
ReflectionManager, and ContextManager already accept through their
own existing public APIs, and forwards it on explicit caller request.

Nothing here runs automatically: every function is a single,
caller-invoked translation step. Neither ProblemSolver nor any
Foundation module is modified.

MemoryAdapter is intentionally not used at this integration point:
``ProblemSolver.record_outcome()`` already writes to MemoryEngine
directly on its own, so routing that same write through MemoryAdapter
as well would duplicate an existing persistence path rather than
support it.
"""

from __future__ import annotations

from typing import Any

from core.agent.context_manager import ContextManager
from core.agent.reasoning_manager import ReasoningManager, ReasoningRecord
from core.agent.reflection_manager import ReflectionManager, ReflectionRecord
from core.problem_solver import ExecutionResult


def record_reasoning_from_context(
    reasoning_manager: ReasoningManager,
    problem: str,
    context_bundle: dict[str, Any],
    *,
    selected_option: str = "",
    rationale: str = "",
    confidence_level: float = 0.0,
    outcome: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReasoningRecord:
    """Record a reasoning trace built from ProblemSolver's context bundle.

    ``context_bundle`` is the dict returned by
    ``core.problem_solver.gather_context()``. This function performs no
    reasoning of its own — it only maps that bundle's existing fields
    onto ``ReasoningManager.add_reasoning``'s existing fields:

    - ``considered_options`` <- one entry per prior solution found in
      ``context_bundle["known_solutions"]``
    - ``constraints`` <- one entry per related decision found in
      ``context_bundle["related_decisions"]``
    - ``assumptions`` <- one entry per related fact found in
      ``context_bundle["related_facts"]``

    The caller still supplies ``selected_option``, ``rationale``,
    ``confidence_level``, and ``outcome`` directly — this function has
    no way to know what was actually decided, since that decision is
    made elsewhere (by the LLM), not by ProblemSolver and not by this
    adapter.

    Args:
        reasoning_manager: The ReasoningManager instance to record into.
        problem: The problem statement (same string passed to
            ``gather_context`` / ``format_context_for_solver``).
        context_bundle: The dict returned by
            ``core.problem_solver.gather_context()``.
        selected_option: Forwarded to ``ReasoningManager.add_reasoning``.
        rationale: Forwarded to ``ReasoningManager.add_reasoning``.
        confidence_level: Forwarded to ``ReasoningManager.add_reasoning``.
        outcome: Forwarded to ``ReasoningManager.add_reasoning``.
        metadata: Forwarded to ``ReasoningManager.add_reasoning``.

    Returns:
        The ReasoningRecord created by ``ReasoningManager.add_reasoning``.
    """
    known_solutions = context_bundle.get("known_solutions") or []
    related_decisions = context_bundle.get("related_decisions") or []
    related_facts = context_bundle.get("related_facts") or []

    considered_options = [
        str(k.get("value", "")) for k in known_solutions if isinstance(k, dict)
    ]
    constraints = [
        str(d.get("decision", "")) for d in related_decisions if isinstance(d, dict)
    ]
    assumptions = [
        f"{f.get('category', '')}/{f.get('key', '')}: {f.get('value', '')}"
        for f in related_facts
        if isinstance(f, dict)
    ]

    return reasoning_manager.add_reasoning(
        problem_statement=problem,
        assumptions=assumptions,
        constraints=constraints,
        considered_options=considered_options,
        selected_option=selected_option,
        rationale=rationale,
        confidence_level=confidence_level,
        outcome=outcome,
        metadata=metadata,
    )


def record_reflection_from_execution(
    reflection_manager: ReflectionManager,
    subject: str,
    execution_result: ExecutionResult,
    *,
    what_worked: str = "",
    what_failed: str = "",
    mistakes_identified: list[str] | None = None,
    uncertainties: list[str] | None = None,
    improvement_suggestions: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReflectionRecord:
    """Record a reflection built from an execute_and_verify() result.

    ``execution_result`` is the ``ExecutionResult`` returned by
    ``core.problem_solver.execute_and_verify()``. This function performs
    no verification of its own — it only maps that already-verified
    outcome onto ``ReflectionManager.add_reflection``'s existing fields:

    - ``confidence_level`` <- ``1.0`` if ``execution_result.verified``
      else ``0.0`` (ProblemSolver's own verify step is the source of
      truth for whether it worked, not a guess made here)
    - ``completion_summary`` <- a factual one-line summary of attempts
      and verification status

    ``what_worked`` / ``what_failed`` / ``mistakes_identified`` /
    ``uncertainties`` / ``improvement_suggestions`` are free-form and
    passed through unchanged from the caller, since ``ExecutionResult``
    carries no such narrative fields to translate.

    Args:
        reflection_manager: The ReflectionManager instance to record into.
        subject: What the reflection is about (e.g. the action taken).
        execution_result: The ExecutionResult from
            ``core.problem_solver.execute_and_verify()``.
        what_worked: Forwarded to ``ReflectionManager.add_reflection``.
        what_failed: Forwarded to ``ReflectionManager.add_reflection``.
        mistakes_identified: Forwarded to
            ``ReflectionManager.add_reflection``.
        uncertainties: Forwarded to ``ReflectionManager.add_reflection``.
        improvement_suggestions: Forwarded to
            ``ReflectionManager.add_reflection``.
        metadata: Forwarded to ``ReflectionManager.add_reflection``.

    Returns:
        The ReflectionRecord created by ``ReflectionManager.add_reflection``.
    """
    confidence_level = 1.0 if execution_result.verified else 0.0
    completion_summary = (
        f"{'verified' if execution_result.verified else 'not verified'} "
        f"after {execution_result.attempts} attempt(s)"
    )

    return reflection_manager.add_reflection(
        subject=subject,
        what_worked=what_worked,
        what_failed=what_failed,
        mistakes_identified=mistakes_identified,
        uncertainties=uncertainties,
        improvement_suggestions=improvement_suggestions,
        confidence_level=confidence_level,
        completion_summary=completion_summary,
        metadata=metadata,
    )


def update_context_from_problem(
    context_manager: ContextManager,
    problem: str,
    project: str | None = None,
) -> None:
    """Record the problem currently being solved in the runtime context.

    Sets ``current_problem`` (and ``current_project``, if given) on the
    supplied ContextManager via its existing ``set`` method. This is
    optional, caller-invoked support for ProblemSolver — it never runs
    on its own, and callers that don't need it are free to skip it.

    Args:
        context_manager: The ContextManager instance to update.
        problem: The problem statement being solved.
        project: Optional project name, forwarded as-is.
    """
    context_manager.set("current_problem", problem)
    if project is not None:
        context_manager.set("current_project", project)
