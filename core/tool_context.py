"""MARK L v8.39 — Tool Context Rendering (deterministic text for token counting).

Renders the tool declarations offered to a model and the completed tool
exchanges of a run into one deterministic text, so ``ContextManager`` can
count them as required context through its injected ``TokenCounter`` (owner
decision OD-A). Only data that is actually sent to a provider is rendered:

* each tool: ``name``, ``description`` and ``parameters`` — never the policy
  flags (``idempotent`` / ``side_effects`` / ``model_invocable``);
* each exchange: its ``text``, every call's id, name and arguments, and every
  result's id, name and output.

Canonical JSON (sorted keys, fixed separators, no ASCII escaping), so the same
input always renders the same text. The inputs are read by attribute only
(duck-typed), so this leaf imports no ``core`` module and carries no provider,
model or counting logic. No I/O, no state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

__all__ = ["render_tool_context"]


def _plain(value: object) -> object:
    """Deep plain copy (mappings -> dict, sequences -> list) for ``json``."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def render_tool_context(tools: Sequence[object], exchanges: Sequence[object]) -> str:
    """Return the deterministic text of ``tools`` and ``exchanges``.

    ``""`` when both are empty.
    """
    if not tools and not exchanges:
        return ""
    document = {
        "tools": [
            {"name": spec.name, "description": spec.description, "parameters": _plain(spec.parameters)}
            for spec in tools
        ],
        "exchanges": [
            {
                "text": exchange.text,
                "calls": [
                    {"id": call.call_id, "name": call.name, "arguments": _plain(call.arguments)}
                    for call in exchange.calls
                ],
                "results": [
                    {"id": result.call_id, "name": result.name, "output": result.output}
                    for result in exchange.results
                ],
            }
            for exchange in exchanges
        ],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
