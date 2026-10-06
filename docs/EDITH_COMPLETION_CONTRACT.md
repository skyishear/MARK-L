# EDITH Completion Contract

> Project identity: EDITH · Repository: MARK-L
> Contract version: **1** · Ratified by the project owner on **2026-10-05**
> (Definition P — production-complete — with the clarifications in §2.2)

This document is the authoritative, project-level definition of when
EDITH is complete. It is evaluated against the repository (code, tests,
git), never against conversation history. `ROADMAP.md` remains the living
record of milestone history and the current checkpoint; this contract
defines what the roadmap is working toward.

---

## 1. Purpose and authority

- This contract answers one question: **what must be true of the
  repository for EDITH to be considered complete.**
- It is the authoritative project-level completion definition. It adds
  **no** requirement beyond those listed in §4–§6; a requirement that is not
  listed here is not a completion requirement.
- It does not replace the per-milestone Definition of Done (`MARK-L.md`),
  the STOP conditions or verification gates
  (`AUTONOMOUS_BUILD_PROTOCOL.md`), or the freeze rules (`ROADMAP.md`).
  It sits beside them: they govern *how a milestone is built*, this
  governs *when the project is finished*.
- Only the project owner may amend this contract (§14). An agent may
  evaluate the checklist (§9) but must never edit the contract, tick it as
  satisfied on the owner's behalf, or declare EDITH complete (§12).

### 1.1 Provenance tags

| Tag | Meaning |
|---|---|
| **[R]** | A repository document states it. |
| **[D]** | Derived: it follows directly from repository text. |
| **[P]** | Proposed in the contract proposal and ratified by the owner on 2026-10-05. |

---

## 2. Definition of EDITH COMPLETE (Definition P)

### 2.1 Definition

EDITH is complete when **all** of the following are true:

1. **[R]** A goal is planned, projected into Foundation records, run
   through a controlled tool system, and written back to memory and
   reflection. Behaviour is deterministic and fully tested (`readme.md`).
2. **[R]** A model can propose tool calls through a provider-neutral
   boundary, and they execute under an owner-locked safety policy
   (owner-authorized area (2), `ROADMAP.md`; `docs/TECHNICAL_DEBT.md` §9).
3. **[R]** AI context, token budget and memory injection are bounded and
   privacy-preserving (v8.34–v8.36, O3).
4. **[D]** The shipped runtime executes user requests **through** the v8.x
   architecture, not beside it. The v8.x architecture is actually
   connected to and used by the production runtime — not merely
   implemented and tested as an isolated library.
5. **[P]** All of the above is proven by the test suite and by an
   owner-run runtime attestation recorded against a commit hash.

### 2.2 Owner clarifications recorded with the ratification

1. EDITH is complete only when the v8.x architecture is actually
   connected to and used by the production runtime, not merely
   implemented and tested as an isolated library.
2. The frozen legacy architecture must not be casually rewritten.
   Production integration must respect the repository's freeze rules and
   use the smallest safe adapter or unfreeze approach, **after** the
   relevant owner decision is explicitly locked.
3. Deferred capabilities — streaming, persistence, full permission
   systems, vision, vector memory, structured outputs, performance work,
   and the like — remain deferred unless the repository later explicitly
   promotes them to mandatory completion requirements (§7.2).
4. Completion of v8.39 alone is not project completion.
5. No additional completion requirements are invented. This contract is
   the authoritative project-level definition once recorded.
6. Every owner decision stays explicitly visible (§8). None is chosen on
   the owner's behalf.

### 2.3 Explicitly not completion

- finishing v8.39, or any single milestone;
- exhausting the defined roadmap milestones;
- a green test suite;
- implementing the ideas in `docs/TECHNICAL_DEBT.md`.

---

## 3. Evaluation rules

- A requirement is satisfied only when its check in §9 can be shown
  against the repository at one commit. "Tests pass" alone never satisfies
  a requirement.
- "Environment cannot verify" is not "implementation is broken": a
  requirement that depends on an environment the agent lacks is reported as
  environment-only (§6.1), and is satisfied by the owner attestation (V6).
- Deferred work is never counted as accidentally incomplete (§7).
- Open owner decisions (§8) block the requirements that name them. An
  agent stops (`AUTONOMOUS_BUILD_PROTOCOL.md` §13, *External decision*)
  rather than choosing.

