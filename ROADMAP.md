# MARK-L Roadmap

> Project identity: EDITH · Repository: MARK-L
> Current checkpoint: **v8.25 complete** · Active milestone: **none** · Next discovered: **none — open decision recorded below**
> Verified suite at checkpoint: **1801 passed, 0 failed, 0 errors, 0 skipped**

This document is the single source for milestone status and a **living
checkpoint**: it records completed milestones, the current checkpoint and
verified test state, the active milestone, the next discovered milestone
(with justification) and deferred areas. It is a history, not a ceiling —
when no milestone is defined, `AUTONOMOUS_BUILD_PROTOCOL.md` §25 discovers,
audits and records the next justified one here as NOT STARTED before any
implementation. Governance lives in `CLAUDE.md`, `MARK-L.md` and
`AUTONOMOUS_BUILD_PROTOCOL.md`; deferred ideas live in
`docs/TECHNICAL_DEBT.md`.

---

## Current Status

| Area | State |
|---|---|
| Legacy v3.x architecture (foundation, agent, planning, execution) | ✅ Complete — **frozen** |
| v4.x request lifecycle | ✅ Complete |
| v5.x controlled skill dispatch / execution / memory / reflection / learning | ✅ Complete |
| v6.x AI provider abstraction + registry | ✅ Complete |
| v7.x real providers, AIService, conversation history, context manager | ✅ Complete |
| v8.4–v8.10 Foundation stores + Agent bridge | ✅ Complete |
| v8.11–v8.19 tool stack (interface → registry → adapter → router → Agent chain) | ✅ Complete |
| v8.20 tool-chain writeback | ✅ Complete |
| v8.21 legacy plan → Foundation projection adapter | ✅ Complete |
| v8.22 pipeline-stage tool dispatch | ✅ Complete |
| v8.23 pipeline run status recording | ✅ Complete |
| v8.24 projection-run writeback | ✅ Complete |
| v8.25 goal/plan lifecycle reflection | ✅ Complete |
| Voice / UI integration, provider tool-calling, persistence, streaming, permissions | ⏳ Deferred (see `docs/TECHNICAL_DEBT.md`) |

---

## Completed

### Legacy foundation (v3.x — frozen)
- Memory Engine (legacy), Skill Registry, Problem Solver, Identity Engine
- Agent composition root; Context / History / Knowledge / Learning /
  Memory Index / Reflection / Reasoning managers
- Planning Engine (`core.planner`) and planning integration
- Planner → ProblemSolver adapter, Execution Orchestrator, Execution
  Pipeline, Execution Session / Progress / Result / Event / Coordinator
- Request lifecycle, context integration, execution-result integration
- Architecture-freeze validation suite

### v4.x — Request lifecycle
- `execute_request` (goal → planning → session → coordinator → ProblemSolver context → `ExecutionResult`)
- Skill-registry check (read-only)

### v5.x — Controlled skill runtime
- v5.0 `SkillDispatchDecision` (`core.skill_dispatch`)
- v5.1 controlled skill execution via `skill_registry.dispatch`
- v5.2 memory writeback · v5.3 reflection · v5.4 learning

### v6.x — AI provider abstraction
- `AIProvider` protocol, `AIRequest` / `AIResponse`, `StaticMockProvider`
- `AIProviderRegistry`

### v7.x — Real providers and conversation
- v7.0–v7.3 OpenAI / Claude / Gemini / Ollama transports (lazy, injectable)
- v7.4 Agent → `AIService` integration
- v7.5 `ConversationHistory` · v7.6 context-manager layer

### v8.x — Foundation stores
- v8.4 `PlanningEngine` (`core.planning_engine`) · v8.5 `TaskGraph` · v8.6 `GoalManager`
- v8.7 `ExecutionPlanner` · v8.8 `PipelineEngine` · v8.9 `PipelineRunManager`
- v8.10 Foundation → Agent bridge (six optional constructor dependencies)
- v8.11 snapshot/clear integration — **skipped** (audited: not justified; stores are individually clearable)

