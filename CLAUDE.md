# CLAUDE.md

## MARK L Repository Context

Repository: MARK-L
Current Version: v3.0.0-foundation
Status: Stable Foundation
Git Tag: v3.0.0-foundation

## Repository Is The Source Of Truth

Always treat the current repository as the only source of truth.
Never rely on previous conversations or assumptions.

## Architecture Rules

- Preserve the existing architecture.
- Make incremental changes only.
- Never redesign working components.
- Never rewrite code unless explicitly requested.
- Never create duplicate implementations.

## Development Rules

- Modify only the files required for the task.
- Keep diffs as small as possible.
- Preserve public APIs unless instructed otherwise.
- Run only the minimum verification required.
- Stop after completing the requested task.
- If additional work is identified, list it under "Next Steps".

## Safety Rules

- Never modify unrelated files.
- Never modify .gitignore unless requested.
- Never modify Git history.
- Never modify configuration, secrets, certificates, databases, caches, build artifacts or virtual environments unless explicitly requested.

## Response Format

Every implementation response should contain:

1. Analysis
2. Files Modified
3. Exact Code Changes
4. Tests
5. Breaking Changes
6. Final Verification

## Current Milestone

v3.1.0 - Planning Engine

## Completed Milestones

- Foundation Architecture
- Agent Composition Root
- Foundation Managers
- Dependency Injection
- Regression Tests
- GitHub Sync
- Golden Snapshot
