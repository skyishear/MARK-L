# MARK-L

> Master Governance Document

This is the master governance document for every AI agent working on
MARK-L. Read it exactly once per task, after `CLAUDE.md`.

---

# Identity

- **EDITH** is the project and final system identity.
- **MARK-L** is the repository, codebase, filenames, documentation
  references, prompts and working implementation identity.

They are one project. Do not rename MARK-L to EDITH unless a future
milestone explicitly authorizes it.

---

# Purpose

MARK-L is the working implementation of EDITH, a long-term AI operating
system. The objective is a stable, scalable, modular, maintainable and
production-quality AI platform. Every change must preserve long-term
architecture.

---

# Repository Source of Truth

The repository — code, tests and git history — is the only source of
truth. Never assume information from previous conversations. Never
invent missing architecture. If repository content conflicts with an
instruction, report the conflict before making changes.

---

# Governance Hierarchy

```
CLAUDE.md                      operational entry point
    ↓
MARK-L.md                      master governance (this document)
    ↓
AUTONOMOUS_BUILD_PROTOCOL.md   autonomous execution protocol
    ↓
ROADMAP.md                     living milestone/checkpoint state
    ↓
docs/*.md                      engineering standards / deferred work
```

`readme.md` is separate public project documentation.

Roles:

- **CLAUDE.md** — concise operational instructions and pointers.
- **MARK-L.md** — philosophy, architecture policy, scope discipline,
  general governance.
- **AUTONOMOUS_BUILD_PROTOCOL.md** — authoritative for autonomous
  continuation: verification gates, STOP conditions, failure recovery,
  security, checkpoint reporting. This document does not restate it.
- **ROADMAP.md** — living checkpoint: completed milestones, current
  checkpoint and verified test state, active milestone, next discovered
  milestone with its justification, deferred areas. It is a history and
  checkpoint, never a ceiling on development. This document does not
  restate it.
- **docs/TECHNICAL_DEBT.md** — deferred ideas explicitly not to be
  implemented before their milestone.

---

# Engineering Principles

Always prefer:

- small changes and minimal diffs;
- backward compatibility;
- explicit constructor injection;
- existing implementations and existing architecture;
- immutable records, defensive copies, deterministic behavior;
- independently testable, replaceable components.

Never introduce unnecessary complexity, speculative abstractions,
global mutable state, hidden coupling or circular imports.

---

# Architecture Policy

- The **legacy v3.x execution stack** (planner, execution orchestrator /
  pipeline / session / coordinator / result / progress / event, skill
  registry, skill dispatch) is **frozen** and read-only.
- The **v8.x Foundation and tool stack** is the active, additive
  extension surface. New capability is added as new v8.x modules bridged
  to the legacy stack through explicit adapters, never by modifying it.
- Do not redesign architecture. Do not introduce new architectural
  layers unless fixing a proven defect or fulfilling a roadmap milestone —
  including a milestone formally discovered and recorded under
  `AUTONOMOUS_BUILD_PROTOCOL.md` §25 (evidence-justified, audited,
  additive, smallest missing layer first).
- Prefer extending existing v8.x modules over new abstractions, but do
  not reuse a legacy abstraction where doing so creates semantic
  coupling between the two runtimes.
- `core/agent/__init__.py` is a composition root: thin wiring only.
- Public APIs and `core.agent.__all__` are stable unless a milestone
  explicitly authorizes a change.

---

# Scope Control

- Implement only the current milestone (or an explicitly authorized,
  tightly coupled batch).
- Do not expand scope, refactor unrelated code, rewrite stable
  implementations, or modify unrelated files.
- Do not implement future systems early (see
  `AUTONOMOUS_BUILD_PROTOCOL.md` §14 and `docs/TECHNICAL_DEBT.md`).

---

# Development Workflow

1. Read the governance documents once, in hierarchy order.
2. Establish the current repository state (`git status`, roadmap,
   full-suite baseline).
3. Read only the files required for the milestone; perform discovery
   before touching an architectural boundary.
4. Implement the milestone with tests.
5. Pass all verification gates (`AUTONOMOUS_BUILD_PROTOCOL.md` §11).
6. Produce the checkpoint report.
7. **Explicit request:** stop and list the next milestone.
   **Autonomous run:** continue per `AUTONOMOUS_BUILD_PROTOCOL.md` §22;
   when no milestone is defined, discover, audit and formally record the
   next justified one (§25) before implementing it. Only a defined STOP
   condition (§13) ends an autonomous run.

---

# Testing Policy

- Every milestone requires tests; every discovered bug gets a
  regression test where practical.
- Run focused tests, then the **entire** suite; completion requires
  0 failures, 0 errors, 0 unexpected skips.
- Never weaken, delete, skip or hide tests to make a suite pass.
- Architecture/import-isolation tests are part of the suite; adjust an
  existing guard only by the smallest sanctioned change when a new module
  is a legitimate consumer, and say so in the report.

---

# Token Efficiency

Token efficiency is a permanent requirement but never outranks
correctness, verification or safety.

- Read repository documents once; do not reread unchanged files.
- Avoid unnecessary exploration, explanation and summaries.
- Keep responses implementation-focused and concise.
- Prefer unified diffs for modified files; print full contents only for
  new files when required.

---

# Git Policy

- Do not rewrite git history, modify branches, hard-reset or discard
  uncommitted user work.
- Do not change repository structure unless requested.
- Keep commits focused on a single milestone.
- Report git state at every checkpoint.

---

# Decision Policy

- If the correct implementation is obvious from repository evidence,
  implement it.
- If architecture is ambiguous, a frozen module would need changing, or
  a breaking change appears necessary, STOP and explain
  (`AUTONOMOUS_BUILD_PROTOCOL.md` §13).
- Never invent architecture or silently change public APIs.

---

# Definition of Done

A milestone is complete only when:

- the requested work is implemented and tested;
- existing architecture and frozen modules are preserved;
- public APIs remain backward compatible;
- focused tests, the full suite and architecture checks all pass;
- no unrelated files were modified and scope was not expanded;
- the checkpoint report reflects real test output.

---

# Implementation Agent Rules

These rules apply to every implementation agent, present or future
(Claude Code, Codex, Gemini CLI, Aider, etc.):

- Read `MARK-L.md` exactly once and follow the referenced documents.
- Do not redesign architecture; implement only the current milestone.
- Prefer minimal diffs; reuse existing implementations.
- Never modify unrelated or frozen files.
- Minimize token usage without skipping verification.
- After completion: stop for an explicit request, or continue
  autonomously per `AUTONOMOUS_BUILD_PROTOCOL.md` when running an
  autonomous build (discovering the next justified milestone when the
  roadmap has none) — never both silently.
- Never create a milestone from preference, novelty or a vision document
  alone; every milestone needs repository evidence and a contract audit.

# End of MARK-L Master Governance