### v8.x — Tool stack
- v8.11 `ToolInterface` / `ToolRequest` / `ToolResult` / `ToolError` / `StaticMockTool`
- v8.12 `ToolRegistry`
- v8.13 Skill → Tool adapter (`adapt_skill_manifest`, `SkillTool`)
- v8.14 `ToolRouter`
- v8.15 Agent ↔ Tool bridge (`tool_registry`, `tool_router` injection)
- v8.16 `Agent.execute_request_with_tool_routing` (opt-in single-tool route)
- v8.17 `ToolDispatchDecision` / `build_tool_dispatch_decision` (`core.tool_dispatch`)
- v8.18 Tool execution chain (decisions → `ToolRequest` → `ToolRouter` → `ToolResult`)
- v8.19 Tool result integration — public contract
  `Agent.execute_request_with_tool_dispatch(goal, *, project, metadata)
   -> (ExecutionResult, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...])`
- v8.20 Tool-chain writeback — `Agent.execute_request_with_tool_dispatch_writeback`
  layering the existing memory / reflection / learning writes (v5.2–v5.4 mirror,
  `cause="controlled_tool_dispatch"`, `ToolResult.output` recorded) over the tool chain

### v8.x — Foundation projection
- v8.21 Legacy Plan → Foundation Projection Adapter — `core/plan_projection.py`
  (`PlanProjection`, `project_execution_plan`) and additive
  `Agent.project_request(goal) -> (ExecutionPlan, PlanProjection)`.
  - **Purpose:** give the v8.4–v8.10 Foundation stores their first producer by
    projecting the legacy `core.planner.ExecutionPlan` into them; no execution.
  - **Projection order:** pre-flight → Foundation `Plan` + `Step`s → `TaskGraph`
    nodes → dependency edges → `GoalRecord` (with references) → `ExecutionMapping`
    → `PipelineRecord`. A write-side adapter / deterministic projection
    coordinator — **not** a pure function.
  - **IDs:** every Foundation record gets a fresh store-generated id; the only
    legacy id reused is `Task.id → Step.id` (plan-scoped, never globally keyed).
  - **Traceability:** `Node.metadata = {task_id, plan_id}`,
    `ExecutionMapping.metadata = {legacy_plan_id, legacy_goal_id}`,
    `GoalRecord.tags = (legacy goal id,)`, `PlanProjection.task_to_node`.
  - **Order:** `ordered_node_ids` is always passed explicitly (legacy
    `execution_order()` translated through `task_to_node`); the shared graph's
    other nodes never leak into a projection.
  - **`graph_reference`:** the projected Foundation `plan_id` (the shared
    `TaskGraph` has no identity; the plan id tags the projected subgraph).
  - **Atomicity:** none — pre-flight validates before the first write; a later
    store exception propagates and earlier records remain (no rollback).
  - **Re-projection:** not idempotent; each projection creates an independent,
    fully traceable record set.
  - **Excluded:** execution, `PipelineRun` creation, status transitions, tool
    routing, writeback, `ToolRequest` changes, any frozen-module change.
- v8.22 Pipeline-Stage Tool Dispatch — `core/stage_dispatch.py`
  (`build_stage_dispatch_decisions(pipeline, *, task_graph, registry, context)`)
  and additive `Agent.execute_projection_with_tool_dispatch(goal, *, project)
  -> (PlanProjection, tuple[ToolDispatchDecision, ...], tuple[ToolResult, ...])`.
  First request path running end-to-end on v8.x architecture: legacy plan →
  v8.21 projection → `PipelineRecord.stages` → one decision per stage
  (`task_id` from `Node.metadata["task_id"]`, `tool_name` from `Node.title`,
  gated by `tool_registry.has`) → `ToolRequest` → `ToolRouter` → `ToolResult`.
  Every stage is dispatched in stage order (`depends_on` is descriptive); no
  `PipelineRun`, no writeback, no legacy coordinator. Verified: 37 focused,
  full suite 1719.
