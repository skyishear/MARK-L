# MARK L

> Master Governance Entry Point

This is the primary entry point for every AI agent working on MARK L.

Before performing any work, read this document exactly once.

---

# Purpose

MARK L is a long-term AI operating system.

The objective is to build a stable, scalable, modular, maintainable and production-quality AI platform.

Every implementation must preserve long-term architecture.

---

# Repository Source of Truth

The repository is the only source of truth.

Never assume information from previous conversations.

Never invent missing architecture.

If repository content conflicts with conversation instructions, report the conflict before making changes.

---

# Repository Governance

Read the following documents exactly once and only when required.

## 1. CLAUDE.md

Defines:

- Repository development rules
- Coding philosophy
- Engineering standards
- Architecture constraints

---

## 2. PROMPT_RULES.md

Defines:

- Prompt workflow
- Output requirements
- Token efficiency rules
- Response format
- ZIP workflow

---

## 3. ROADMAP.md

Defines:

- Long-term roadmap
- Current development phase
- Planned milestones

---

## 4. PROJECT_STATUS.md

Defines:

- Current implementation status
- Completed work
- Remaining work
- Current milestone

---

## 5. DSH_ROLE.md (if present)

Defines:

- Lead Software Engineer responsibilities
- Authority
- Restrictions
- Engineering workflow

---

# Engineering Principles

Always prefer:

- Small changes
- Minimal diffs
- Backward compatibility
- Constructor injection
- Existing implementations
- Existing architecture

Never introduce unnecessary complexity.

---

# Architecture Policy

Architecture is considered stable.

Do not redesign architecture.

Do not introduce new architectural layers unless fixing a proven architectural defect.

Prefer extending existing implementations instead of creating new abstractions.

---

# Development Workflow

1. Read required governance documents.
2. Read only the files required for the milestone.
3. Implement only the requested milestone.
4. Modify only directly affected files.
5. Run only affected tests.
6. Package the repository if requested.
7. Stop after completion.

---

# Scope Control

Do not expand scope.

Do not perform unrelated refactoring.

Do not rewrite stable implementations.

Do not modify unrelated files.

Do not introduce speculative improvements.

---

# Token Efficiency

Token efficiency is a permanent requirement.

Read repository documents only once.

Never reread unchanged files.

Avoid unnecessary repository exploration.

Avoid unnecessary explanations.

Avoid unnecessary summaries.

Keep responses implementation-focused.

Minimize output tokens.

---

# Output Policy

Prefer unified diffs for modified files.

Avoid printing complete contents of existing files.

Print complete contents only for newly created files when explicitly required.

Keep responses concise.

---

# Testing Policy

Run only the minimum affected tests.

Do not run the entire test suite unless explicitly required.

Keep test additions minimal.

---

# Git Policy

Do not rewrite Git history.

Do not modify branches.

Do not change repository structure unless requested.

Keep commits focused on a single milestone.

---

# Decision Policy

If the correct implementation is obvious, implement it.

If architecture is unclear, stop and explain the issue.

Never invent architecture.

Never silently change public APIs.

---

# Definition of Done

A milestone is complete only when:

- Requested work is implemented.
- Existing architecture is preserved.
- Public APIs remain backward compatible.
- Tests pass.
- No unrelated files were modified.
- Scope was not expanded.

---

# End of MARK L Master Governance