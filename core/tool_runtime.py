"""MARK L v8.39 — Tool Runtime Loop (pure orchestration).

Runs one tool-calling run: the model proposes tool calls, each call is either
refused or executed through the injected router, the results go back to the
model as a ``ToolExchange`` in the follow-up request, and the loop ends with
the first response that proposes no call. All collaborators are injected, so
this leaf imports no router, registry, catalog, provider, Agent or memory
module, performs no I/O and holds no state (every run owns its own counters).

Owner-locked policy (see ``docs/EDITH_COMPLETION_CONTRACT.md`` §8.1):

* **Limits (OD-C).** At most ``MAX_MODEL_ROUNDS`` (5) model rounds — a round is
  one provider call, the first being round 1 — and at most
  ``MAX_TOOL_EXECUTIONS`` (10) tool executions per run, where an execution is
  one invocation of the router, counted at invocation (a call that raises
  counts; a refused call does not). Exhausting either limit raises
  ``ToolLoopExhaustedError``: if the 5th response still proposes calls they are
  not run; once a call has passed the offered / registered gates and 10
  executions are used, the error is raised before the confirmation hook is
  asked and before invoking. These limits are not the v8.33 per-step retry
  bound; the router is called at most once per call (no retry) and no other
  numeric limit exists.
* **Authorization (O1).** A call is refused unless its tool is among the tools
  offered for the run and is registered. A tool whose ``side_effects`` is not
  exactly ``False`` additionally needs the injected ``confirm`` hook to return
  exactly ``True``; with no hook it is refused.
* **Errors (O2).** A refusal or failure reaches the model as a fixed,
  sanitized string in ``ToolCallResult.output`` — ``error: refused (<reason>)``
  with the closed reasons ``not_offered`` / ``not_registered`` /
  ``confirmation_denied``, or ``error: failed (<ExceptionTypeName>)`` — and the
  loop continues. The exception message, arguments, repr and traceback are
  never sent. A non-``Exception`` ``BaseException`` and every exception raised
  by the provider call or the hook propagate unchanged.
* **Audit (O9).** The run returns one immutable ``ToolCallOutcome`` per call
  (``call_id``, ``tool_name``, ``outcome``, ``exception_type`` for a failure) and
  writes nothing.

Dependency direction:

    Agent  →  tool_runtime  →  ai_provider, tool_calling, tool_interface
    tool_runtime  →  the router, registry and catalog modules, Agent   (forbidden:
    the router and registry arrive as injected objects)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from core.ai_provider import AIRequest, AIResponse
from core.tool_calling import ToolCall, ToolCallResult, ToolExchange
from core.tool_interface import ToolRequest

__all__ = [
    "MAX_MODEL_ROUNDS",
    "MAX_TOOL_EXECUTIONS",
    "ToolCallOutcome",
    "ToolLoopExhaustedError",
    "ToolLoopResult",
    "run_tool_loop",
]

MAX_MODEL_ROUNDS = 5  # OD-C: model rounds (provider calls) per run
MAX_TOOL_EXECUTIONS = 10  # OD-C: router invocations per run

_OUTCOMES = ("executed", "refused", "failed")


@dataclass(frozen=True, slots=True)
class ToolCallOutcome:
    """The audit record of one model-proposed call (never arguments or text)."""

    call_id: str
    tool_name: str
    outcome: str
    exception_type: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("call_id", "tool_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.outcome not in _OUTCOMES:
            raise ValueError(f"outcome must be one of {_OUTCOMES}")
        if self.outcome == "failed":
            if not isinstance(self.exception_type, str) or not self.exception_type.strip():
                raise ValueError("a failed outcome requires exception_type")
        elif self.exception_type is not None:
            raise ValueError("exception_type is only valid for a failed outcome")


@dataclass(frozen=True, slots=True)
class ToolLoopResult:
    """The finished run: the final response, the audit records and the counts."""

    response: AIResponse
    outcomes: tuple[ToolCallOutcome, ...]
    rounds: int
    tool_executions: int


class ToolLoopExhaustedError(Exception):
    """A run used up one of the two loop limits (owner decision OD-C).

    ``limit`` is ``"model_rounds"`` or ``"tool_executions"``; ``outcomes``
    holds the audit records produced before the limit was reached, so nothing
    is lost. The message is structural only.
    """

    def __init__(
        self,
        limit: str,
        rounds: int,
        tool_executions: int,
        outcomes: tuple[ToolCallOutcome, ...],
    ) -> None:
        if limit == "model_rounds":
            maximum = MAX_MODEL_ROUNDS
        elif limit == "tool_executions":
            maximum = MAX_TOOL_EXECUTIONS
        else:
            raise ValueError("limit must be 'model_rounds' or 'tool_executions'")
        super().__init__(f"tool loop exhausted: {limit} limit ({maximum}) reached")
        self.limit = limit
        self.rounds = rounds
        self.tool_executions = tool_executions
        self.outcomes = tuple(outcomes)


def _refusal(call: ToolCall, reason: str) -> tuple[ToolCallResult, ToolCallOutcome]:
    return (
        ToolCallResult(call.call_id, call.name, f"error: refused ({reason})"),
        ToolCallOutcome(call.call_id, call.name, "refused"),
    )


def _failure(call: ToolCall, exc: Exception) -> tuple[ToolCallResult, ToolCallOutcome]:
    type_name = type(exc).__name__
    return (
        ToolCallResult(call.call_id, call.name, f"error: failed ({type_name})"),
        ToolCallOutcome(call.call_id, call.name, "failed", type_name),
    )


def run_tool_loop(
    complete: Callable[[AIRequest], AIResponse],
    *,
    prompt: str,
    tools: Sequence[Any],
    router: Any,
    registry: Any,
    confirm: Optional[Callable[[ToolCall, Any], bool]] = None,
) -> ToolLoopResult:
    """Run one tool-calling run and return its ``ToolLoopResult``.

    ``complete`` performs one provider call for an ``AIRequest`` (the caller
    binds the provider, history and memory); ``tools`` are the ``ToolSpec``
    declarations offered for the whole run (non-empty, ``model_invocable``,
    validated by ``AIRequest``); ``router.route(ToolRequest)`` executes a tool
    and ``registry.has(name)`` says whether it is registered; ``confirm``
    (``(call, spec) -> bool``) approves side-effecting calls.

    Raises:
        TypeError / ValueError: invalid arguments (including empty ``tools``).
        ToolLoopExhaustedError: a loop limit was reached.
        Exception: whatever ``complete`` or ``confirm`` raises, unchanged.
    """
    if not callable(complete):
        raise TypeError("complete must be callable")
    if not callable(getattr(router, "route", None)):
        raise TypeError("router must provide route(request)")
    if not callable(getattr(registry, "has", None)):
        raise TypeError("registry must provide has(name)")
    if confirm is not None and not callable(confirm):
        raise TypeError("confirm must be callable or None")
    offered = AIRequest(prompt=prompt, tools=tuple(tools)).tools
    if not offered:
        raise ValueError("tools must not be empty")
    specs = {spec.name: spec for spec in offered}

    exchanges: list[ToolExchange] = []
    outcomes: list[ToolCallOutcome] = []
    executions = 0
    for round_number in range(1, MAX_MODEL_ROUNDS + 1):
        response = complete(AIRequest(prompt=prompt, tools=offered, tool_exchanges=tuple(exchanges)))
        if not response.tool_calls:
            return ToolLoopResult(response, tuple(outcomes), round_number, executions)
        if round_number == MAX_MODEL_ROUNDS:
            raise ToolLoopExhaustedError("model_rounds", round_number, executions, tuple(outcomes))
        results: list[ToolCallResult] = []
        for call in response.tool_calls:
            spec = specs.get(call.name)
            if spec is None:
                result, outcome = _refusal(call, "not_offered")
            elif registry.has(call.name) is not True:
                result, outcome = _refusal(call, "not_registered")
            else:
                if executions >= MAX_TOOL_EXECUTIONS:
                    raise ToolLoopExhaustedError(
                        "tool_executions", round_number, executions, tuple(outcomes)
                    )
                if spec.side_effects is not False and not (
                    confirm is not None and confirm(call, spec) is True
                ):
                    result, outcome = _refusal(call, "confirmation_denied")
                else:
                    executions += 1
                    try:
                        tool_result = router.route(
                            ToolRequest(tool_name=call.name, arguments=call.arguments)
                        )
                        result = ToolCallResult(call.call_id, call.name, tool_result.output)
                        outcome = ToolCallOutcome(call.call_id, call.name, "executed")
                    except Exception as exc:  # noqa: BLE001 - converted per O2; BaseException propagates
                        result, outcome = _failure(call, exc)
            results.append(result)
            outcomes.append(outcome)
        exchanges.append(ToolExchange(calls=response.tool_calls, results=tuple(results), text=response.text))
    raise ToolLoopExhaustedError("model_rounds", MAX_MODEL_ROUNDS, executions, tuple(outcomes))  # pragma: no cover