- v8.23 Pipeline Run Status Recording — additive
  `Agent.execute_projection_with_run_status(goal, *, project)
  -> (PlanProjection, PipelineRun, decisions, results)`. First producer of
  the v8.9 `PipelineRunManager`: `create_run(pipeline_id)` (CREATED) → RUNNING
  before the first route → COMPLETED after the loop, or FAILED when a tool
  raises, with the **same exception re-raised unchanged** (bare `raise`; no
  wrapping). Run metadata `{project, goal_id, mapping_id}`. Empty / all-skipped
  pipelines complete; no run is created if projection fails; a manager wired to
  a different engine fails loudly (v8.10 non-reconciliation). No per-stage
  status, no retries, no writeback. Verified: 24 focused, full suite 1743.
- v8.24 Projection-Run Writeback — additive
  `Agent.execute_projection_with_writeback(goal, *, project)
  -> (PlanProjection, PipelineRun, decisions, results)`: the v8.20 writeback
  layering (memory `record_outcome` with `cause="controlled_tool_dispatch"` →
  reflection → learning, one layer at a time, per dispatched decision paired
  with its `ToolResult`) over the v8.23 run-status path, with `run_id` added
  to learning metadata. No writes on skip / failure / projection error; no
  Goal/Plan status transitions. Verified: 20 focused, full suite 1763.
- v8.25 Goal/Plan Lifecycle Reflection — `core/lifecycle_reflection.py`
  (`reflect_execution_started`, `reflect_execution_completed`; existing
  `update_goal` / `update_plan` only) and additive
  `Agent.execute_projection_with_lifecycle(goal, *, project)` returning the
  v8.23/v8.24 4-tuple. **Locked semantics** (project decision): Goal/Plan =
  "what are we trying to accomplish", PipelineRun = "what happened in this
  attempt". Order: projection → Goal ACTIVE, Plan ACTIVE → run RUNNING → tools
  → run COMPLETED → Plan COMPLETED, Goal COMPLETED → v8.24 writeback. A FAILED
  run leaves Goal/Plan **ACTIVE**, writes nothing, re-raises the original
  exception; all-skipped runs complete normally. No new `GoalStatus` /
  `PlanStatus` values, no transition state machine, `PipelineRunStatus`
  unchanged, no meaning assigned to PAUSED/CANCELLED/READY/ARCHIVED.
  Behaviour-preserving refactor: the v8.23 run body and v8.24 writeback body
  moved into private helpers `_run_projected_pipeline` / `_record_tool_outcomes`
  shared by v8.23, v8.24 and v8.25 (structural guards retargeted; semantics
  unchanged). Verified: 38 focused, full suite 1801.

Legacy and tool runtimes are intentionally **parallel**: the legacy
skill chain is unchanged; the tool chain is opt-in.

---

## Current Checkpoint

**v8.25 — Goal/Plan Lifecycle Reflection: COMPLETE.**

- Full suite: 1801 passed, 0 failed, 0 errors, 0 skipped.
- Frozen legacy modules: zero diff; `core/goal_manager.py`,
  `core/planning_engine.py`, `core/pipeline_run.py` and every other v8.x
  module unchanged (only `core/agent/__init__.py` and the new leaf module).
- The Foundation-native vertical now covers goal → projection → stage
  dispatch → run status → lifecycle reflection → writeback.

---

## Active Milestone

None.

## Next Discovered Milestone

_(Filled by architecture-driven discovery, `AUTONOMOUS_BUILD_PROTOCOL.md`
§25. Recorded as NOT STARTED with objective, justification, prerequisites,
exclusions and verification before implementation begins.)_

### v8.22 — Pipeline-Stage Tool Dispatch — **COMPLETE** (moved to history above; kept here as the discovery record)

_Discovered autonomously under `AUTONOMOUS_BUILD_PROTOCOL.md` §25 after the
v8.21 checkpoint; version derived per §25.2 (v8.21 → v8.22). A contract audit
(§25 "CONTRACT / PREREQUISITE AUDIT") must precede implementation._

