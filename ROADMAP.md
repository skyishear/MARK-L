# MARK-L Roadmap

> Project identity: EDITH · Repository: MARK-L
> Current checkpoint: **v8.42 complete** · Active milestone: **none** · Next planned: **v8.43 Production Run Recording — NOT STARTED** (production-runtime integration plan v8.41–v8.45, owner-authorized 2026-10-06)
> Verified suite at checkpoint: **2766 passed, 0 failed, 0 errors, 0 skipped**

This document is the single source for milestone status and a **living
checkpoint**: it records completed milestones, the current checkpoint and
verified test state, the active milestone, the next discovered milestone
(with justification) and deferred areas. It is a history, not a ceiling —
when no milestone is defined, `AUTONOMOUS_BUILD_PROTOCOL.md` §25 discovers,
audits and records the next justified one here as NOT STARTED before any
implementation. Governance lives in `CLAUDE.md`, `MARK-L.md` and
`AUTONOMOUS_BUILD_PROTOCOL.md`; the project-level definition of "EDITH
complete" lives in `docs/EDITH_COMPLETION_CONTRACT.md`; deferred ideas live
in `docs/TECHNICAL_DEBT.md`.

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
| v8.26 step lifecycle reflection | ✅ Complete |
| v8.27 execution failure writeback | ✅ Complete |
| v8.28 failure writeback expansion (v8.24) + shared failure normalization | ✅ Complete |
| v8.29 tool-chain failure writeback (v8.20) | ✅ Complete |
| v8.30 execution failure taxonomy | ✅ Complete |
| v8.31 tool catalog (metadata + schema validation) | ✅ Complete |
| v8.32 resume a failed lifecycle run | ✅ Complete |
| v8.33 bounded in-run retry | ✅ Complete |
| v8.34 context policy and history trimming | ✅ Complete |
| v8.35 token budgeting | ✅ Complete |
| v8.36 system channel and opt-in memory injection | ✅ Complete |
| v8.37 neutral tool-calling types | ✅ Complete |
| v8.38 first provider tool-call normalization (Anthropic) | ✅ Complete |
| v8.39 tool runtime loop (model↔tool execution loop, `core/tool_runtime.py`) | ✅ Complete |
| v8.40 tool calling on the remaining providers (OpenAI, Gemini, Ollama) | ✅ Complete |
| v8.41 production tool bridge (P2, P3: Gemini Live adapter, tool registration; `core/live_tools.py`) | ✅ Complete |
| v8.42 production memory bridge (P4; `core/production_memory.py`) | ✅ Complete |
| v8.43 production run recording (P5) | 🔲 Planned — NOT STARTED |
| v8.44 production runtime wiring (P1, V5; scoped unfreeze of `main.py`) | 🔲 Planned — NOT STARTED |
| v8.45 contract closure (V7 dependencies, V9 notices, V4 `main.py` pin, A3 / A5 records) | 🔲 Planned — NOT STARTED |
| Streaming, persistence, full permission system, voice/UI features beyond P1–P5, and the other `docs/TECHNICAL_DEBT.md` ideas | ⏳ Deferred (see `docs/TECHNICAL_DEBT.md`; promoted only by a contract amendment) |

---

## Completion Contract

EDITH is complete only as defined in `docs/EDITH_COMPLETION_CONTRACT.md`
(Definition P — production-complete — ratified by the project owner on
2026-10-05). That document is authoritative; this section does not restate
it.

- The v8.x stack is not yet connected to the production runtime
  (`main.py` constructs an `Agent` but does not use it), so completing
  v8.39 alone does not complete the project.
- Requirements, owner decisions and the dated status snapshot live in the
  contract. This roadmap stays the living milestone / checkpoint record.
- Contract V4 is partial: `tests/test_frozen_content.py` pins the content of 15
  of the 16 frozen files; `main.py` stays unpinned until the owner resolves the
  contract §13 exception.
- When the contract is satisfied, this file records "Contract v1 satisfied
  at commit `<hash>`" with the owner's sign-off.

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
- v8.26 Step Lifecycle Reflection — new leaf `core/step_lifecycle.py`
  (`reflect_step_reached` / `reflect_step_completed` / `reflect_step_skipped`;
  `PlanningEngine.get_plan` + whole-tuple `update_plan(steps=...)` only,
  steps targeted by `plan_id` + `Step.id`) and an opt-in keyword
  `reflect_steps=False` on the shared `_run_projected_pipeline`, set only by
  `execute_projection_with_lifecycle`. Implements the recorded Step.status
  contract: reached dispatched stage ACTIVE → COMPLETED on success; reached
  skipped stage DRAFT → ARCHIVED; failing step stays ACTIVE; unreached steps
  stay DRAFT (6a); v8.22–v8.24 leave steps DRAFT. No new status type or
  values, no store transition machine, no `TaskState`, no re-execution
  handling; Goal/Plan/run semantics, exception propagation and v8.24
  writeback unchanged. Sanctioned structural pin updates: the Agent import
  allowlists (+`core.step_lifecycle`, as v8.25 did for its leaf), the
  `_run_projected_pipeline` call-set pin (+3 `reflect_step_*`), and the
  v8.25 goal/plan/run ordering traces (step writes now recorded explicitly).
  Verified: 41 new focused, full suite 1842.
- v8.27 Execution Failure Writeback — additive private
  `Agent._record_failure_outcome` and one `try/except BaseException`
  around the run in `execute_projection_with_lifecycle` (the only caller).
  **Contract** (owner decision after the v8.26 audit: retry/resume NO,
  failure writeback YES): exactly one structured writeback per failed
  execution attempt through the existing Memory → Reflection → Learning
  APIs — `record_outcome(cause="controlled_tool_dispatch_failure",
  outcome="failed:<ExceptionType>")`, `add_reflection(what_failed=...,
  confidence_level=0.0)`, `record_failed_pattern` — with metadata
  `{run_id, goal_id, plan_id, task_id, project, exception_type}`. It is an
  *execution* failure only if the projection's `PipelineRun` is FAILED
  (projection, lifecycle-start and pre-RUNNING failures write nothing); the
  failed stage is the single ACTIVE step (fallback: goal, `task_id=None`).
  Only the exception **type name** is stored — never its message, repr,
  args or traceback. Writeback exceptions (`Exception`) are suppressed so
  the original exception always propagates unchanged (writes are
  non-atomic). No status transition, no success record for stages
  completed before the failure, v8.22–v8.24 unchanged (still write nothing
  on failure), no retry/resume, no new statuses, no new module. Sanctioned
  test updates (owner decision): v8.25 `test_failure_no_writeback` →
  `test_failure_no_success_writeback`; `test_method_is_thin_glue` now pins
  exactly one BaseException handler (bare re-raise, calls only
  `_record_failure_outcome`) around `_run_projected_pipeline` only.
  Verified: 37 new focused, full suite 1879.
