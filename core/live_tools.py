"""MARK L v8.41 — Production Tool Bridge (Gemini Live adapter).

The production runtime executes the tool calls of a realtime Gemini Live session
through its own dispatch code. This module puts those calls under the v8.x tool
stack without rewriting that code (owner decisions OD-2, OD-3; contract P2 / P3):

* ``declaration_to_spec`` turns a production (Gemini-format) tool declaration
  into a ``ToolSpec`` — types lower-cased, only the keywords the catalog's
  JSON-Schema subset knows (anything else fails loudly, nothing is repaired).
  Every production tool is model-invocable; only the tools in ``READ_ONLY_TOOLS``
  are marked free of side effects, the rest keep the restrictive default.
* ``CallbackTool`` is the ``ToolInterface`` a declared tool is registered with:
  it runs the production executor and returns its text.
* ``LiveToolSession`` registers the declarations in the Agent's registry and
  catalog and executes each ``tool_call`` batch of the Live session — one batch is
  one model round — through the router under exactly the C8 per-call policy
  (``core.tool_runtime.ToolRun``: offered / registered gates, the O1 confirmation
  hook, O2 sanitized strings, O9 outcome records, the OD-C limits per run). The
  Live session itself drives the loop, so a run ends when the model's turn does
  (``end_run``). When a limit is reached the pending calls of that batch are
  answered with ``error: failed (ToolLoopExhaustedError)`` and nothing more runs
  until the next run. The production executor stays in charge of the existing
  owner-identity / PIN gate; ``approve_requested_call`` is the confirmation hook
  that defers to it (the user's spoken request is the confirmation).

No Google SDK is imported here: the session hands plain ``LiveCall`` values in and
plain ``LiveReply`` values out. The router and registry are injected objects.
Nothing is persisted; the optional ``recorder`` receives the new outcome records
after every round and can never break a tool call.

Dependency direction:

    Agent  →  live_tools  →  tool_runtime, tool_calling, tool_catalog, tool_interface
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

from core.tool_calling import ToolCall
from core.tool_catalog import ToolSpec
from core.tool_interface import ToolRequest, ToolResult
from core.tool_runtime import ToolCallOutcome, ToolLoopExhaustedError, ToolRun

__all__ = [
    "CallbackTool",
    "LiveCall",
    "LiveReply",
    "LiveToolSession",
    "READ_ONLY_TOOLS",
    "approve_requested_call",
    "declaration_to_spec",
]

# Production tools that read or search without changing anything outside the
# assistant. Every other production tool keeps the restrictive default
# (``side_effects=True``), so the O1 hook decides before it runs.
READ_ONLY_TOOLS = frozenset({"web_search", "system_status", "recall_memory", "solve_problem"})

_EXHAUSTED_TEXT = "error: failed (ToolLoopExhaustedError)"


def _schema(node: object) -> object:
    """Lower-case the Gemini ``type`` names; leave every other keyword to the
    catalog's validator, which rejects anything outside its subset."""
    if isinstance(node, Mapping):
        converted: dict[str, object] = {}
        for key, value in node.items():
            if key == "type" and isinstance(value, str):
                converted[key] = value.lower()
            elif key == "properties" and isinstance(value, Mapping):
                converted[key] = {name: _schema(sub) for name, sub in value.items()}
            elif key == "items":
                converted[key] = _schema(value)
            else:
                converted[key] = value
        return converted
    return node


def declaration_to_spec(declaration: Mapping[str, Any]) -> ToolSpec:
    """Convert one production tool declaration into a model-invocable ``ToolSpec``.

    Raises:
        ValueError / TypeError / ``InvalidToolSchemaError``: the declaration is
            not convertible (nothing is repaired or dropped).
    """
    if not isinstance(declaration, Mapping):
        raise TypeError("declaration must be a mapping")
    name = declaration.get("name")
    description = declaration.get("description", "")
    parameters = declaration.get("parameters")
    return ToolSpec(
        name,  # type: ignore[arg-type]
        description,
        _schema(parameters) if parameters is not None else {"type": "object"},  # type: ignore[arg-type]
        idempotent=False,
        side_effects=name not in READ_ONLY_TOOLS,
        model_invocable=True,
    )


class CallbackTool:
    """A ``ToolInterface`` that runs a production executor: ``execute(name,
    arguments) -> str``."""

    def __init__(self, name: str, description: str, execute: Callable[[str, dict], str]) -> None:
        self.name = name
        self.description = description
        self._execute = execute

    def invoke(self, request: ToolRequest) -> ToolResult:
        return ToolResult(self.name, self._execute(request.tool_name, dict(request.arguments)))


@dataclass(frozen=True, slots=True)
class LiveCall:
    """One function call of a Live ``tool_call`` batch (``call_id`` may be absent)."""

    call_id: Optional[str]
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LiveReply:
    """The response to send back for one ``LiveCall`` (same ``call_id`` and name)."""

    call_id: Optional[str]
    name: str
    response: dict


def approve_requested_call(call: ToolCall, spec: ToolSpec) -> bool:
    """Production confirmation hook: the user's spoken request is the
    confirmation. The owner-identity / PIN gate for high-risk actions stays inside
    the production executor, which keeps its guidance to the model."""
    return True