---

## 4. Mandatory completion areas

| ID | Requirement | Tag |
|---|---|---|
| **C1** | Legacy request lifecycle and skill chain (v3.x–v5.x), frozen | [R] |
| **C2** | Provider-neutral AI layer and the four providers (v6.x–v7.x) | [R] |
| **C3** | Foundation stores, plan projection and lifecycle reflection (v8.4–v8.10, v8.21–v8.26) | [R] |
| **C4** | Controlled tool system and catalog (v8.11–v8.20, v8.31) | [R] |
| **C5** | Failure handling: writeback, taxonomy, resume, bounded retry (v8.27–v8.30, v8.32–v8.33) | [R] |
| **C6** | AI context and memory shaping (v8.34–v8.36) | [R] |
| **C7** | Tool-calling types and first provider, Anthropic (v8.37–v8.38) | [R] |
| **C8** | Model-initiated tool runtime loop (v8.39) | [R] |
| **C9** | Minimal safety policy for model-initiated calls: confirmation (O1), error disclosure (O2), auditing (O9). Not the full, deferred permission system. | [R] |
| **C10** | Tool calling on the remaining providers (v8.40+), in the scope fixed by OD-4b | [R] |
| **A1** | No import cycles | [R] |
| **A2** | Provider SDKs only in provider modules, lazily imported | [R] |
| **A3** | Frozen legacy modules unchanged against their freeze point | [R] |
| **A4** | Legacy and v8.x coupled only through documented adapters | [R] |
| **A5** | `Agent` stays a composition root, under the policy set by OD-7 | [R] |

---

## 5. Production integration requirements

All five are **[P]**, derived from §2.1 item 4. Definition P makes them
mandatory.

| ID | What must be connected |
|---|---|
| **P1** | The production entry point obtains **and uses** an `Agent` for at least one real request path. |
| **P2** | The production tool surface (the tools declared and dispatched by the production runtime, plus registered skills) is reachable through `ToolRegistry`, `ToolRouter` and `ToolCatalog`. Anything excluded must be on an explicit, owner-approved exclusion list. |
| **P3** | Tool calls the production model initiates (the realtime Gemini Live session, OD-3) are executed through an adapter that applies the same per-call policy as the C8 loop — offered and registered gates, the O1 confirmation hook, O2 sanitized strings, O9 outcome records and the OD-C limits — against the `ToolRouter` (amended 2026-10-06; see §14). |
| **P4** | One memory source of truth is declared. Either an explicit adapter bridges the production memory into v8.x injection (with an O3 sensitive-flag mapping), or the split is recorded as permanent (OD-4). |
| **P5** | Executions on the P1 path are recorded through the v8.x lifecycle: run status, writeback and failure writeback. |

**Freeze constraint (owner clarification 2).**
`main.py`, `core/skill_registry.py`, `core/skill_dispatch.py` and
`skills/*` are frozen (`ROADMAP.md` Frozen Modules; protocol §8 and §13).
Integration must use the **smallest safe** adapter or scoped unfreeze,
and only **after** OD-2 is explicitly locked. Until then no agent may
modify them. Integration is bridged through explicit adapters
(`ROADMAP.md` Architecture Policy), not by rewriting frozen code.

---

## 6. Verification requirements

| ID | Check | Tag |
|---|---|---|
| **V1** | Full suite on a clean checkout built from declared dependencies: 0 failed, 0 errors, 0 skipped, count ≥ the recorded checkpoint | [R] |
| **V2** | The four gates (A–D) pass per milestone with real output (protocol §11) | [R] |
| **V3** | The architecture and import-pin tests pass, and a cycle scan finds none | [R] |
| **V4** | Frozen-module content is mechanically pinned against its freeze point (today the freeze test pins import edges only) | [P] |
| **V5** | Automated headless tests cover P1–P5 using fakes (no GUI, audio or network), including a pin that the production entry point **uses** the `Agent` | [P] |
| **V6** | Environment-only attestation: the owner runs the app on a real desktop and records the commit hash — launch, one live provider call, and one voice turn that makes a tool call through the v8.x path | [D] |
| **V7** | Dependencies are declared for the runtime, the providers actually used, and the test suite | [D] |
| **V8** | `CLAUDE.md`, `ROADMAP.md`, `readme.md` and `docs/TECHNICAL_DEBT.md` agree on the checkpoint and on this contract (protocol §20) | [R] |
| **V9** | `THIRD_PARTY_NOTICES.md` is complete, including the CryptoJS MIT licence text | [R] |