- v8.28 Failure Writeback Expansion (v8.24) + Shared Failure Normalization —
  new stdlib-only leaf `core/execution_failure.py`: frozen/slots
  `ExecutionFailure(exception_type, run_id, tool_name, project)` and
  `normalize_execution_failure(exc, *, run_id, tool_name=None, project=None)`
  (reads only `type(exc).__name__`; never message/repr/args/traceback, never
  keeps the exception). `Agent._record_failure_outcome` is now the single
  shared failure writer (lifecycle and v8.24) built on it; v8.27 records are
  unchanged (same content, key order and ACTIVE-step/goal fallback — v8.27
  content tests pass unmodified). `execute_projection_with_writeback` now
  runs the v8.23 body directly (`project_request` + `_run_projected_pipeline`
  with a caller-owned `dispatched` log, identical results to v8.23) inside
  one `try/except BaseException`: a FAILED run gets exactly one structured
  failure writeback (Memory → Reflection → Learning; failed stage = last
  dispatched decision) and the original exception is re-raised unchanged;
  writeback errors never mask it. As before, a failed attempt writes **no
  success record** for stages that succeeded earlier (success writeback runs
  only for a COMPLETED run); later stages are never dispatched or recorded;
  pre-RUNNING / projection failures write nothing. v8.20 / v8.22 / v8.23,
  statuses, stores, tool stack and providers unchanged. Sanctioned test
  updates: Agent import allowlists (+`core.execution_failure`); v8.24
  `test_failure_writes_nothing_and_run_failed` → one failure record (owner
  authorization); v8.24 delegation/call-set pins retargeted to the v8.23 body
  with a results-equivalence check; three v8.27 guards retargeted (v8.24 now
  a sanctioned caller; `exc` only passed to the normalizer, whose type-name-
  only read is pinned in `tests/test_execution_failure.py`). Verified: 50 new
  focused, full suite 1929.
- v8.29 Tool-Chain Failure Writeback (v8.20) — the v8.19 chain body is
  extracted unchanged into the private `_run_tool_dispatch_chain` (shared by
  v8.19 and v8.20, v8.25 precedent) with a caller-owned in-flight `routing`
  log (decision appended just before `ToolRouter.route`, removed when it
  returns). `execute_request_with_tool_dispatch_writeback` runs it inside one
  `try/except BaseException`: an exception raised **by `ToolRouter.route`**
  (the v8.20 execution boundary) gets exactly one structured failure
  writeback through the single shared writer `_record_failure_outcome`
  (additive `projection=None` mode) and is re-raised unchanged; failures in
  planning, session, coordination, decision building or request
  construction write nothing. No `PipelineRun`, Foundation goal or plan
  exists on this path, so `run_id`, `goal_id` and `plan_id` are **`None`**
  (the legacy session id is deterministic per goal and is not an attempt
  identity — nothing is invented); `task_id` / tool name / project come
  from the failed decision and the caller, exactly as v8.20 success records
  expose them. `ExecutionFailure.run_id` becomes `Optional[str]` (additive;
  blank strings still rejected). Same record shape and metadata keys as
  v8.27 / v8.28, whose records are unchanged; no success record for a failed
  attempt; v8.19 results and public signatures, v8.22 / v8.23, statuses,
  stores, tool stack and providers unchanged; no `PipelineRun`, retry or
  resume. Sanctioned test updates: v8.20 "failed → no write" tests (four)
  → one failure record (owner authorization); v8.20 delegation / call-set
  pins retargeted to the shared chain body; v8.19 structural guards and the
  tool-bridge router allowlist retargeted to `_run_tool_dispatch_chain`;
  v8.28 guards updated (`run_id=None` now valid; v8.20 an allowed writer).
  Verified: 36 new focused, full suite 1965.