class LiveToolSession:
    """Executes the tool calls of one Gemini Live session under the C8 policy.

    Args:
        router / registry / catalog: the Agent's tool router, tool registry and
            tool catalog (injected objects; the router needs ``route(request)``,
            the registry ``has`` / ``register``, the catalog ``register`` /
            ``list``).
        execute: ``async (name, arguments) -> Mapping`` — the production executor;
            its ``"result"`` value is the tool's text and the whole mapping is sent
            back to the model for an executed call.
        confirm: the O1 hook (``(call, spec) -> bool``); none means every
            side-effecting call is refused.
        recorder: optional ``(outcomes) -> None`` receiving the new O9 records
            after each round; its exceptions are suppressed.
    """

    def __init__(
        self,
        *,
        router: Any,
        registry: Any,
        catalog: Any,
        execute: Callable[[str, dict], Awaitable[Mapping[str, Any]]],
        confirm: Optional[Callable[[ToolCall, Any], bool]] = None,
        recorder: Optional[Callable[[tuple[ToolCallOutcome, ...]], None]] = None,
    ) -> None:
        if not callable(execute):
            raise TypeError("execute must be callable")
        if recorder is not None and not callable(recorder):
            raise TypeError("recorder must be callable or None")
        self._router = router
        self._registry = registry
        self._catalog = catalog
        self._execute = execute
        self._confirm = confirm
        self._recorder = recorder
        self._registered: set[str] = set()
        self._run: Optional[ToolRun] = None
        self._exhausted = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._responses: list[dict] = []

    # ── registration (P2) ───────────────────────────────────────────────

    def sync_declarations(self, declarations: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
        """Register every not-yet-registered declaration (spec in the catalog,
        callback tool in the registry) and return ``declarations`` unchanged.
        Idempotent per name. A declaration that cannot be converted raises."""
        for declaration in declarations:
            spec = declaration_to_spec(declaration)
            if spec.name in self._registered:
                continue
            self._catalog.register(spec)
            self._registry.register(CallbackTool(spec.name, spec.description, self._execute_blocking))
            self._registered.add(spec.name)
        return declarations

    @property
    def registered_names(self) -> frozenset[str]:
        return frozenset(self._registered)

    # ── execution (P3) ──────────────────────────────────────────────────

    def _execute_blocking(self, name: str, arguments: dict) -> str:
        """Runs in a worker thread: execute the production coroutine on the
        session's event loop and wait for it (the loop stays free meanwhile)."""
        assert self._loop is not None
        response = asyncio.run_coroutine_threadsafe(self._execute(name, arguments), self._loop).result()
        self._responses.append(dict(response))
        return str(response.get("result", ""))

    async def handle_round(self, calls: Sequence[LiveCall]) -> tuple[LiveReply, ...]:
        """Handle one ``tool_call`` batch (one model round) and return one reply
        per call, in order."""
        self._loop = asyncio.get_running_loop()
        return await self._loop.run_in_executor(None, self._process_round, tuple(calls))

    def end_run(self) -> None:
        """The model's turn is over: the next batch starts a fresh run (counters,
        limits and the exhausted state are reset)."""
        self._run = None
        self._exhausted = False

    def _offered(self) -> tuple[Any, ...]:
        return tuple(
            spec for spec in self._catalog.list() if spec.name in self._registered and spec.model_invocable
        )

    @staticmethod
    def _as_tool_call(call: LiveCall, index: int) -> ToolCall:
        call_id = call.call_id if isinstance(call.call_id, str) and call.call_id.strip() else f"call_{index + 1}"
        try:
            return ToolCall(call_id=call_id, name=call.name, arguments=call.arguments)
        except (TypeError, ValueError):
            # Malformed call (blank name, non-JSON arguments): never executed — it
            # names no offered tool, so the run refuses it.
            return ToolCall(call_id=call_id, name="invalid_call", arguments={})

    def _process_round(self, calls: tuple[LiveCall, ...]) -> tuple[LiveReply, ...]:
        if self._exhausted:
            return self._exhausted_replies(calls)
        if self._run is None:
            self._run = ToolRun(
                tools=self._offered(), router=self._router, registry=self._registry, confirm=self._confirm
            )
        run = self._run
        before = len(run.outcomes)
        tool_calls = tuple(self._as_tool_call(call, index) for index, call in enumerate(calls))
        self._responses = []
        try:
            results = run.process_round(tool_calls)
        except ToolLoopExhaustedError:
            self._exhausted = True
            done = run.outcomes[before:]
            self._record(done)
            return self._partial_replies(calls, done)
        new_outcomes = run.outcomes[before:]
        self._record(new_outcomes)
        legacy = iter(self._responses)
        replies: list[LiveReply] = []
        for call, result, outcome in zip(calls, results, new_outcomes):
            response = next(legacy) if outcome.outcome == "executed" else {"result": result.output}
            replies.append(LiveReply(call.call_id, call.name, response))
        return tuple(replies)

    def _partial_replies(self, calls: Sequence[LiveCall], done: Sequence[ToolCallOutcome]) -> tuple[LiveReply, ...]:
        """A limit was reached mid-batch: the calls already handled keep their real
        answer (an executed call's production response, a failure's sanitized
        text); every other call gets the exhaustion text."""
        legacy = iter(self._responses)
        replies: list[LiveReply] = []
        for index, call in enumerate(calls):
            outcome = done[index] if index < len(done) else None
            if outcome is not None and outcome.outcome == "executed":
                response: dict = next(legacy)
            elif outcome is not None and outcome.outcome == "failed":
                response = {"result": f"error: failed ({outcome.exception_type})"}
            else:
                response = {"result": _EXHAUSTED_TEXT}
            replies.append(LiveReply(call.call_id, call.name, response))
        return tuple(replies)

    @staticmethod
    def _exhausted_replies(calls: Sequence[LiveCall]) -> tuple[LiveReply, ...]:
        return tuple(LiveReply(call.call_id, call.name, {"result": _EXHAUSTED_TEXT}) for call in calls)

    def _record(self, outcomes: Sequence[ToolCallOutcome]) -> None:
        if self._recorder is None or not outcomes:
            return
        try:
            self._recorder(tuple(outcomes))
        except Exception:  # noqa: BLE001 - recording must never break a tool call
            pass