**Objective.** Give the v8.21 projection its first consumer: an opt-in Agent
method that runs the existing tool chain over a projected `PipelineRecord`'s
stages instead of the legacy coordinator's ready descriptors —
`goal → project_request → PipelineRecord.stages → ToolDispatchDecision per
stage (gated by tool_registry.has) → ToolRequest → ToolRouter → ToolResult`.

**Architectural justification (repository evidence).**
- Dependency chain: v8.4–v8.10 stores → v8.21 projection produces
  `PipelineRecord` stages, but nothing consumes them; the v8.17–v8.20 tool
  chain still starts from the frozen legacy coordinator. Joining the two is the
  smallest missing layer on the established
  `projection → stages → dispatch` path.
- Data already lines up without new contracts: `PipelineStage.node_id` →
  `TaskGraph.get_node().title` equals the legacy task description, which is
  exactly the `tool_name` the legacy chain dispatches; `Node.metadata["task_id"]`
  supplies `ToolDispatchDecision.task_id`; stage order is the legacy
  `execution_order()` (v8.21 explicit ordering); `PipelineStage.depends_on` is
  documented as descriptive only (v8.8), so sequential dispatch in stage order is
  the model's own semantics.
- Reuses unchanged: `build_tool_dispatch_decision`, `ToolRequest`,
  `ToolRouter`, the v8.19 result contract
  `(ExecutionResult | projection, decisions, results)` shape to be fixed by the
  audit; no new abstraction.
- Advances EDITH: first end-to-end request path that runs entirely on v8.x
  Foundation + tool architecture, the prerequisite for recording run state
  (dormant `PipelineRunManager`, v8.9) in a later milestone.

**Prerequisites (all present).** v8.21 `Agent.project_request`,
`PipelineEngine.get_pipeline`, `TaskGraph.get_node`, `core.tool_dispatch`,
`Agent.tool_router` / `tool_registry` (v8.15), v8.19 chain semantics
(skip vs dispatch, exact identity, exception propagation, stop at first
failure).

**Expected boundary.** Thin additive Agent method (composition root only) or,
if the audit finds non-trivial stage→decision translation, one small leaf
module (`core/stage_dispatch.py`-style) depending only on `core.tool_dispatch`,
`core.pipeline_engine`, `core.task_graph`. No changes to any frozen module, any
v8.x store, the tool stack, or `Agent.__all__`.

**Explicit exclusions.** No `PipelineRun` creation or status transitions, no
readiness evaluation or task marking, no writeback (a later layer, mirroring
v8.20), no legacy-chain change, no `ToolRequest` context, no retries /
fallback / permissions / async / persistence, no replacement of the legacy
planner.

**Verification.** Focused tests for stage→decision mapping (task_id/tool_name
from node metadata/title, order = stages, skip/dispatch gating, exact
request/result identity, exception propagation and stop-at-first-failure,
empty pipeline, re-projection isolation, injected-store wiring), legacy
isolation spies (no `skill_registry`/`skill_dispatch`/coordinator calls),
Agent guards (exact-import sets, accessor scans, `__all__`), full suite with
exact counts, architecture/cycle checks, `git diff --check`.

### v8.23 — Pipeline Run Status Recording — **COMPLETE** (discovery record)

_Discovered autonomously (§25) after the v8.22 checkpoint; version per §25.2
(v8.22 → v8.23). Contract audit performed against `core/pipeline_run.py`
before implementation._

**Objective.** Give the dormant v8.9 `PipelineRunManager` its first producer:
an opt-in Agent method that wraps the v8.22 stage dispatch in a `PipelineRun`
— `create_run(pipeline_id)` (CREATED) → `RUNNING` before the first routing →
`COMPLETED` after the loop, or `FAILED` when a tool raises (the original
exception is re-raised unchanged after the status is recorded).