- v8.30 Execution Failure Taxonomy — new stdlib-only leaf
  `core/failure_taxonomy.py`: `FailureCategory(str, Enum)` with stable values
  `TRANSIENT="transient"`, `PERMANENT="permanent"`,
  `INVALID_INPUT="invalid_input"`, `UNKNOWN="unknown"`, and pure
  `classify_failure(exc, rules)` — classification by **exception class
  only** (MRO, most specific first) against caller-supplied rules; never
  reads message / repr / args / traceback, stores nothing, unmatched →
  `UNKNOWN`. **TRANSIENT means "potentially temporary according to the
  classifier" — not "retry", "safe to retry", "idempotent" or
  "side-effect free".** The execution rule table is owned by the composition
  root (private `core.agent._classify_execution_failure`, built per call —
  the v8.15 "no module-level state" pin and the v8.14 "no core module
  imports the router" boundary are both respected): `ToolNotFoundError` →
  PERMANENT, `InvalidGoalError` / `PlanValidationError` → INVALID_INPUT;
  everything else — including `ToolError` (no structured category) and all
  generic Python exceptions (incl. `TimeoutError`, `ConnectionError`) — →
  UNKNOWN. **No repository exception is documented as transient, so nothing
  maps to TRANSIENT** (limitation; the plan's `TransientToolError` was not
  introduced — the owner's v8.30 contract forbids inventing exception classes
  solely to create TRANSIENT cases; a transient signal remains a future
  decision). Foundation only: no execution path calls the classifier; no
  retry, no resume, `ExecutionFailure` and all v8.27 / v8.28 / v8.29 failure
  records unchanged, exception propagation, tool stack, stores, statuses and
  providers unchanged. Sanctioned test updates: Agent import allowlists
  (+`core.failure_taxonomy`). Verified: 54 new focused, full suite 2019.
- v8.31 Tool Catalog — new stdlib-only leaf `core/tool_catalog.py`
  (metadata + schema validation only; no importer yet, no existing file
  changed). Frozen/slotted `ToolSpec(name, description, parameters,
  idempotent=False, side_effects=True, model_invocable=False)` — most
  restrictive defaults, data only (nothing acts on them). `parameters` is a
  **declaration** validated at construction by the pure
  `validate_parameters_schema` against a bounded JSON-Schema subset (root
  `type: "object"`; types object / array / string / number / integer /
  boolean; `description`; object `properties` / `required` (unique, present
  in properties) / `additionalProperties` (bool); array `items`; scalar
  `enum` (non-empty, unique, type-consistent); any other keyword, keyword on
  the wrong type or type union → `InvalidToolSchemaError(ValueError)` with a
  path, nothing repaired) and stored as a deep read-only copy (mappings
  behind `MappingProxyType`, arrays as tuples — JSON-equivalent, same keys,
  order and values). `ToolCatalog` (`register` / `get` / `list`) follows the
  `ToolRegistry` conventions: independent instance with an `RLock`,
  insertion order, same-object re-registration a no-op, a different spec
  under the same name → `ToolSpecAlreadyRegisteredError(ValueError)`,
  unknown `get` → `None`, tuple snapshots. The catalog is separate from the
  execution registry: no spec ⇒ no metadata ⇒ not model-invocable and not
  eligible for any future catalog-driven decision; `ToolInterface`,
  `ToolRequest`, `ToolResult`, `ToolError`, `ToolRegistry`, `ToolRouter`,
  the Agent and every execution path unchanged. No tool calling, retry,
  resume, confirmation or provider code. Verified: 78 new focused, full
  suite 2097.
- v8.32 Resume a Failed Lifecycle Run — new public
  `Agent.resume_failed_run(run_id)` (plus read-only `_prepare_resume`) and an
  Agent-owned, empty-by-default `ToolCatalog` exposed as `Agent.tool_catalog`
  (no constructor parameter: the v8.15 / v8.21 signature pins fix it). All
  refusals happen **before** any run is created: unknown run → `KeyError`;
  not FAILED (COMPLETED / CREATED / RUNNING / CANCELLED), not a lifecycle
  attempt (its Goal / Plan not ACTIVE — e.g. a v8.23 / v8.24 run),
  unresolvable pipeline / mapping / plan / goal, or a non-resumable failed
  ACTIVE step → `ValueError`. The resume creates a **new** `PipelineRun` on
  the **same** pipeline (no new pipeline, mapping or projection) with
  metadata `{project, goal_id, mapping_id, resumes_run_id}` (`project` taken
  from the failed run); the failed run is never modified. Execution reuses
  the shared `_run_projected_pipeline` (additive `skip_task_ids` /
  `resumes_run_id`, both off by default) with freshly rebuilt decisions in
  pipeline order. **Locked owner decisions:** **O4** — the failed ACTIVE
  step is re-dispatched only if its `ToolSpec` is `idempotent=True`; a
  missing spec or `idempotent=False` refuses the resume, no override;
  **O6** — ARCHIVED steps remain ARCHIVED and are never re-checked against
  the registry or re-dispatched; **O7** — stages COMPLETED in an earlier
  attempt are skipped and get no new success writeback (only stages newly
  executed in the resumed run do). Additional conservative rule (edge not
  covered by O4/O6/O7): a failed ACTIVE step whose tool is no longer
  registered refuses the resume (it would otherwise be relabelled ARCHIVED,
  "not executed"). DRAFT steps execute with v8.26 semantics (ACTIVE →
  COMPLETED, ARCHIVED if unregistered, ACTIVE on failure, later steps stay
  DRAFT). Success → run COMPLETED, Plan / Goal COMPLETED (existing lifecycle
  reflection), success writeback for this run's stages; failure → run
  FAILED, Goal / Plan ACTIVE, exactly one failure writeback with the new
  `run_id`, original exception re-raised unchanged. A resumed attempt that
  fails can itself be resumed. No retry, no new status or transition, no
  change to v8.20 / v8.22 / v8.23 / v8.24, the registry, router, catalog or
  stores. Sanctioned test updates: Agent import allowlists
  (+`core.tool_catalog`); registry/router consultation allowlist
  (+`_prepare_resume`, reads the registry only); "no resume surface" guards
  and the step-reflection / failure-writer caller sets (+`resume_failed_run`,
  retry still forbidden); two v8.31 "no consumer yet" catalog guards.
  Verified: 37 new focused, full suite 2134.
- v8.33 Bounded In-Run Retry — private `Agent._route_with_transient_retry`
  wrapped around the unchanged `ToolRouter.route`, opted into only by the
  lifecycle path (`execute_projection_with_lifecycle`) and
  `resume_failed_run` through an additive `retry_transient=False` flag on the
  shared `_run_projected_pipeline`; every other path routes exactly once.
  **Locked owner policy O5:** TRANSIENT failures only; at most **2 retries**
  after the initial attempt, i.e. **at most 3 tool invocations per step**
  (hard bound: a literal `for` over three attempts, no `while`); **0-second
  delay** (no sleep, backoff, scheduler, timer, queue or async); the step
  stays **ACTIVE** during retry and becomes COMPLETED only after a
  successful invocation (whose exact `ToolResult` is used); the **final
  attempt's exception is re-raised unchanged** (same object); **exactly one
  failure writeback** after exhaustion or a non-retryable failure —
  intermediate failures never leave the retry method, so they produce no
  writeback, no run-status change and no new run; **UNKNOWN is never
  retried**; `BaseException` that is not an `Exception` is never retried.
  **Transient signal (explicit, type-based):** new
  `TransientToolError(ToolError)` in `core/tool_interface.py` (the
  owner-approved plan's signal, withheld in v8.30 for lack of a consumer),
  mapped to TRANSIENT in the Agent's rule table — the only TRANSIENT
  mapping; classification still walks the class MRO against explicit
  rules and never reads message / repr / args / traceback; generic
  exceptions (incl. `TimeoutError`, `ConnectionError`) stay UNKNOWN. A
  resumed attempt retries within its one new run (no extra run per retry).
  Router, registry, catalog, taxonomy leaf, statuses, lifecycle, v8.32
  O4 / O6 / O7 and failure-record format unchanged. Sanctioned test
  updates: v8.11 `ToolError` hierarchy / `__all__` pins
  (+`TransientToolError`); run-helper call set and router allowlist
  (+`_route_with_transient_retry`); v8.30 guards ("nothing is transient",
  "execution never classifies" → only the lifecycle path classifies);
  "no retry surface" guards (+ the one retry helper). Verified: 51 new
  focused, full suite 2185.
- v8.34 Context Policy and History Trimming — `core/context_manager.py`
  only (the v7.6 `ContextManager`, the documented owner of context
  shaping, `docs/TECHNICAL_DEBT.md` §2 / §6). **Locked owner policy:**
  **50 messages / 20,000 content characters**, **enabled by default**
  (`ContextManager(*, max_messages=50, max_chars=20_000)`, keyword-only,
  zero-arg compatible; the default `AIService` — hence `Agent.ask` /
  `Agent.reason` — gets the bounded view with no configuration);
  characters are `len(Message.content)` only (no roles / structure) and the
  request's new `prompt` is not counted; a history within both limits is
  returned unchanged; otherwise **complete user/assistant pairs** (or single
  messages that do not form a pair, e.g. a trailing incomplete user turn)
  are dropped oldest-first, the view never deliberately begins with an
  orphan `assistant` message, and retained messages keep their order,
  identity and content; an **oversized newest message raises the dedicated
  `ContextValidationError(ValueError)`** (sizes only in the message, never
  content) — no truncation, no silent drop, never over budget. Derived
  rule for cases the policy leaves implicit: a newest complete pair that
  cannot fit, or a newest orphan assistant message, raises the same error.
  **Canonical history is preserved:** `ConversationHistory` stays the
  source of truth and is never mutated; `prepare()` returns a bounded
  derived view. **Token budgeting is deferred to v8.35** — no token
  counting, tokenizer or budget abstraction here; no provider, `AIService`,
  Agent, tool or execution change. No existing test changed. Verified: 40
  new focused, full suite 2225.
- v8.35 Token Budgeting — new stdlib-only leaf `core/token_counter.py`
  (`TokenCounter` protocol `count(text) -> int`, provider-neutral; default
  `LocalTokenCounter`: a deterministic local lexical tokenizer — each run of
  word characters `\w+` and each other non-space character is one token;
  no network, no provider SDK, no new dependency, not a character ratio,
  not model-specific). **Locked owner decisions:** **D1** pluggable counter,
  no counting logic inside `ContextManager` (it only consumes the injected
  counter); **D2** `max_tokens = 8,192` — the **input/context** budget,
  enabled by default, unrelated to provider output caps; **D3** it covers
  **history + the request's new prompt**; **D4** no output-token
  reservation (Claude's `max_tokens=1024` output cap untouched); **D5** a
  **third independent limit** beside `max_messages = 50` and
  `max_chars = 20,000`, all enabled by default, with the v8.34 rules
  unchanged (canonical history never mutated, `ContextManager` owns
  trimming, bounded derived view, oldest complete user/assistant pairs
  dropped first, no orphan leading assistant, order and content preserved,
  newest required context that cannot fit → `ContextValidationError`, never
  truncated or silently dropped). Provider / model context windows are out
  of scope; `ContextManager` carries no provider or model identity.
  `ContextManager(*, max_messages=50, max_chars=20_000, max_tokens=8_192,
  token_counter=None)`; `prepare(history)` applies all three limits to the
  history alone; new `prepare_request(history, prompt)` applies
  `self.prepare(history)` (subclass overrides honoured) and then the token
  budget over history + prompt — a prompt that alone exceeds 8,192 tokens
  raises. `AIService.complete` now calls `prepare_request` (plumbing only,
  also without history, where it only validates the budget and the request
  is sent unchanged). Sanctioned test updates (v8.34 `test_context_policy.py`):
  fixture padding `"."` → `"x"` (same characters, one token per message, so
  the v8.34 character tests keep exercising the character limit with the
  token budget satisfied); import / identifier pins now allow the counter
  leaf and budget names while still forbidding tokenizer logic and provider
  / model names in `ContextManager`. Verified: 53 new focused, full suite
  2278.
- v8.36 System Channel and Memory Injection — **System channel:** additive
  request-level `AIRequest.system: str | None = None` (no `system` /
  `developer` `Message` role; `ConversationHistory` untouched), supplied
  through `AIService(..., *, system=None)` configuration (an explicit
  `AIRequest.system` takes precedence), mapped only inside provider modules
  and only when set — OpenAI leading `{"role": "system"}` message, Anthropic
  `system=`, Gemini `config={"system_instruction": ...}`, Ollama `system=`;
  with `system=None` every payload is byte-identical to v8.35; the
  `AIProvider` interface is unchanged. **Memory injection (opt-in):** new
  stdlib-only leaf `core/memory_context.py` (`MemoryRequest(source,
  category=None, project=None, memory_type=None)`, `select_memories`,
  `render_memories`); requested only by passing `memory=MemoryRequest(...)`
  to `AIService.complete` or the new keyword-only `Agent.ask(...,
  memory=None)` / `Agent.reason(..., memory=None)` (forwarded only when set,
  so the default call shape is unchanged); source is only
  `core.memory_engine.MemoryEngine` (injected, never imported by the leaf;
  never the legacy SQLite memory, index, reflection, learning or knowledge
  stores); query = the current prompt through the existing deterministic
  substring `recall` (optional category / project / memory_type filters use
  recall's own semantics; no ranking, embeddings or search; TTL semantics
  untouched); at most **10** eligible memories in recall order; deterministic
  render `Relevant memories:` / `- [<category>] <key>: <value>`. **O3
  (locked privacy boundary):** a memory whose `sensitive` flag is not
  exactly `False` is removed before rendering — sensitive memories never
  reach `AIRequest.system` or any provider payload; no override, no opt-in.
  **Order:** SYSTEM → MEMORY (appended to the system channel) → HISTORY →
  PROMPT. **Budget:** the 8,192-token input budget now covers system +
  memory + history + prompt (`ContextManager.prepare_context`, new
  `PreparedContext(messages, system, memory_count)`); system and prompt are
  required and never truncated; history is bounded exactly as in v8.34 /
  v8.35 with the system tokens counted alongside the prompt; memories are the
  removable part, dropped from the end until everything fits, and never cause
  history trimming; system + prompt over budget, or the newest history unit
  plus them not fitting, raises `ContextValidationError`; 50 messages /
  20,000 characters still apply to the history only. With no system and no
  memory, `AIService` runs the unchanged v8.35 path. `AIService` stays free
  of memory imports (the `MemoryRequest` is forwarded opaquely and validated
  by `ContextManager`). No tool, execution, legacy, TTL, ranking,
  persistence or dependency change. Sanctioned test updates: Agent import
  allowlists (+`core.memory_context`); v8.34 `ContextManager` import /
  `__all__` pins (+ the memory-context leaf, `PreparedContext`). Verified:
  44 new focused, full suite 2322.
- v8.37 Neutral Tool-Calling Types — **types only**: new stdlib-only leaf
  `core/tool_calling.py` (`__all__ = ["ToolCall", "ToolCallResult",
  "validate_tool_calls"]`; no importer yet; no existing file changed).
  `ToolCall(call_id, name, arguments)` — a model-proposed (untrusted) call;
  frozen / slotted; `call_id` and `name` non-blank `str`; `arguments` a
  mapping with `str` keys whose values are recursively JSON-compatible
  (`str` / `int` / `float` / `bool` / `None` / lists / tuples / `str`-keyed
  mappings; anything else → `TypeError` with a path), stored as a deep
  read-only copy (mappings behind `MappingProxyType`, arrays as tuples)
  that never aliases the caller's objects. `ToolCallResult(call_id, name,
  output: str)` — the model-facing result, correlated by `call_id` (and
  `name`, which some providers key results by); **no error / failure field
  (deferred to owner decision O2)**. `validate_tool_calls(calls)` — a
  sequence of `ToolCall` only, unique `call_id`s, original order, returned
  as a tuple (`()` when empty). **Identity:** `call_id` is required, opaque
  and stored verbatim — no id generation (the positional-id fallback for
  providers without ids is a v8.38 mapping rule). Tool declarations reuse
  the v8.31 `ToolSpec`; no `ToolDeclaration`. Deliberately distinct from
  the execution-side `ToolRequest` / `ToolResult` (their exact-field pins
  untouched). `AIRequest` / `AIResponse`, providers, `AIService`,
  `ContextManager`, `MemoryEngine`, the tool stack, catalog, Agent,
  execution and legacy modules unchanged — v8.36 behaviour byte-identical.
  Deferred: provider mapping, `AIRequest` / `AIResponse` tool fields and
  unsupported-provider behaviour (v8.38); runtime loop, authorization,
  confirmation, `ToolCall` → `ToolRequest` / `ToolResult` → `ToolCallResult`
  conversion (v8.39); auditing / writeback of tool calls (O9). Verified: 65
  new focused, full suite 2387.
- v8.38 First Provider Tool-Call Normalization — provider boundary only;
  **first provider (O8) = Anthropic / `ClaudeProvider`**. `AIRequest` gains
  the additive final field `tools: tuple[ToolSpec, ...] = ()` (collection →
  tuple, order kept, every item a `ToolSpec`, duplicate names → `ValueError`,
  `model_invocable=False` → `ValueError` — the v8.31 meaning, not
  authorization). `AIResponse` gains `tool_calls: tuple[ToolCall, ...] = ()`
  (the v8.37 type, validated by `validate_tool_calls`, response order).
  New neutral errors in `core/ai_provider.py`:
  `ToolCallNormalizationError(ValueError)` and `ToolCallingUnsupportedError`.
  **Only `core/claude_provider.py` knows the Anthropic-native format:**
  declarations `tools=[{"name", "description", "input_schema"}]` sent only
  when `request.tools` is non-empty, as plain `dict` / `list` copies of
  `ToolSpec.parameters` (never `idempotent` / `side_effects`); every
  `tool_use` block → `ToolCall(call_id=id, name, arguments=input)` in response
  order, id verbatim (no generation, no fallback); the first-text-block rule,
  unknown-block handling and the v8.36 `system=` mapping are unchanged; no SDK
  object leaves the module; `supports_tool_calling = True`. Malformed
  `tool_use` blocks (missing / invalid id or name, non-mapping input, invalid
  arguments, duplicate ids) raise `ToolCallNormalizationError` with a
  structural message (block index + reason, never model text), the
  underlying validation error kept as the cause — never repaired, invented
  or dropped. `AIService` forwards `tools` on every path and, when tools are
  offered to a provider whose neutral `supports_tool_calling` is not `True`
  (OpenAI, Gemini, Ollama, any custom provider), raises
  `ToolCallingUnsupportedError` before invoking it (fail-closed; no
  provider-specific checks; direct `provider.complete()` calls are not
  guarded in v8.38). With no tools every payload and response is identical
  to v8.36. **Deferred:** O2 tool-error representation (`ToolCallResult`
  unchanged), positional-id fallback for other providers, tool-declaration
  token accounting (v8.39), runtime loop / execution / authorization (v8.39+).
  OpenAI / Gemini / Ollama, the tool stack, catalog, context, memory, Agent,
  execution and legacy modules unchanged; no dependency added. Sanctioned
  pin updates (minimum, documented): `ToolSpec` importers (+`ai_provider`);
  `ToolCall` importers (+`ai_provider`, `claude_provider`; now checked on
  real imports, since `supports_tool_calling` is not an import); AI boundary
  field pins (additive fields); Claude's import pin (+`core.tool_calling`).
  Verified: 62 new focused, full suite 2449.
- v8.39 Tool Runtime Loop — the model↔tool execution loop, implemented under
  the owner decisions locked in `docs/EDITH_COMPLETION_CONTRACT.md` §8.1 (O1,
  O2, O9, OD-A, OD-B, OD-C and the C8 audit confirmations). New stdlib-only /
  provider-neutral leaves **`core/tool_runtime.py`** (`run_tool_loop`,
  `ToolLoopResult`, `ToolCallOutcome`, `ToolLoopExhaustedError`,
  `MAX_MODEL_ROUNDS = 5`, `MAX_TOOL_EXECUTIONS = 10`) and
  **`core/tool_context.py`** (`render_tool_context`, deterministic canonical
  JSON of the offered declarations and the run's exchanges). **Loop:** every
  round is one provider call; a response with no tool call ends the run; a
  call is refused unless its tool is offered for the run (`not_offered`) and
  registered (`not_registered`); a tool whose `side_effects` is not exactly
  `False` also needs the injected `confirm` hook to return exactly `True`
  (`confirmation_denied`; no hook: refused); otherwise the router is invoked
  once (no retry — the v8.33 per-step bound is untouched). A refusal or a tool
  failure (including a non-`str` output) reaches the model as the sanitized
  string `error: refused (<reason>)` / `error: failed (<ExceptionTypeName>)`
  in `ToolCallResult.output` and the loop continues; messages, arguments and
  tracebacks are never sent or recorded. **Limits (OD-C):** 5 model rounds and
  10 tool executions per run; a refused call is not an execution, a failing
  call is; if the 5th response still proposes calls they are not run; the 11th
  execution is refused before the hook is asked and before invoking; either
  limit raises `ToolLoopExhaustedError` carrying `limit`, `rounds`,
  `tool_executions` and the audit `outcomes`. **Audit (O9):** the run returns
  one `ToolCallOutcome(call_id, tool_name, outcome, exception_type)` per call
  and writes nothing. **Carrier (OD-B):** `ToolExchange(calls, results, text)`
  in `core/tool_calling.py` and the additive final field
  `AIRequest.tool_exchanges` (non-empty requires `tools`); exchanges stay
  loop-local and canonical history is unchanged. **Accounting (OD-A):**
  `ContextManager.prepare_context(..., tool_context=)` counts the rendering as
  required, never-truncated context inside the existing 8,192-token budget
  (history is trimmed to make room, overflow raises
  `ContextValidationError`); `AIService` forwards the exchanges on every path
  and uses the context path whenever tools are offered (a tools-only request
  is still forwarded unchanged). **Claude (provider boundary):**
  exchanges are replayed as native assistant `tool_use` / user `tool_result`
  blocks (no error flag), and a response that holds a `tool_use` block with
  `stop_reason` `max_tokens` or `refusal` raises `ToolCallNormalizationError`
  (R-2). **Agent:** one thin `Agent.ask_with_tools(provider_name, prompt, *,
  tools=None, confirm=None, memory=None)` mirroring `ask` (history is appended
  only on success; `tools` defaults to the catalog's `model_invocable` specs);
  `Agent.__all__` unchanged. Known limitation (R-1, environment-only, V6): the
  exchange carries no provider-opaque blocks, so a model whose reasoning
  blocks must be replayed may degrade a follow-up request. Sanctioned pin
  updates (minimum): `ToolCall` importers (+`tool_runtime`); `tool_calling`
  `__all__` (+`ToolExchange`); `AIRequest` field lists (+`tool_exchanges`);
  `AIService` import allowlist (+`core.tool_context`); `tool_interface`
  consumer allowlist (+`tool_runtime`); Agent import allowlists
  (+`core.tool_runtime`). Frozen legacy modules, `main.py`, the router,
  registry, catalog, other providers and `Agent.__all__` zero diff. Verified:
  138 new focused, full suite 2587.
- v8.40 Tool Calling on the Remaining Providers (owner decision OD-4b) — each
  provider module is the only place that knows its native format, in the
  v8.38 / v8.39 shape. **OpenAI:** `tools=[{"type": "function", "function":
  {name, description, parameters}}]`; `function` tool calls of the first choice
  → `ToolCall` (id verbatim, arguments parsed from the JSON string, never
  repaired); exchanges replayed as an assistant `tool_calls` message plus one
  `tool` message per result; `finish_reason` `length` / `content_filter` with
  calls, or a malformed / non-function / duplicate call, raises
  `ToolCallNormalizationError`. **Gemini:** `config["tools"] =
  [{"function_declarations": [{name, description, parameters_json_schema}]}]`
  with native `user` / `model` + `parts` contents (only on the tool path; the
  v7.2 history shape is untouched); `function_call` parts → `ToolCall` with the
  **positional-id fallback** (`call_1`, `call_2`, … when the SDK gives no id);
  replay as `function_call` / `function_response` parts; any `finish_reason`
  other than `STOP` with calls is fail-closed. **Ollama:** tools go through
  `chat` (`generate` has no tool support; requests without tools still use
  `generate`); positional ids; replay as assistant `tool_calls` + `tool`
  messages (`tool_name`); `done_reason` `length` with calls is fail-closed. All
  four built-in providers now declare `supports_tool_calling = True`; the
  `AIService` guard still rejects custom providers without it. Request shapes
  and response objects were checked against the real `openai`, `google-genai`
  and `ollama` SDK models in the build environment (not part of the suite).
  Sanctioned pin updates (minimum): the three provider isolation tests
  (+`json`, +`core.tool_calling`); `ToolCall` importers (+ the three
  providers); the "built-in unsupported providers are rejected" and "other
  providers have no capability" tests, obsolete by OD-4b, replaced by their
  v8.40 counterparts (all four built-ins declare the capability; custom
  providers without it are still rejected). Verified: 69 new focused, full
  suite 2677. Found while verifying (pre-existing, not changed here, relevant
  to V6): the Gemini history shape `{"role", "content"}` and Ollama's
  `generate(messages=...)` are not valid against the real SDKs on the
  non-tool path.
- v8.41 Production Tool Bridge (contract P2, P3; owner decisions OD-2, OD-3) —
  new `core/live_tools.py` and a behaviour-preserving extraction in
  `core/tool_runtime.py`. **`ToolRun`** now owns the per-run policy and counters
  (offered / registered gates, the `MAX_TOOL_EXECUTIONS` check before the O1
  hook, the hook for a tool whose `side_effects` is not exactly `False`, one
  router invocation, O2 strings, O9 records, the 5-round rule) and is used by
  both `run_tool_loop` and the Live adapter, so there is one implementation of
  the policy; every v8.39 test passed unchanged. **`declaration_to_spec`**
  converts a production Gemini-format declaration into a model-invocable
  `ToolSpec` (types lower-cased; any keyword outside the catalog subset fails
  loudly); only `READ_ONLY_TOOLS` (`web_search`, `system_status`,
  `recall_memory`, `solve_problem`) are marked free of side effects, every other
  production tool keeps `side_effects=True`, `idempotent=False`. All 28
  production declarations (the 26 in `main.py` and the weather / Spotify skills)
  convert. **`CallbackTool`** (`ToolInterface`) runs the production executor.
  **`LiveToolSession`** registers the declarations in the Agent's registry and
  catalog (`sync_declarations`, idempotent, returns the declarations unchanged)
  and executes each Live `tool_call` batch — one model round — through the
  router under the C8 policy (`handle_round`): the production coroutine runs on
  the session's event loop while the router runs in a worker thread; an
  executed call is answered with the production response exactly, a refusal or
  failure with the sanitized string; when a limit is reached the calls already
  handled keep their real answer and every other call of the batch (and of the
  rest of the run) gets `error: failed (ToolLoopExhaustedError)` until
  `end_run()` (the model's turn is over). `approve_requested_call` is the
  production confirmation hook (the user's spoken request is the confirmation;
  the owner-identity / PIN gate for high-risk actions stays inside the
  production executor with its guidance to the model). An optional recorder
  receives the new O9 outcomes after each round and can never break a call.
  One thin `Agent.live_tool_session(*, execute, confirm=None, recorder=None)`.
  No SDK import; router and registry are injected. Sanctioned pin updates
  (minimum): Agent import allowlists (+`core.live_tools`); `tool_catalog` /
  `tool_interface` / `tool_calling` / `tool_runtime` consumer allowlists
  (+`live_tools`); the `tool_runtime` public surface (+`ToolRun`). Verified: 48
  new focused, full suite 2725. Assumption for V6: a Live `turn_complete` is not
  sent between a `tool_call` and its tool response.

Legacy and tool runtimes are intentionally **parallel**: the legacy
skill chain is unchanged; the tool chain is opt-in.

---

## Current Checkpoint

**v8.41 — Production Tool Bridge: COMPLETE.**

- Full suite: 2725 passed, 0 failed, 0 errors, 0 skipped.
- Production changes: new `core/live_tools.py`, the `ToolRun` extraction in
  `core/tool_runtime.py`, and the thin `Agent.live_tool_session`; frozen legacy
  modules and `main.py` zero diff.
- The production tools can be registered in, and Gemini Live tool calls run
  through, the v8.x tool stack under the C8 policy. `main.py` is not wired yet
  (v8.44), so the production runtime still does not use it.

---

## Active Milestone

None.

## Next Discovered Milestone

_(Filled by architecture-driven discovery, `AUTONOMOUS_BUILD_PROTOCOL.md`
§25. Recorded as NOT STARTED with objective, justification, prerequisites,
exclusions and verification before implementation begins.)_

### v8.26 — Step Lifecycle Reflection — **COMPLETE** (moved to history above; kept here as the discovery record)

**Objective.** Reflect per-stage outcomes onto the projected Foundation
`Step.status` on the `Agent.execute_projection_with_lifecycle` path only,
exactly as fixed by the recorded Step.status contract (see "Discovery after
v8.25" below): reached step → ACTIVE, dispatched success → COMPLETED,
skipped (unregistered tool) → ARCHIVED directly from DRAFT, failing step
stays ACTIVE, steps never reached stay DRAFT.

**Architectural justification.** v8.25 reflects the execution attempt onto
Goal/Plan, but projected `Step`s stay DRAFT forever — the Foundation plan
is the only lifecycle-bearing record on the projection path that never
reflects execution. The blocking decision recorded after v8.25 is now
resolved by the project owner, and every prerequisite exists; the work is
additive glue on the lifecycle path through existing store APIs.

**Prerequisites (all present).** `Step.status: PlanStatus`
(`core/planning_engine.py`); `PlanningEngine.get_plan` /
`update_plan(plan_id, steps=...)` (whole-tuple replacement of frozen
`Step`s; status-only `update_plan` preserves steps); traceability
`Step.id == Task.id == Node.metadata["task_id"] == ToolDispatchDecision.task_id`
(v8.21 / v8.22), unique within a plan (`core/planner.py` rejects duplicate
task ids); `Agent.execute_projection_with_lifecycle` and
`_run_projected_pipeline` (v8.25).

**Boundary.** Steps are targeted by `projection.plan_id` + `Step.id` /
`decision.task_id`, never by position (stage order is
`plan.execution_order()`, `Step.index` is `plan.tasks` order). Existing
Goal / Plan / PipelineRun semantics, the re-raised exception and the v8.24
writeback are unchanged.

**Exclusions.** No new `StepStatus` type; no new `PlanStatus` values; no
transition machine inside `PlanningEngine`; no legacy `TaskState` coupling;
no change to v8.22 / v8.23 / v8.24 `Step.status` behaviour (steps stay
DRAFT there); no writeback redesign; no new per-stage execution engine; no
re-execution / idempotency implementation.

**Verification.** Focused tests per contract rule: projection DRAFT;
success → every dispatched step COMPLETED; skipped → ARCHIVED and never
observed ACTIVE; all-skipped run → Plan/Goal COMPLETED with all steps
ARCHIVED; failure → earlier steps COMPLETED/ARCHIVED, failing step ACTIVE,
later steps DRAFT (including unregistered ones — rule 6a), run FAILED,
Goal/Plan ACTIVE, original exception re-raised, no writeback; step
targeting correct when stage order differs from `Step.index`; v8.22 /
v8.23 / v8.24 leave all steps DRAFT; `PlanStatus` / `GoalStatus` /
`PipelineRunStatus` vocabularies and `ALLOWED_TRANSITIONS` unchanged;
frozen modules zero diff. Existing structural pins that the change
necessarily touches (e.g. `test_method_is_thin_glue`, and the
`lifecycle_reflection.py` AST pins if that module is extended) may only
receive sanctioned minimal updates, listed in the checkpoint report. Full
suite, `git diff --check`.

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

### Discovery after v8.25 — STOP (protocol §13); resolved by the project owner → v8.26 (record kept)

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

_Resolution (project owner, after a read-only audit and contract
validation, before v8.26) — **Step.status lifecycle contract**:_

1. Newly projected Step → DRAFT.
2. On the lifecycle execution path, when execution reaches a step/stage →
   ACTIVE.
3. Dispatched stage succeeds → COMPLETED.
4. A skipped stage whose tool is unavailable/unregistered → ARCHIVED.
5. A stage/tool execution failure leaves that step → ACTIVE.
6. Steps after a failure that were never reached remain → DRAFT.
7. A step already COMPLETED is never downgraded — an **invariant only**; no
   re-execution state machine or idempotency mechanism is introduced (every
   execution re-projects into fresh DRAFT steps today).
8. Foundation `Step.status` uses only the existing `PlanStatus` vocabulary.

_Mandatory clarifications:_

- **2a.** Step status transitions occur **only** on the
  `execute_projection_with_lifecycle` path; the v8.22, v8.23 and v8.24
  methods remain behaviourally unchanged with respect to `Step.status`.
- **4a.** A skipped stage goes directly DRAFT → ARCHIVED; it never passes
  through ACTIVE because it was never executed.
- **6a.** Rule 6 overrides rule 4: a stage never reached because an earlier
  stage failed remains DRAFT, even if its tool is unregistered.

_Semantics:_

- Step ARCHIVED means **"skipped, not executed, no success implied"** — the
  first meaning assigned to ARCHIVED (at step level only; Plan-level
  ARCHIVED remains unassigned).
- A Plan may therefore become COMPLETED while some or all of its steps are
  ARCHIVED (an all-skipped run already completes, v8.23/v8.25).
- A failing step remains ACTIVE because the architecture already represents
  unfinished intent at Goal/Plan level as ACTIVE when an attempt fails
  (v8.25).
- A step that completed before a later stage failed may remain COMPLETED
  while the `PipelineRun` is FAILED and the Plan/Goal remain ACTIVE.

_No new status values_ (no FAILED / SKIPPED): the failure and skip
outcomes are already expressible with existing values and recorded
authoritatively at run level (`PipelineRunStatus.FAILED`); adding values
would change the completed v8.4 data model, which v8.25 deliberately
avoided. _Legacy `TaskState`_ (PENDING/RUNNING/COMPLETED/FAILED/SKIPPED, in
the frozen `core/execution_orchestrator.py`) remains a separate vocabulary
and is neither imported nor mirrored (Architecture Policy: no coupling of
the two runtimes).

### Discovery after v8.26 — STOP (protocol §13); resolved by the project owner → v8.27 (record kept)

Candidates examined against §25.1 (v8.26 adds step granularity but opens no
new evidence-backed gap):

- **Retry / resume from the ACTIVE (failed) step.** v8.26 makes the failing
  step identifiable, but retry/fallback is explicitly forbidden until
  authorized (§14/§15) and rule 7 excludes re-execution handling —
  requires owner authorization (§13 *External decision*).
- **Failure writeback** (recording FAILED attempts or partially COMPLETED
  steps to memory): every chain deliberately writes nothing on failure —
  product decision, unchanged since the v8.25 discovery.
- **Producers for the remaining unassigned values** (`PlanStatus.READY`,
  Plan-level `ARCHIVED`, `GoalStatus.PAUSED` / `CANCELLED`,
  `PipelineRunStatus.CANCELLED`): no signal, initiator or consumer exists —
  speculative.
- **Readiness evaluation over `PipelineStage.depends_on`**: descriptive only
  (v8.8); stage order is fixed at projection time and nothing consumes
  readiness — speculative.
- Structured tool arguments, tool schemas / provider tool-calling (§9,
  v9.x), `main.py` migration (frozen) — rejected for the reasons recorded
  after v8.24.

**Open decisions for the project owner** — any one unblocks the next
milestone: *(a) Should a failed lifecycle attempt be retryable/resumable
from its ACTIVE step (authorizing §14/§15 retry scope)? (b) Should failed
attempts be written back to memory/reflection/learning, and in what
shape?*

_Note: "§14/§15" in the retry references above means
`docs/TECHNICAL_DEBT.md` §14 (Retry policy) / §15 (Fallback policy), both
scoped to `AIService`; `AUTONOMOUS_BUILD_PROTOCOL.md` §14 separately
forbids "retries before retry architecture"._

_Resolution (project owner, after a read-only decision audit, before
v8.27): (a) retry/resume — **NO for now** (future architecture decision;
no retry, resume, re-execution API, attempt counter, retry policy or
idempotency metadata). (b) failure writeback — **YES**: one structured
writeback per failed execution attempt through the existing
Memory → Reflection → Learning layering; no raw exception text; original
exception wins; execution state authoritative; projection failures are
not execution failures. Implemented as v8.27 (see history above)._

### Discovery after v8.27 — no defensible milestone; STOP (protocol §13)

Candidates examined against §25.1:

- **Retry / resume** — explicitly deferred by the owner (decision (a)
  above); requires a future architecture decision.
- **Consulting failure memory before projection execution**
  (`gather_context`): the v8.18 tool chain deliberately dropped that read
  because "its result was always discarded"; the projection path has no
  consumer for the context — speculative.
- **Failure writeback on v8.20 / v8.24 paths**: the owner decision scoped
  failure writeback to the lifecycle path; extending it would contradict
  those milestones' pinned "no writes on failure" contracts — product
  decision.
- Producers for unassigned status values, readiness evaluation over
  `depends_on`, structured tool arguments, tool schemas / provider
  tool-calling (§9, v9.x), `main.py` migration (frozen) — rejected for the
  reasons recorded after v8.24 / v8.26.

**Open decision for the project owner:** *authorize the next capability
area (e.g. retry/resume architecture, or a consumer for recorded failure
memory on the Foundation path) — none is derivable from repository
evidence alone.*

_Resolution (project owner, after the v8.27 read-only planning audit): all
four areas authorized — (1) advanced context management, (2) AI-initiated
tool calling (§9), (3) retry / resume, (4) failure writeback expansion to
v8.20 / v8.24. Approved sequence (each milestone still requires its own
contract audit and gates; mechanisms ship disabled until their policy
decisions are recorded): v8.28 writeback on v8.24 + shared normalization
(complete) → v8.29 writeback on v8.20 → v8.30 failure category /
transient-error taxonomy → v8.31 tool catalog (declarations, argument
schemas, safety flags; `ToolInterface` untouched) → v8.32 resume a failed
lifecycle run → v8.33 bounded in-run retry → v8.34 context policy and
trimming → v8.35 token budgeting → v8.36 system channel and memory
injection → v8.37 neutral tool-calling types → v8.38 first provider
normalization → v8.39 tool runtime loop → v8.40+ remaining providers.
Open owner decisions recorded with the plan (needed only before their
milestone): side-effecting tool confirmation, tool-error disclosure to
providers, `sensitive` memory handling, resume of non-idempotent stages,
policy values, ARCHIVED-stage resume, prior-attempt success records,
first provider, tool-call auditing, token-count method, v8/v9 numbering._

### v8.41–v8.45 — Production-runtime integration plan — **NOT STARTED** (owner-authorized 2026-10-06)

_Recorded under `AUTONOMOUS_BUILD_PROTOCOL.md` §25 from the Completion Contract
(requirements P1–P5, V4, V5, V7, V9) after the owner locked OD-2, OD-3, OD-4,
OD-4b, OD-5, OD-7, §13 and the V7 authorization. Each milestone is audited
against the repository before implementation. Common exclusions: persistence,
streaming, a permission framework, any change to the legacy runtime beyond the
scoped `main.py` wiring (OD-2), OD-8 (licensing intent) and V6 (owner
attestation). Common verification: focused tests, full suite, architecture and
import checks, `git diff` scope check._

- **v8.41 Production Tool Bridge (P2, P3) — COMPLETE (see history above).** *Objective:* a provider-neutral
  adapter, new `core/live_tools.py`, that (a) converts the production Gemini-
  format declarations into `ToolSpec`s and registers a callback tool per
  production tool in the Agent's `ToolRegistry` / `ToolCatalog`, and (b) executes
  the tool calls of a Gemini Live session through the `ToolRouter` under the
  exact C8 per-call policy (offered / registered gates, O1 hook, O2 strings, O9
  outcome records, OD-C limits per run), sharing one implementation with the
  v8.39 loop (a behaviour-preserving extraction in `core/tool_runtime.py`).
  *Justification:* contract P2 / P3 (amended); the 26 production tools and the
  two skills are not reachable through the v8.x tool stack. *Prerequisites
  (present):* `ToolSpec` / `ToolCatalog` (the declarations use only
  `type`, `properties`, `description`, `required`, `items`), `ToolRouter`,
  `tool_runtime`, thin `Agent` wiring (OD-7). *Exclusions:* `main.py`; the
  production confirmation hook keeps the existing identity / PIN gate inside the
  legacy executor.
- **v8.42 Production Memory Bridge (P4).** *Objective:* a read-only, one-way
  bridge, new `core/production_memory.py`, copying the production SQLite memory
  into the Agent's in-process `MemoryEngine`, honouring O3 (an entry is
  injectable only if explicitly marked non-sensitive) and OD-5 (nothing is
  persisted). *Prerequisites:* `MemoryEngine`, `memory_context`. *Exclusions:*
  any write to the production store; persistence.
- **v8.43 Production Run Recording (P5).** *Objective:* record each production
  tool call through the v8.x lifecycle — `Agent.project_request(tool_name)`, a
  `PipelineRun` (CREATED → RUNNING → COMPLETED / FAILED), step and Goal / Plan
  reflection, and Reflection / Learning / in-process Memory writeback including
  failure writeback — from the O9 outcome record only (no arguments, outputs or
  exception text). *Prerequisites:* v8.21–v8.29 machinery, v8.39 records.
  *Exclusions:* writes to the production SQLite store (OD-5).
- **v8.44 Production Runtime Wiring (P1, V5).** *Objective:* the scoped unfreeze
  of `main.py` (OD-2): the production entry point obtains the Agent's live tool
  session, routes the Live `tool_call` batches and `turn_complete` through it,
  and imports the memory bridge, with all logic in the new `core/` modules;
  headless tests (V5) cover P1–P5 with fakes and pin that `main.py` uses the
  Agent. *Prerequisites:* v8.41–v8.43.
- **v8.45 Contract Closure.** *Objective:* V7 (declare `anthropic`, `openai`,
  `ollama` and the test dependency), V9 (restore the CryptoJS MIT licence text),
  V4 (pin the authorized `main.py` content), A3 / A5 records, and the contract
  snapshot. *Exclusions:* OD-8 stays open; V6 stays the owner's attestation.

### v8.39 — Tool Runtime Loop — **COMPLETE** (moved to history above; kept here as the discovery record)

Per the owner-authorized plan above. The C8 contract audit was performed and
its confirmations were owner-approved on 2026-10-06 (contract §8.1) before
implementation.

All six gating owner decisions are **locked 2026-10-06** (full text in
`docs/EDITH_COMPLETION_CONTRACT.md` §8.1): O1 — side-effecting tool calls are
refused unless an injected confirmation hook approves (no hook: refused);
OD-B — a new additive `AIRequest` field carries the loop-local tool exchange,
canonical history unchanged; O2 — refusals and failures reach the model as a
fixed, sanitized string in `ToolCallResult.output` (no new field); OD-A —
tool declarations and the exchange are counted as required context inside the
existing 8,192-token budget; O9 — the loop returns per-call outcome records
and writes nothing; OD-C — the v8.39 model↔tool execution loop is limited to
**5 model rounds** and **10 total tool executions** per tool-calling run, and
exhausting either limit produces the dedicated loop-exhaustion error defined
for v8.39. These limits apply to the v8.39 loop only; they are not the v8.33
per-step retry bound, which is unchanged.

No owner decision remained open for v8.39. The details left to the contract
audit (carrier field shape, sanitized-string vocabulary, token rendering rule,
outcome record shape, loop-exhaustion error shape and the exact counting
rules for the two limits) were confirmed by the owner and are recorded in §8.1
of the contract.

### v8.38 — First Provider Tool-Call Normalization — **COMPLETE** (moved to history above; kept here as the discovery record)

Contract locked before implementation: first provider (O8) = Anthropic;
`AIRequest.tools: tuple[ToolSpec, ...] = ()` (model-invocable, unique names);
`AIResponse.tool_calls: tuple[ToolCall, ...] = ()`; native mapping only in
`ClaudeProvider`; `ToolCallNormalizationError` (structural, cause kept, never
repair / drop); `ToolCallingUnsupportedError` raised by `AIService` via the
neutral `supports_tool_calling` capability before invocation; O2, other
providers' id fallback and tool-declaration token accounting deferred.

### v8.37 — Neutral Tool-Calling Types — **COMPLETE** (moved to history above; kept here as the discovery record)

Contract locked before implementation: types only; stdlib leaf
`core/tool_calling.py`; `ToolCall(call_id, name, arguments)` /
`ToolCallResult(call_id, name, output)` / `validate_tool_calls`; non-blank ids
and names, JSON-compatible deeply frozen arguments, no id generation, unique
ids per sequence, order preserved; reuse `ToolSpec` (no `ToolDeclaration`); no
failure field (O2); no change to `AIRequest` / `AIResponse`, providers, tool
stack, catalog, Agent or execution.

### v8.36 — System Channel and Memory Injection — **COMPLETE** (moved to history above; kept here as the discovery record)

Owner decisions locked before implementation: O3 — `sensitive=True` memory is
never injected or sent to any provider (no override, no opt-in); system channel
= request-level `AIRequest.system` via `AIService` configuration (no system /
developer role); memory source = `core.memory_engine` only; opt-in injection;
query = current prompt via existing `recall`; max 10 memories in recall order;
optional category / project / memory_type filters; TTL unchanged; order SYSTEM
→ MEMORY → HISTORY → PROMPT; the 8,192-token budget covers system + memory +
history + prompt with memory as the removable part.

### v8.35 — Token Budgeting — **COMPLETE** (moved to history above; kept here as the discovery record)

Owner decisions locked before implementation: D1 pluggable provider-neutral
`count(text) -> int` counter with a deterministic local tokenizer, no network,
no counting logic in `ContextManager`; D2 `max_tokens = 8,192` input/context
budget, enabled by default; D3 covers history + current prompt; D4 no output
reservation, provider output caps unchanged; D5 third independent limit beside
50 messages / 20,000 characters, v8.34 behaviour intact; provider / model
context windows out of scope.

### v8.34 — Context Policy and History Trimming — **COMPLETE** (moved to history above; kept here as the discovery record)

Owner policy locked before implementation: 50 messages / 20,000 content
characters (prompt not counted) / complete-pair trimming, no orphan leading
assistant message / oversized newest message raises a dedicated validation
error / enabled by default / canonical history preserved (derived view only).

### v8.33 — Bounded In-Run Retry — **COMPLETE** (moved to history above; kept here as the discovery record)

Owner policy O5 locked before implementation: TRANSIENT only; max 2 retries
(max 3 total tool invocations per step); 0-second delay; step ACTIVE during
retry; final exception unchanged; exactly one final failure writeback;
explicit type-based TRANSIENT classification (`TransientToolError`); UNKNOWN
is not retried.

### v8.32 — Resume a Failed Lifecycle Run — **COMPLETE** (moved to history above; kept here as the discovery record)

Owner decisions locked before implementation: O4 non-idempotent failed step =
blocked, no override; O6 ARCHIVED = remains archived, never re-dispatched;
O7 previous-run completed stages = no new success writeback.

### v8.31 — Tool Catalog — **COMPLETE** (moved to history above; kept here as the discovery record)

Implemented as the stdlib-only leaf `core/tool_catalog.py`. Still open from
v8.30: how a tool signals a *transient* failure (no such signal exists yet).

### v8.30 — Failure Category / Transient-Error Taxonomy — **COMPLETE** (moved to history above; kept here as the discovery record)

Implemented as a separate leaf taxonomy with Agent-owned rules; `ExecutionFailure`
unchanged; no `TransientToolError` (see history).

### v8.29 — Failure Writeback on the Tool-Chain Path (v8.20) — **COMPLETE** (moved to history above; kept here as the discovery record)

**Objective.** Give a failed `execute_request_with_tool_dispatch_writeback`
attempt exactly one structured failure writeback through the shared v8.28
writer. **Justification.** Authorized area (4); the last path whose
contract still reads "no writes on failure". **Prerequisites.** v8.28
`ExecutionFailure` and shared writer. **Boundary.** Behaviour-preserving
extraction of the v8.19 dispatch loop (v8.25 precedent) to expose the failed
decision; no `PipelineRun` exists on this path, so no attempt identity is
invented. **Exclusions.** No change to v8.19 results, the legacy chain,
v8.22 / v8.23, statuses or the tool stack. **Verification.** Mirror of the
v8.28 suite for v8.20; v8.19 results identical; full suite; gates A–D.

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
