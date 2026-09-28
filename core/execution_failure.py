"""MARK L v8.28 — Execution Failure Normalization.

A small, provider-neutral value describing one failed execution attempt,
shared by every execution path that writes failure evidence back
(v8.27 lifecycle path, v8.28 projection-writeback path).

Only structured data is kept: the exception's **type name**, the
``PipelineRun`` id, the failed stage's tool name (when known) and the
caller's project. The exception object itself, its message, repr, args
and traceback are never read or stored — exception text may carry
secrets, paths, user data or tool arguments.

Pure and deterministic: no I/O, no state, no writes.

Dependency direction:

    Agent  →  execution_failure
    execution_failure  →  anything in core.*   (forbidden; stdlib only)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

__all__ = ["ExecutionFailure", "normalize_execution_failure"]


@dataclass(frozen=True, slots=True)
class ExecutionFailure:
    """Immutable, sanitized description of one failed execution attempt."""

    exception_type: str
    run_id: str
    tool_name: Optional[str]
    project: Optional[str]


def normalize_execution_failure(
    exc: BaseException,
    *,
    run_id: str,
    tool_name: Optional[str] = None,
    project: Optional[str] = None,
) -> ExecutionFailure:
    """Build the ``ExecutionFailure`` for ``exc``.

    Reads only ``type(exc).__name__`` from the exception.

    Raises:
        TypeError: ``exc`` is not an exception instance.
        ValueError: ``run_id`` is not a non-blank string.
    """
    if not isinstance(exc, BaseException):
        raise TypeError("exc must be an exception instance")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    return ExecutionFailure(
        exception_type=type(exc).__name__,
        run_id=run_id,
        tool_name=tool_name,
        project=project,
    )
