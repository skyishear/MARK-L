"""
core/problem_solver.py — CORE problem-solving & verification engine.

Two responsibilities, matching the architecture spec:

1. DIAGNOSIS SUPPORT (spec §11/§12)
   Before Gemini reasons from scratch about a problem, check whether a
   similar problem was already solved before (failure memory) and surface
   the relevant project decisions/constraints as a context bundle. This
   engine does not "think" for the model — Gemini still does the actual
   diagnosis/solution generation — but it makes sure Gemini isn't
   reasoning blind on a problem that already has a known-good answer.

2. EXECUTE → VERIFY → RETRY (spec §13)
   A small generic wrapper any skill can use: run an action, then run a
   verifier that actually checks the world changed as expected — never
   assume success just because a command returned without raising.
   On failure it can retry once, and either way the outcome gets handed
   to record_outcome() so future problem-solving benefits from it.

Both responsibilities are backed by ``core.memory_engine.MemoryEngine``
(via the Agent-owned instance, installed through ``set_memory_engine``).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.memory_engine import MemoryEngine

# ── Engine wiring ─────────────────────────────────────────────────────────

# A single, module-level MemoryEngine instance is the canonical
# memory backend. The Agent installs its own MemoryEngine into this
# slot at construction time; any other consumer can also call
# ``set_memory_engine`` to point the module at a different engine.
_engine: MemoryEngine = MemoryEngine()


def set_memory_engine(engine: MemoryEngine) -> None:
    """Install ``engine`` as the canonical memory backend for this
    module. Idempotent; resets to a fresh engine on ``None``.
    """
    global _engine
    _engine = engine if engine is not None else MemoryEngine()


def get_memory_engine() -> MemoryEngine:
    """Return the currently installed memory engine (never ``None``)."""
    return _engine


# ── Memory primitives (routed through the installed engine) ───────────────

def _remember(
    category: str,
    key: str,
    value: str,
    *,
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "solver",
    project: Optional[str] = None,
    memory_type: str = "permanent",
    sensitive: bool = False,
    ttl_days: Optional[int] = None,
) -> str:
    return _engine.remember(
        category,
        key,
        value,
        importance=importance,
        confidence=confidence,
        source=source,
        project=project,
        memory_type=memory_type,
        sensitive=sensitive,
        ttl_days=ttl_days,
    )


def _recall(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    project: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 25,
) -> list[dict]:
    return _engine.recall(
        query=query,
        category=category,
        project=project,
        memory_type=memory_type,
        limit=limit,
    )


def _forget(
    *,
    key: Optional[str] = None,
    category: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    return _engine.forget(key=key, category=category, project=project)


# Public, module-level proxies. These names are stable so existing
# callers (and tests) can monkeypatch them in place to redirect
# the canonical memory backend for the duration of a test.
def remember(
    category: str,
    key: str,
    value: str,
    *,
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "solver",
    project: Optional[str] = None,
    memory_type: str = "permanent",
    sensitive: bool = False,
    ttl_days: Optional[int] = None,
) -> str:
    return _remember(
        category, key, value,
        importance=importance,
        confidence=confidence,
        source=source,
        project=project,
        memory_type=memory_type,
        sensitive=sensitive,
        ttl_days=ttl_days,
    )


def recall(
    *,
    query: Optional[str] = None,
    category: Optional[str] = None,
    project: Optional[str] = None,
    memory_type: Optional[str] = None,
    limit: int = 25,
) -> list[dict]:
    return _recall(
        query=query,
        category=category,
        project=project,
        memory_type=memory_type,
        limit=limit,
    )


def forget(
    *,
    key: Optional[str] = None,
    category: Optional[str] = None,
    project: Optional[str] = None,
) -> int:
    return _forget(key=key, category=category, project=project)


def why(project: Optional[str] = None, query: Optional[str] = None) -> list[dict]:
    """Return a list of past project decisions relevant to ``query``.

    In v8.1 this is a stub returning an empty list — decisions live
    in a future layer. Kept on the module surface so the existing
    ``gather_context`` API and downstream test fixtures can monkey-
    patch it in place.
    """
    return []


# ── Diagnosis support ────────────────────────────────────────────────────

def gather_context(problem: str, project: Optional[str] = None) -> dict:
    """Assemble everything already known that's relevant to a new problem:
    a previously-recorded solution if one exists, related project
    decisions (with their reasoning), and any other loosely related
    facts. Gemini uses this instead of reasoning from zero."""
    known_solutions = recall(query=problem, category="problems_solutions", limit=5)
    related_facts = recall(query=problem, project=project, limit=8)
    related_decisions: list[dict] = why(project, problem) if project else []

    return {
        "known_solutions": known_solutions,
        "related_facts": related_facts,
        "related_decisions": related_decisions,
        "has_known_fix": any(k["value"].startswith("SOLVED") for k in known_solutions),
    }


def format_context_for_solver(problem: str, project: Optional[str] = None) -> str:
    """Human/LLM-readable version of gather_context(), sized for a tool
    response so Gemini can read it directly."""
    ctx = gather_context(problem, project)
    lines = []

    if ctx["known_solutions"]:
        lines.append("Previously seen similar problems:")
        for k in ctx["known_solutions"]:
            lines.append(f"  - {k['value']}")

    if ctx["related_decisions"]:
        lines.append("Relevant past decisions:")
        for d in ctx["related_decisions"]:
            reason = f" (because: {d['reasoning']})" if d["reasoning"] else ""
            lines.append(f"  - {d['decision']}{reason}")

    if ctx["related_facts"]:
        lines.append("Other relevant known facts:")
        for f in ctx["related_facts"][:5]:
            lines.append(f"  - {f['category']}/{f['key']}: {f['value']}")

    if not lines:
        return "No prior context found for this problem — reason from scratch, then verify before declaring success."

    return "\n".join(lines)


def record_outcome(problem: str, cause: str, solution: str, outcome: str,
                    project: Optional[str] = None) -> str:
    """Save problem → cause → solution → outcome to failure memory.
    Successful outcomes get high importance/confidence so they surface
    first next time a similar problem comes up."""
    success = outcome.strip().lower() in {"success", "solved", "fixed", "worked"}
    value = f"{'SOLVED' if success else 'FAILED'} | problem: {problem} | cause: {cause} | solution: {solution} | outcome: {outcome}"
    key = "_".join(problem.lower().split())[:60] or "problem"
    return remember(
        "problems_solutions", key, value,
        importance=5 if success else 3,
        confidence=1.0 if success else 0.5,
        project=project,
        source="solver",
    )


# ── Execute → verify → retry ─────────────────────────────────────────────

@dataclass
class ExecutionResult:
    success: bool
    result: Any
    attempts: int
    verified: bool


def execute_and_verify(
    action_fn: Callable[[], Any],
    verify_fn: Callable[[], bool],
    *,
    max_retries: int = 1,
    retry_delay: float = 0.5,
) -> ExecutionResult:
    """Run action_fn(), then verify_fn() to confirm the world actually
    changed as expected — never trust a command's return value alone.
    Retries the action (not just the check) up to max_retries times on
    verification failure."""
    attempts = 0
    result = None
    verified = False

    while attempts <= max_retries:
        attempts += 1
        result = action_fn()
        verified = bool(verify_fn())
        if verified:
            break
        if attempts <= max_retries:
            time.sleep(retry_delay)

    return ExecutionResult(success=verified, result=result, attempts=attempts, verified=verified)


# ── Built-in verifiers ────────────────────────────────────────────────────

def verify_path_exists(path) -> bool:
    from pathlib import Path
    return Path(path).exists()


def verify_process_running(process_name: str) -> bool:
    try:
        import psutil
    except ImportError:
        return False
    name_lower = process_name.lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if name_lower in (proc.info.get("name") or "").lower():
                return True
        except Exception:
            continue
    return False


def verify_url_reachable(url: str, timeout: float = 4.0) -> bool:
    try:
        import requests
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        try:
            import requests
            resp = requests.get(url, timeout=timeout)
            return resp.status_code < 400
        except Exception:
            return False


__all__ = [
    "set_memory_engine",
    "get_memory_engine",
    "remember",
    "recall",
    "forget",
    "why",
    "gather_context",
    "format_context_for_solver",
    "record_outcome",
    "ExecutionResult",
    "execute_and_verify",
    "verify_path_exists",
    "verify_process_running",
    "verify_url_reachable",
]