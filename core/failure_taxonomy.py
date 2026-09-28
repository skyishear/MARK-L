"""MARK L v8.30 — Execution Failure Taxonomy.

A small, provider-neutral classification vocabulary for execution
failures, plus a pure classifier. It is a **foundation only**: nothing is
retried, resumed, re-raised differently or written differently because of
it. Future retry / resume policy decides what, if anything, to do with a
category.

Categories:

* ``TRANSIENT``     — potentially temporary according to the classifier.
                      It does **not** mean "retry", "safe to retry",
                      "idempotent" or "free of side effects".
* ``PERMANENT``     — not considered retryable by classification alone.
* ``INVALID_INPUT`` — the request / input is invalid.
* ``UNKNOWN``       — no category can be established safely.

Classification uses **only the exception's class** (walked along its
MRO, most specific first) against a caller-supplied rule mapping of
exception classes to categories; the exception's message, repr, args and
traceback are never read, and nothing is stored. Anything not covered by
a rule is ``UNKNOWN`` — generic Python exceptions are never assumed to be
transient.

The rules are supplied by the composition root (the Agent owns the
execution rule table), so this module depends on nothing in ``core.*``.

Dependency direction:

    Agent  →  failure_taxonomy
    failure_taxonomy  →  anything in core.*   (forbidden; stdlib only)
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

__all__ = ["FailureCategory", "classify_failure"]


class FailureCategory(str, Enum):
    """Finite execution-failure taxonomy (values are stable)."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    INVALID_INPUT = "invalid_input"
    UNKNOWN = "unknown"


def classify_failure(
    exc: BaseException,
    rules: Mapping[type, FailureCategory],
) -> FailureCategory:
    """Return the category of ``exc`` under ``rules``.

    The most specific class in ``type(exc).__mro__`` that has a rule wins;
    with no matching rule the result is ``FailureCategory.UNKNOWN``.

    Raises:
        TypeError: ``exc`` is not an exception instance, or ``rules`` is not
            a mapping of exception classes to ``FailureCategory`` values.
    """
    if not isinstance(exc, BaseException):
        raise TypeError("exc must be an exception instance")
    if not isinstance(rules, Mapping):
        raise TypeError("rules must be a mapping")
    for cls, category in rules.items():
        if not (isinstance(cls, type) and issubclass(cls, BaseException)):
            raise TypeError("rule keys must be exception classes")
        if not isinstance(category, FailureCategory):
            raise TypeError("rule values must be FailureCategory members")
    for cls in type(exc).__mro__:
        category = rules.get(cls)
        if category is not None:
            return category
    return FailureCategory.UNKNOWN