### 6.1 Environment-only limits (not defects)

An agent without the following cannot verify them, and a gap here is not
a defect in the code. V6 covers them through the owner's attestation:

- the desktop GUI;
- audio, speech-to-text and text-to-speech;
- Windows-only packages;
- live provider calls (provider SDKs and API keys);
- Gemini Live.

---

## 7. Deferred and optional areas

### 7.1 What does not block completion

**Deferred [R]** (`ROADMAP.md` Current Status):

- streaming;
- persistence (see OD-5);
- the full permission system (only C9's minimal form is required);
- voice/UI features beyond P1–P5;
- vision, vector memory, structured outputs and performance work (owner
  clarification 3).

**Optional ideas [R]** (`docs/TECHNICAL_DEBT.md`; not built early, protocol §14):
PromptBuilder; context filtering and summarization; vector memory;
structured outputs; vision; audio inside the AI stack; `AIService`-level
retry and fallback; a provider capability matrix; message metadata;
attachments; performance work.

**Optional hygiene [P]**: type-check, lint and build tooling (no
repository document requires them); the unreferenced `core/llm_client.py`
(OD-11); the duplicate class names `ContextManager`, `PlanningEngine` and
`ExecutionResult`.

### 7.2 Promotion rule

A deferred or optional area becomes a mandatory completion requirement
**only** by an owner-approved amendment to this contract (§14) that adds
it to §4–§6. Until then it is deferred, whatever `ROADMAP.md`,
`docs/TECHNICAL_DEBT.md` or an agent's discovery run says.

---

## 8. Owner decisions

No decision below is chosen on the owner's behalf. A decision is **LOCKED**
only when the owner has stated it and it is recorded here or in
`ROADMAP.md`.

### 8.1 Locked by the ratification of this contract

| ID | Decision | Locked |
|---|---|---|
| **OD-1** | Production integration is required for completion: **Definition P** | 2026-10-05 |
| **OD-6** | This contract is ratified with the §2.2 clarifications | 2026-10-05 |
| **O1** | **Option 2.** A model-proposed call to a tool whose `ToolSpec` has `side_effects=True` is refused unless an injected confirmation hook approves it; with no hook it is refused. A call whose spec has `side_effects=False` needs no confirmation. The hook is a single injected synchronous predicate with default-deny, not a permission framework (the full permission system stays deferred). The baseline gates (tool offered, `model_invocable`, registered) are already required by C8. The hook's real implementation belongs to production wiring (P3). | 2026-10-06 |
| **OD-B** | **Option 1.** A new additive final `AIRequest` field carries the prior rounds as neutral `ToolCall` and `ToolCallResult` data. The exchange stays loop-local and the canonical `ConversationHistory` is not changed. Each provider maps it natively. | 2026-10-06 |
| **O2** | **Option 1.** Refusals and tool failures reach the model as a fixed, sanitized string in `ToolCallResult.output`: a category plus the exception type name, or a closed refusal reason. No new field (`ToolCallResult` is unchanged), and the loop continues. The exception message, arguments, repr and traceback are never sent (the v8.28 rule). | 2026-10-06 |
| **OD-A** | **Option 2.** Tool declarations and the tool-call exchange are rendered deterministically and counted through the injected `TokenCounter` as required, never-truncated context (like system and prompt) inside the existing 8,192-token budget, with no new limit. History is trimmed to make room; if they still do not fit, `ContextValidationError` is raised. | 2026-10-06 |
| **O9** | **Option 2.** The loop returns an immutable per-call outcome record: the `call_id`, the tool name, an outcome (executed, refused or failed), and the exception type name for a failure. It never carries arguments or exception text, and the loop itself writes nothing. | 2026-10-06 |
| **OD-C** | **Locked limits** for the v8.39 model↔tool execution loop: a maximum of **5 model rounds** per tool-calling run, and a maximum of **10 total tool executions** per tool-calling run. Exhausting **either** limit produces the dedicated OD-C loop-exhaustion error defined for v8.39 (the run does not truncate or stop silently). These two limits apply to the v8.39 loop only. They are **not** the v8.33 per-step retry bound (3 invocations per step), which is a separate bound this decision does not amend; O5 and the statement that every other path routes exactly once are unchanged. No other numeric loop limit exists. | 2026-10-06 |

| **OD-4b** | Tool calling is added to the remaining providers (OpenAI, Gemini, Ollama) in the provider-neutral shape of v8.38 / v8.39, with a positional-id fallback for providers that give calls no id. | 2026-10-06 |
| **OD-3** | Production keeps the realtime Gemini Live session. P3 is amended (§5): a Live adapter executes the session's tool calls under the C8 per-call policy and OD-C limits. | 2026-10-06 |
| **OD-2** | Scoped unfreeze of `main.py`: only minimal wiring in `main.py`; all logic lives in new adapter modules under `core/`. No other frozen file is unfrozen. | 2026-10-06 |
| **OD-4** | The production SQLite memory reaches v8.x injection through a read-only, one-way bridge into the in-process `MemoryEngine`, honouring O3 (anything not explicitly non-sensitive is treated as sensitive). | 2026-10-06 |
| **OD-5** | Persistence stays deferred; v8.x state and its `MemoryEngine` remain process-local and sit beside the production SQLite memory. | 2026-10-06 |
| **OD-7** | The `Agent` is accepted at its current size; from now on only thin wiring may be added to it. | 2026-10-06 |
| **§13 / A3** | The `aa95b63` edit to `main.py` (one string literal) is confirmed (§13). | 2026-10-06 |
| **V7** | Authorization to change `requirements.txt` / `pyproject.toml` and add a development requirements file. | 2026-10-06 |
| **OD-10** | The owner performs V6 manually; the agent never marks V6 passed (§15). | 2026-10-06 |

**Still open, deliberately.** OD-8 (commercial-licensing intent): the
existing CC BY-NC 4.0 constraint stays documented and commercial use stays
unresolved until the owner decides. OD-9 (numbering) follows the existing rule
in `AUTONOMOUS_BUILD_PROTOCOL.md` §25.2 (v8.x). OD-11 is optional hygiene.

**C8 audit confirmations (owner-approved 2026-10-06).** The details the
five decisions above left to the C8 contract audit are now confirmed exactly
as the audit proposed them. The values 5 and 10 and the either-limit rule
are unchanged.

- **Counting rules (OD-C).** R1: a "model round" is one provider call, the
  first call being round 1. R2: if the 5th response still contains tool
  calls, the error is raised and those calls are not run. R3: a "tool
  execution" is one invocation of the injected router, counted at
  invocation; a call that raises counts, a refused call does not. R4: once a
  call has passed the offered and registered gates and 10 executions are
  already used, the error is raised before the confirmation hook is asked and
  before invoking. R5: counters are local to one run and keep no state across
  runs; no other numeric loop limit exists.
- **Error (OD-C).** `ToolLoopExhaustedError(Exception)`, defined in
  `core/tool_runtime.py`, with the attributes `limit` (`"model_rounds"` or
  `"tool_executions"`), `rounds`, `tool_executions` and `outcomes` (the
  immutable tuple of O9 records so far). Its message is structural only.
- **Per-call order.** Refuse if the tool is not among the tools offered for
  the run; refuse if it is not registered; apply the R4 limit check; if the
  spec's `side_effects` is not exactly `False`, refuse unless the injected
  hook returns exactly `True`; invoke once. A failure, including a
  non-`str` tool output, becomes an error string and the loop continues.
- **Model-facing strings (O2).** `error: refused (<reason>)` with the closed
  vocabulary `not_offered`, `not_registered`, `confirmation_denied`; and
  `error: failed (<ExceptionTypeName>)`.
- **Outcome record (O9).** `ToolCallOutcome(call_id, tool_name, outcome,
  exception_type)`, exactly the locked fields, with no refusal-reason field.
  The run result is `ToolLoopResult(response, outcomes, rounds,
  tool_executions)`.
- **Carrier (OD-B).** `ToolExchange(calls, results, text)` in
  `core/tool_calling.py` and `AIRequest.tool_exchanges` as the new final
  field; a non-empty value requires non-empty `tools`. `text` is the first
  text block of the round's response.
- **Token rendering (OD-A).** Canonical, sorted-key JSON of each tool's
  name, description and parameters only, plus each exchange's call ids,
  names, arguments, outputs and text, in a new stdlib-only leaf
  `core/tool_context.py`; `ContextManager.prepare_context` gains one
  additive keyword, `tool_context`, counted as required context.
- **R-2 hardening.** `core/claude_provider.py` raises
  `ToolCallNormalizationError` when a response contains a `tool_use` block
  and its `stop_reason` is `max_tokens` or `refusal`.
- **Scope.** A pure orchestration leaf `core/tool_runtime.py` with
  injected collaborators, plus one thin
  `Agent.ask_with_tools(provider_name, prompt, *, tools=None, confirm=None,
  memory=None)` that mirrors `ask`: on success the user prompt and the final
  text are appended to canonical history, on any exception nothing is.
- **Exception propagation (acknowledged).** The C8 check "exception
  propagation" means: provider, `AIService`, `ContextManager` and
  confirmation-hook exceptions, non-`Exception` `BaseException`s and the
  exhaustion error propagate unchanged; tool `Exception`s are converted per
  O2.
- **R-1 (acknowledged).** The locked exchange carries no provider-opaque
  blocks, so a model whose reasoning blocks must be replayed may reject or
  degrade a follow-up request. This is a known, environment-only limitation
  (V6); the default model is unaffected, and any later fix is a separate
  additive decision.

Recording model-initiated calls through Memory → Reflection → Learning is
not part of the O9 lock and is decided separately at P5.

### 8.2 Locked earlier (recorded in `ROADMAP.md`)

O3 (sensitive memory never injected), O4 (non-idempotent resume blocked),
O5 (bounded retry policy), O6 (ARCHIVED steps), O7 (prior-attempt success
records), O8 (first provider = Anthropic), D1–D5 (token budgeting), the
Goal / Plan / Step lifecycle contract, failure writeback (YES), and the
retry / resume authorization.

### 8.3 Open

| ID | Decision | Blocks |
|---|---|---|
| **OD-8** | Licensing intent: the inherited runtime is CC BY-NC 4.0 — is commercial use intended? Also approval to restore the CryptoJS notice. | V9, release |
| **OD-9** | Version numbering: `docs/TECHNICAL_DEBT.md` targets "v9.x" for tool calling while `ROADMAP.md` uses v8.x. (Existing rule: protocol §25.2 stays within the current major series.) | — |
| **OD-11** | Keep or retire the unreferenced `core/llm_client.py` | optional |

No default is adopted for any open decision.

---

## 9. Completion checklist

**EDITH is complete (Definition P) when every box below is true at one
commit and the owner has signed the attestation (§12).** Every check is
evaluated against the repository.

### Capabilities

- [ ] **C1–C7** — the module exists, its dedicated tests pass, and `ROADMAP.md` records the milestone COMPLETE.
- [ ] **C8** — the v8.39 loop exists, and tests cover the OD-A to OD-C rules, fail-closed behaviour for specs that are not `model_invocable`, an unauthorized call, loop termination and exception propagation.
- [ ] **C9** — O1, O2 and O9 are locked in `ROADMAP.md` and enforced by tests.
- [ ] **C10** — each provider in the OD-4b scope maps tool calls natively, and every other provider is pinned fail-closed.

### Architecture

- [ ] **A1** — an AST cycle scan of `core/` and `core/agent/` finds none.
- [ ] **A2** — non-stdlib imports in `core/` appear only in the provider modules and the inherited desktop modules, and every provider SDK import is nested inside a function.
- [ ] **A3** — `git log` for each frozen module shows no commit after its freeze point except the exceptions in §13, each confirmed by the owner.
- [ ] **A4** — non-frozen `core` modules (the `Agent` composition root aside) import frozen modules only through the two documented adapters: `plan_projection` → `planner` and `skill_tool_adapter` → `skill_registry`.
- [ ] **A5** — an OD-7 outcome is recorded and respected.

### Production integration

- [ ] **P1** — the production entry point calls the `Agent` in a request path, and an AST pin proves it.
- [ ] **P2** — every production tool is registered with a `ToolSpec`, or appears on the owner-approved exclusion list.
- [ ] **P3** — a tool call initiated by the production Gemini Live session is executed through the Live adapter under the C8 per-call policy and OD-C limits (shared code with `core/tool_runtime.py`).
- [ ] **P4** — an OD-4 outcome is implemented and tested, or the split is recorded.
- [ ] **P5** — a P1-path run produces a `PipelineRun` and the writeback records.

### Verification

- [ ] **V1** — the suite passes in an environment built only from declared dependencies.
- [ ] **V2** — each milestone's checkpoint report contains real test output.
- [ ] **V3** — the architecture tests pass.
- [ ] **V4** — a test pins the frozen-module content.
- [ ] **V5** — headless tests cover P1–P5.
- [ ] **V6** — a signed attestation names the commit and the checks run.
- [ ] **V7** — a clean install covers the runtime, the used providers and the tests.
- [ ] **V8** — the four documents agree on the checkpoint line and on this contract.
- [ ] **V9** — the CryptoJS text is restored and the notices are complete.

### Governance

- [ ] No owner decision in §8.3 that a mandatory requirement names is open.
- [ ] `ROADMAP.md` records "Contract v1 satisfied at commit `<hash>`" with the owner's sign-off.

---

## 10. Status snapshot

*Informational snapshot as of 2026-10-06 at checkpoint v8.38 (head
`aa95b63` plus the uncommitted documentation changes). It is not normative: agents
re-evaluate §9 against the repository and never against this table.
`ROADMAP.md` stays the living checkpoint.*

| ID | Status | Repository evidence |
|---|---|---|
| **C1** | COMPLETE | Frozen modules untouched since their original commits (git log). Tests: planner 29, orchestrator 16, pipeline 14, session 7, coordinator 6. |
| **C2** | COMPLETE | Provider modules with lazy SDK imports. Mock tests: 19–20 per provider. Live calls are environment-only. |
| **C3** | COMPLETE | `core/plan_projection.py` (51 tests), `core/step_lifecycle.py` (41), `core/lifecycle_reflection.py` (38), and the Foundation stores. |
| **C4** | COMPLETE | `ToolRegistry`, `ToolRouter`, `SkillTool`, and the catalog (78 tests). |
| **C5** | COMPLETE | Retry is `for attempt in range(1, max_attempts + 1)` with `max_attempts = 3` (`core/agent/__init__.py:1218`). The failure normalizer reads only the type name (`core/execution_failure.py:49`). The resume O4 gate is at `core/agent/__init__.py:1445`. |
| **C6** | COMPLETE | `ContextManager(50, 20_000, 8_192)` (`core/context_manager.py:80–82`). The O3 filter is at `core/memory_context.py:101`. |
| **C7** | COMPLETE | `supports_tool_calling` is true only on Claude (`core/claude_provider.py:79`). The `AIService` guard is at `core/ai_service.py:108–111`. |
| **C8** | COMPLETE | `core/tool_runtime.py` (`run_tool_loop`, limits `MAX_MODEL_ROUNDS = 5` / `MAX_TOOL_EXECUTIONS = 10`, `ToolLoopExhaustedError`), `core/tool_context.py`, `ToolExchange`, `AIRequest.tool_exchanges`, `Agent.ask_with_tools`; `ROADMAP.md` records v8.39 COMPLETE. Tests: `tests/test_tool_runtime.py` (65), `test_tool_exchange.py` (32), `test_tool_context.py` (22), `test_agent_ask_with_tools.py` (19), covering the OD-A to OD-C rules, fail-closed gates, loop termination and exception propagation as interpreted in §8.1. |
| **C9** | COMPLETE | O1, O2 and O9 are locked and recorded in `ROADMAP.md` (v8.39 entry) and enforced by `tests/test_tool_runtime.py` (hook is exact-`True` and default-deny, sanitized strings only, outcome records with no arguments or exception text, loop writes nothing; end to end in `tests/test_agent_ask_with_tools.py`). The full permission system stays deferred. |
| **C10** | COMPLETE | OpenAI, Gemini and Ollama map tool calls natively and declare `supports_tool_calling` (`core/openai_provider.py`, `core/gemini_provider.py`, `core/ollama_provider.py`; OD-4b locked); every other provider is still fail-closed. Tests: `tests/test_provider_tool_calling.py` (69). Request shapes were checked against the real SDK models in the build environment. |
| **A1** | COMPLETE | AST cycle scan of `core/` and `core/agent/`: none. |
| **A2** | COMPLETE | `anthropic`, `openai`, `ollama` and `google` are imported only inside the provider modules, nested. |
| **A3** | COMPLETE | The only commit after a freeze point is the `aa95b63` edit to `main.py`, confirmed by the owner (§13). The other 15 frozen files each have one commit and are content-pinned (V4). |
| **A4** | COMPLETE | Only `plan_projection` → `planner` and `skill_tool_adapter` → `skill_registry`. |
| **A5** | COMPLETE | OD-7 is recorded (§8.1): the current `Agent` (55 methods, 1,606-line class) is accepted and only thin wiring may be added. v8.39 added only the 41-line `ask_with_tools` (pure delegation to `run_tool_loop`, pinned thin by `tests/test_agent_ask_with_tools.py`). |
| **P1** | NOT STARTED | `main.py:684` builds `Agent()`; `self._agent` is never read. OD-2 is locked (scoped unfreeze); planned as v8.44. |
| **P2** | PARTIAL | `core/live_tools.py` converts and registers all 28 production declarations (the 26 in `main.py` plus the weather and Spotify skills) in the Agent's registry and catalog (`tests/test_live_tools.py`, 48 tests). Not yet called from `main.py` (v8.44). |
| **P3** | PARTIAL | `LiveToolSession.handle_round` runs a Gemini Live `tool_call` batch through the router under the C8 policy, sharing `ToolRun` with the v8.39 loop (OD-C limits per run, O1 hook, O2 strings, O9 records). Not yet called from `main.py` (v8.44). |
| **P4** | NOT STARTED | Production memory is SQLite (`memory/core_memory.py:39`); `MemoryEngine` is in-process (`core/memory_engine.py:1`). OD-4 / OD-5 are locked; the bridge is planned as v8.42. |
| **P5** | NOT STARTED | No production code path calls any lifecycle or writeback method. Planned as v8.43. |
| **V1** | PARTIAL | 2725 passed, but the suite needs `pytest` and `numpy`, and `pytest` is not declared in any dependency file. |
| **V2** | COMPLETE | Each milestone has a checkpoint commit and the current head passes the suite. Historical gates were not re-run. |
| **V3** | COMPLETE | `tests/test_architecture_freeze.py` (9 tests) and per-module AST pins pass. |
| **V4** | PARTIAL | `tests/test_frozen_content.py` (20 tests) pins the content (SHA-256, line endings normalized) of 15 of the 16 frozen files at their single freeze-point commit, checks the pinned set against the `ROADMAP.md` Frozen Modules list, and rejects new files in `skills/`. `main.py` is deliberately unpinned until the owner confirms or reverts the §13 exception. |
| **V5** | NOT STARTED | `tests/test_main_agent_integration.py` has syntax and import-shape checks only. |
| **V6** | NOT STARTED | No attestation recorded. Environment-only. |
| **V7** | PARTIAL | `requirements.txt` omits `anthropic`, `openai`, `ollama`, `pytest`, and the speech modules' imports (`torch`, `kokoro`, `vosk`, `faster_whisper`, `edge_tts`, `miniaudio`). |
| **V8** | COMPLETE | `CLAUDE.md`, `ROADMAP.md`, `readme.md` and `docs/TECHNICAL_DEBT.md` reconciled by the documentation step that recorded this contract. |
| **V9** | PARTIAL | The CryptoJS MIT text is missing (`THIRD_PARTY_NOTICES.md` §2 records it as open). |
| Streaming, persistence, full permissions, other §7.1 areas | DEFERRED | §7. |

Tally of the 29 requirements: **18 COMPLETE, 6 PARTIAL, 0 BLOCKED,
5 NOT STARTED.** The tally is a count, not a percentage, and the items
are not weighted.

---

## 11. Remaining work, ordered by dependency

1. ~~**C0** — record this contract and reconcile the stale governance
   statements (documentation only).~~ Recorded by this change.
2. ~~Lock O1, O2, O9, OD-A, OD-B and OD-C~~ — all six locked 2026-10-06
   (§8.1). C8 and C9 are complete.
3. ~~Lock OD-2, OD-3, OD-4, OD-5 and OD-7~~ — locked 2026-10-06 (§8.1).
4. ~~A read-only production-integration contract audit~~ — done; the plan
   is recorded in `ROADMAP.md` (v8.41–v8.45).
5. V7 — declare dependencies and make the test environment reproducible
   (authorized 2026-10-06; planned in v8.45).
6. ~~C8 and C9 (v8.39), at library level.~~ Complete.
7. The P-series and V5, as planned in `ROADMAP.md`: v8.41 (P2, P3), v8.42
   (P4), v8.43 (P5), v8.44 (P1, V5). V4 is partial: only the `main.py` pin
   remains (v8.45, after the authorized wiring).
8. ~~C10 (v8.40+), in the OD-4b scope.~~ Complete (v8.40).
9. V9, then V6 (the owner attestation).
10. The completion attestation in `ROADMAP.md` (§12).

Each step is formally defined and recorded in `ROADMAP.md` (protocol §25).

---

## 12. Interaction with autonomous runs

- An autonomous run (`AUTONOMOUS_BUILD_PROTOCOL.md` §25) treats an
  unchecked, unblocked item in §9 as evidence of a documented gap whose
  prerequisites exist, and may define it as the next milestone.
- An item that names an open §8.3 decision is **blocked**: the run stops
  (protocol §13, *External decision*) and reports the exact decision. It
  never selects an option on the owner's behalf.
- No agent may declare EDITH complete. Completion exists only when every
  §9 box is true at one commit and the owner has signed the attestation,
  recorded in `ROADMAP.md` as "Contract v1 satisfied at commit `<hash>`".
- Completing v8.39, or any other single milestone, never satisfies this
  contract.

---

## 13. Recorded exceptions (A3)

| Module | Commit | Change | Authorization |
|---|---|---|---|
| `main.py` (frozen) | `aa95b63` | One string literal in a Gemini tool-declaration example (`"Fatih"` → `"Alex"`). Behaviour-neutral. Recorded in `THIRD_PARTY_NOTICES.md`. | **Confirmed by the owner, 2026-10-06.** |

The change is accepted. Later authorized changes to `main.py` (the scoped
unfreeze of OD-2) are recorded in this table when they are made.

---

## 14. Amendment log

| Date | Change | By |
|---|---|---|
| 2026-10-05 | Contract v1 ratified: Definition P (OD-1) and the §2.2 clarifications (OD-6). | Project owner |
| 2026-10-06 | Decision register updated: O1 = Option 2, OD-B = Option 1, O2 = Option 1, OD-A = Option 2 and O9 = Option 2 locked (§8.1). OD-C kept open until a justified limit is established (§8.3). No requirement in §4–§6 added or removed. | Project owner |
| 2026-10-06 | Owner delegations recorded (§8.1): OD-2, OD-3, OD-4, OD-4b, OD-5, OD-7, §13 / A3, V7, OD-10; **P3 amended** (§5, §9) for the Gemini Live adapter. OD-8 stays open. | Project owner |
| 2026-10-06 | OD-C locked (§8.1): 5 model rounds and 10 total tool executions per tool-calling run in the v8.39 loop, either limit raising the dedicated loop-exhaustion error; the v8.33 per-step retry bound is not amended. OD-C removed from §8.3. No requirement in §4–§6 added or removed. | Project owner |

An amendment is made only by the owner, adds a dated row here, and is the
only way to add or remove a requirement in §4–§6 (§7.2).

---

## 15. V6 attestation record

V6 is the owner's manual attestation on a real Windows desktop (launch, one
live provider call, and one voice turn that makes a tool call through the v8.x
path). An agent never fills in or marks this record passed (OD-10). Nothing
below has been attested yet.

| Date | Commit | Checks run (launch · live provider call · voice tool-call turn) | Result | By |
|---|---|---|---|---|
| — | — | — | **NOT ATTESTED** | — |
