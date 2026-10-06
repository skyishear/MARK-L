# MARK-L

> **EDITH** — a long-term, modular AI operating system.
> **MARK-L** is its repository and working implementation.

MARK-L is built as a stable, provider-neutral AI platform: goals are
planned, projected into explicit execution records, run through a
controlled tool system, and written back into memory and reflection with
deterministic, fully tested behavior. Every capability is added as a
small, additive, independently testable module.

**Status:** checkpoint **v8.39 complete** · next planned milestone
**v8.40+ tool calling on the remaining providers (owner-gated)** · verified
suite **2607 passed, 0 failed, 0 errors, 0 skipped**. `ROADMAP.md` is the authoritative, living record.

---

## Architecture

```
                    ┌──────────────────────────────────┐
  request / goal ─▶ │  Agent  (core/agent/__init__.py)  │  composition root
                    └──────────────────────────────────┘
          │                    │                      │
   context & memory      planning & execution     AI & tools
          │                    │                      │
  context_manager      planner → plan_projection   ai_service
  conversation_history goal_manager, task_graph    ai_provider(_registry/_router)
  memory_engine        execution_planner           *_provider (Claude, OpenAI,
  memory_context       pipeline_engine / run         Gemini, Ollama)
  reflection_engine    stage_dispatch              tool_interface / registry
  lifecycle_reflection step_lifecycle              tool_router / dispatch
  token_counter        execution_failure           tool_catalog / tool_calling
                       failure_taxonomy
```

### Provider-neutral AI foundation
- `AIProvider` protocol with neutral `AIRequest` / `AIResponse` records
  (`core/ai_provider.py`), a registry and router, and `AIService` as the
  single entry point used by the Agent.
- Transports for Anthropic Claude, OpenAI, Google Gemini and Ollama —
  lazy, injectable and fully mockable in tests.
- Neutral tool-calling types (`ToolSpec`, `ToolCall`) in
  `core/tool_calling.py`; provider-native formats are confined to the
  provider module that owns them (Anthropic first, v8.38).

### Memory, context and reflection
- `ConversationHistory` and a context-manager layer with an explicit
  context policy, history trimming and token budgeting (v8.34–v8.35).
- A dedicated system channel with opt-in memory injection (v8.36).
- Memory and reflection engines; lifecycle reflection for goals, plans
  and steps (v8.25–v8.26).

### Planning and execution
- Foundation stores: `PlanningEngine`, `TaskGraph`, `GoalManager`,
  `ExecutionPlanner`, `PipelineEngine`, `PipelineRunManager`.
- Plans are projected into Foundation records (`core/plan_projection.py`)
  and dispatched stage by stage (`core/stage_dispatch.py`), with run
  status recording and writeback.
- Failures are normalized into a shared taxonomy
  (`core/execution_failure.py`, `core/failure_taxonomy.py`), written back
  explicitly, and support resuming a failed run and bounded in-run retry
  (v8.27–v8.33).

### Tool system
- `ToolInterface` / `ToolRequest` / `ToolResult` / `ToolError`, a
  `ToolRegistry`, a `ToolRouter`, and explicit `ToolDispatchDecision`s.
- Existing skills are exposed as tools through an adapter
  (`core/skill_tool_adapter.py`).
- A tool catalog with metadata and schema validation (v8.31).
- The Agent exposes opt-in tool routing, dispatch and writeback paths.
- A bounded model↔tool loop (`core/tool_runtime.py`, `Agent.ask_with_tools`, v8.39):
  5 model rounds / 10 tool executions per run, side-effecting calls need an
  injected confirmation hook, failures reach the model only as sanitized text.

### Legacy stack
The original v3.x execution stack (planner, execution orchestrator /
pipeline / session / coordinator, skill registry, skill dispatch) is
**frozen** and read-only. New capability is added as v8.x modules
bridged to it through explicit adapters, never by modifying it.

---

## Engineering principles

- Small, additive changes; existing architecture and public APIs
  (`core.agent.__all__`) are preserved.
- Explicit constructor injection, immutable records, defensive copies,
  deterministic behavior; no hidden global state or circular imports.
- Every milestone ships with tests and passes the four verification
  gates in `AUTONOMOUS_BUILD_PROTOCOL.md` §11 before it is recorded as
  complete. Tests are never weakened, skipped or removed to make a suite
  pass.

---

## Repository structure

```
MARK-L/
├── core/
│   ├── agent/                  # Agent composition root and managers
│   ├── ai_*.py, *_provider.py  # provider-neutral AI layer and transports
│   ├── context_*.py, memory_*.py, token_counter.py, conversation_history.py
│   ├── planning_engine.py, task_graph.py, goal_manager.py,
│   │   execution_planner.py, pipeline_*.py, plan_projection.py,
│   │   stage_dispatch.py, step_lifecycle.py, lifecycle_reflection.py
│   ├── execution_failure.py, failure_taxonomy.py
│   ├── tool_*.py, skill_tool_adapter.py
│   └── (frozen legacy v3.x modules)
├── tests/                      # pytest suite for every module and milestone
├── docs/TECHNICAL_DEBT.md      # deferred work, not to be built early
├── CLAUDE.md                   # operational entry point for AI agents
├── MARK-L.md                   # master governance
├── AUTONOMOUS_BUILD_PROTOCOL.md  # verification gates, STOP conditions, reports
├── ROADMAP.md                  # living checkpoint and milestone history
├── THIRD_PARTY_NOTICES.md      # origin and license of inherited components
└── main.py, ui.py, actions/, dashboard/, memory/, skills/
                                # inherited desktop runtime (see below)
```

---

## Getting started

```bash
pip install -r requirements.txt
python -m pytest        # run the full suite
```

The v8.x architecture is developed and verified through the test suite.
Connecting it to the production runtime is a required completion
requirement of the EDITH Completion Contract
(`docs/EDITH_COMPLETION_CONTRACT.md`) and has not started; voice and UI
features beyond that integration remain deferred (see `ROADMAP.md` and
`docs/TECHNICAL_DEBT.md`).

---

## Development and continuation

- Start from `CLAUDE.md`, then `MARK-L.md`, `AUTONOMOUS_BUILD_PROTOCOL.md`
  and `ROADMAP.md`.
- The repository — code, tests and git history — is the only source of
  truth.
- Work one milestone at a time, as recorded in `ROADMAP.md`; deferred
  ideas stay in `docs/TECHNICAL_DEBT.md` until their milestone.
- Each milestone ends with a checkpoint report and a verified commit.

---

## Inherited components

Parts of this repository — the desktop runtime (`main.py`, `ui.py`,
`actions/`, `dashboard/`, `memory/`, `skills/`) and some legacy `core/`
modules — are derived from an imported base snapshot and remain under
their original license terms. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for their origin,
license and the list of affected files.