**Architectural justification.** `PipelineRunManager` (v8.9) exists with a
fixed status vocabulary and `ALLOWED_TRANSITIONS`, is wired into `Agent`
(v8.15) and has zero producers; v8.22 now produces exactly the
`pipeline_id` it validates against and the success/failure events its
`COMPLETED`/`FAILED` statuses describe. Recording run state is the next
layer of the established `projection → stages → dispatch → run` chain and
is the prerequisite for any later per-stage or resumable execution.

**Prerequisites (all present).** v8.22 `execute_projection_with_tool_dispatch`
semantics, `PipelineRunManager.create_run/update_run` with
`ALLOWED_TRANSITIONS` (CREATED→RUNNING→COMPLETED|FAILED),
`Agent.pipeline_run_manager` wired to `Agent.pipeline_engine` (v8.10/v8.15
non-reconciliation applies: a manager wired to a different engine rejects
the run — fail loudly).

**Boundary.** One additive Agent method reusing `project_request`,
`build_stage_dispatch_decisions` and the v8.18 routing loop; the only new
construct is a `try/except BaseException` that records `FAILED` and
**re-raises the same exception** (no swallowing, no wrapping). No new module
unless the audit shows the status wrapping deserves one.

**Exclusions.** No per-stage status (the v8.9 model is run-level), no
readiness, no retries, no cancellation mechanics, no writeback, no legacy
change, no `PipelineRun` model change.

**Verification.** Status sequence on success / empty pipeline / all-skipped /
failure; run metadata; run references the projected pipeline; exception
identity preserved; no run when projection fails; manager wired elsewhere
fails loudly; legacy isolation; guards; full suite; `git diff --check`.

### v8.24 — Projection-Run Writeback — **COMPLETE** (discovery record)

_Discovered autonomously (§25) after the v8.23 checkpoint; version per §25.2._

**Objective.** Complete the Foundation-native vertical path with the
established writeback layer: an opt-in Agent method over
`execute_projection_with_run_status` that, for each dispatched decision paired
with its `ToolResult`, performs the same three existing writes as v8.20
(memory `record_outcome` with `cause="controlled_tool_dispatch"`, reflection,
learning) — one layer at a time, in v5.2→v5.4 order — adding the `run_id`
to the learning metadata now that a run exists. Nothing is written for skipped
stages or after a failure (the FAILED run and the exception propagate first).

**Architectural justification.** Every other request path ends in the
writeback layer (legacy v5.2–v5.4; tool chain v8.20). The projection path
(v8.21 → v8.22 → v8.23) is the only vertical without it — an incomplete
vertical path through established architecture. All prerequisites exist
(v8.23 results/run, `record_problem_outcome`, `ReflectionManager`,
`LearningManager`); the layer is additive glue in the composition root with a
direct precedent to mirror, and it makes the Foundation-native path
functionally complete relative to the legacy and tool chains.

**Boundary.** One additive Agent method; no new module; no changes to v8.20,
stores, tool stack or frozen modules. Returns the v8.23 4-tuple unchanged.

**Exclusions.** No Goal/Plan status transitions (see open decision below),
no per-stage status, no retries, no legacy change, no writeback on failure.

**Verification.** Mirror of the v8.20 suite over the projection path: exact
write counts per dispatch, ordering M→R→L, pairing with results, run_id in
learning metadata, no writes on skip/failure/empty, legacy isolation, run
status still COMPLETED, guards, full suite, `git diff --check`.

### Discovery after v8.24 — resolved by the project owner → v8.25 (record kept)

Architecture discovery after the v8.24 checkpoint found one evidence-backed
candidate and no others that satisfy §25.1:

