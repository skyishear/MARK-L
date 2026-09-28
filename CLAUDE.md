# CLAUDE.md

Claude Code entry point for the MARK-L repository.

## Identity

- **EDITH** — project / final system identity.
- **MARK-L** — repository, codebase, filenames, docs and prompts.
  Use MARK-L in code and documentation; do not rename to EDITH.

## Governance Hierarchy

Read in this order, each exactly once per task:

1. `CLAUDE.md` — this file: operational entry point.
2. `MARK-L.md` — master governance: philosophy, architecture policy, scope discipline.
3. `AUTONOMOUS_BUILD_PROTOCOL.md` — authoritative autonomous execution protocol
   (verification gates, STOP conditions, failure recovery, checkpoint reports, continuation).
4. `ROADMAP.md` — living checkpoint: milestone history, current checkpoint,
   active and next discovered milestone, deferred areas.
5. `docs/*.md` — engineering standards and deferred-work notes (`docs/TECHNICAL_DEBT.md`).

`readme.md` is separate public project documentation.
When documents overlap, the more specific document is authoritative for its role.

## Source of Truth

The repository — code, tests, git — is the only source of truth.
Never rely on previous conversations. Verify the current state before acting.

## Current Repository State

- Legacy v3.x execution stack: **frozen** (read-only; see `ROADMAP.md`).
- Active surface: v8.x Foundation stores, v8.11–v8.20 tool stack, v8.21–v8.30 projection path.
- Checkpoint: **v8.31 complete**; active milestone: none; next planned milestone:
  **v8.32** of the owner-authorized plan recorded in `ROADMAP.md` (the living checkpoint).
- Verified suite: **2097 passed, 0 failed, 0 errors, 0 skipped**.

Details and history live in `ROADMAP.md` — do not duplicate them here.

## Operating Rules

- Preserve existing architecture; incremental, additive changes only.
- Never redesign, rewrite or duplicate working components.
- Modify only files required for the task; keep diffs minimal.
- Preserve public APIs and `core.agent.__all__` unless explicitly instructed.
- Never modify frozen legacy modules, configuration, secrets, certificates,
  databases, caches, build artifacts, virtual environments, `.gitignore`
  or git history unless explicitly requested.
- Every milestone requires tests and must pass the four verification gates
  in `AUTONOMOUS_BUILD_PROTOCOL.md` §11 before it is reported complete.
- Never weaken, skip, delete or hide tests to make a suite pass.

## Execution Modes

- **Explicit request** (a named milestone, discovery, audit or fix):
  implement exactly the requested scope, verify, report, then stop.
  List further work under "Next Milestone" without starting it.
- **Autonomous run** (the user says "Continue building MARK-L autonomously"):
  follow `AUTONOMOUS_BUILD_PROTOCOL.md` — after a milestone passes every
  gate, take the next roadmap milestone; when none is defined, run
  architecture-driven milestone discovery (protocol §25), record the
  justified milestone in `ROADMAP.md` as NOT STARTED, then implement it.
  Continue until a defined STOP condition (protocol §13) occurs. Roadmap
  exhaustion alone is not a STOP condition; never ask the user which
  milestone to build next — derive it from repository evidence or STOP
  with the exact unresolved architectural question.

## Report Format

Use the checkpoint report defined in `AUTONOMOUS_BUILD_PROTOCOL.md` §23
(Milestone, Analysis, Files Modified, Exact Code Changes, Tests,
Architecture Verification, Breaking Changes, Git Diff Summary,
Final Verification, Next Milestone). Report real test output only.