**Candidate: Goal / Plan lifecycle reflection.** The projected `GoalRecord`
and Foundation `Plan` stay `DRAFT` forever; `GoalStatus` / `PlanStatus`
vocabularies and `update_goal` / `update_plan` exist (v8.4 / v8.6, "this
engine never transitions them" — left to callers), and the run outcome
(v8.23) is now available to drive them. **Blocked by an unresolvable
decision:** neither vocabulary has a failure state (`PlanStatus`:
DRAFT/READY/ACTIVE/COMPLETED/ARCHIVED; `GoalStatus`:
DRAFT/ACTIVE/PAUSED/COMPLETED/CANCELLED). Repository evidence cannot say
whether a FAILED run should leave the plan/goal ACTIVE, map to
PAUSED/CANCELLED/ARCHIVED, or require a new status value (a data-model
change to completed stores). This is a product/architecture decision
(§13 *Architectural ambiguity*).

**Rejected candidates (invalid grounds per §25.1):** per-stage run status
(requires changing the completed v8.9 model); structured tool arguments
(legacy `Task.metadata` is always empty — nothing to derive); tool schemas /
provider tool-calling (vision item §9, reserved v9.x, prerequisites absent);
retry / fallback (§14/§15, explicitly forbidden until authorized); migrating
`main.py` to the tool router (frozen).

**Open decision for the project owner** — answering it unblocks the next
milestone: *On a FAILED `PipelineRun`, what should the projected
`GoalRecord.status` and `Plan.status` become, and should success map to
`COMPLETED` for both?*

_Resolution (project owner, before v8.25): Goal/Plan describe intent, a run
describes one attempt — start → ACTIVE/ACTIVE; run COMPLETED →
COMPLETED/COMPLETED; run FAILED → both remain ACTIVE; no new values._

### Discovery after v8.25 — no defensible milestone; STOP (protocol §13)

Candidates examined against §25.1:

- **Step-level lifecycle reflection.** `Step.status` shares the `PlanStatus`
  vocabulary and is never transitioned (steps stay DRAFT; `update_plan(steps=)`
  could replace them). Blocked by the same class of decision as v8.25 but at
  step granularity: what a *skipped* stage's step becomes, what the steps after
  a failing stage become, and whether a step that ran before the failure is
  COMPLETED while its plan stays ACTIVE. Not derivable from the repository —
  **open decision** (below).
- **`PipelineRunStatus.CANCELLED` producer.** No cancellation signal or
  initiator exists anywhere; v8.9/v8.23 explicitly excluded cancellation
  mechanics — speculative.
- **Failure writeback** (recording FAILED attempts to memory): every existing
  chain (v5.2–v5.4, v8.20, v8.24, v8.25) deliberately writes nothing on
  failure; changing that is a product decision, not an architectural gap.
- Structured tool arguments, tool schemas / provider tool-calling (§9, v9.x),
  retry/fallback (§14/§15), `main.py` migration — rejected for the reasons
  recorded after v8.24.

**Open decision for the project owner:** *Should stage outcomes be reflected
onto `Step.status`, and if so: dispatched-and-succeeded → COMPLETED? skipped →
(unchanged DRAFT | COMPLETED | ARCHIVED)? steps after a failing stage →
(unchanged | ACTIVE)? the failing step itself → (ACTIVE | unchanged)?*

---

## Frozen Modules

Read-only unless a future milestone explicitly authorizes a change:

- `core/planner.py`, `core/planner_problem_solver_adapter.py`,
  `core/planner_execution_orchestrator_adapter.py`
- `core/execution_orchestrator.py`, `core/execution_pipeline.py`,
  `core/execution_session.py`, `core/execution_coordinator.py`,
  `core/execution_result.py`, `core/execution_progress.py`,
  `core/execution_event.py`
- `core/skill_registry.py`, `core/skill_dispatch.py`, `skills/*`, `main.py`
- Completed v8.x modules are stable; change them only when a milestone
  requires it and the architecture tests are updated by sanctioned
  minimal changes.

---

## Architecture Policy

- Legacy v3.x architecture is complete and frozen.
- The v8.x Foundation / tool stack is the additive extension surface;
  new capability is bridged through explicit adapters and dependency
  injection, never by modifying frozen code.
- Do not introduce new architectural layers except to fulfil a defined
  milestone or fix a proven defect. Prefer extending existing v8.x
  modules; do not reuse legacy abstractions where that couples the two
  runtimes.
