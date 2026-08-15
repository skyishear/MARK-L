"""
core/skill_registry.py — CORE skill/plugin registry.

This is CORE infrastructure, not a feature (per the architecture spec's
CORE ≠ FEATURES principle). It lets independent skills — browser control,
weather, spotify, coding helpers, anything — register themselves with a
standard manifest instead of being hardcoded into main.py's tool list and
if/elif dispatch chain.

Adding a brand-new capability later means: drop one file into skills/
that builds a SkillManifest and calls register_skill(SKILL) at import
time. main.py never needs to change.

Each skill declares:
  - name, description, version
  - risk_level (low | medium | high) — for a future permission system
  - permissions  — what kinds of access it needs (e.g. 'open_browser',
    'filesystem_write', 'network')
  - dependencies — extra pip packages it needs beyond requirements.txt
  - tools        — Gemini function-declaration dicts (same shape main.py
    already used for TOOL_DECLARATIONS)
  - handler      — a callable (tool_name, args, ctx) -> result string
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class SkillManifest:
    name: str
    description: str
    tools: list[dict]
    handler: Callable[[str, dict, dict], str]
    version: str = "1.0"
    risk_level: str = "low"                     # low | medium | high
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


_skills: dict[str, SkillManifest] = {}       # skill name -> manifest
_tool_index: dict[str, SkillManifest] = {}   # tool name  -> owning manifest


def register_skill(manifest: SkillManifest) -> SkillManifest:
    """Called by a skill module at import time. Raises if a tool name
    is already claimed by another skill, so conflicts fail loudly at
    startup instead of silently shadowing a tool."""
    if not manifest.tools:
        raise ValueError(f"Skill '{manifest.name}' declares no tools.")
    for tool in manifest.tools:
        tool_name = tool["name"]
        if tool_name in _tool_index and _tool_index[tool_name] is not manifest:
            owner = _tool_index[tool_name].name
            raise ValueError(
                f"Tool '{tool_name}' from skill '{manifest.name}' conflicts "
                f"with the same tool already registered by skill '{owner}'."
            )
        _tool_index[tool_name] = manifest
    _skills[manifest.name] = manifest
    print(f"[Skills] ✅ Registered '{manifest.name}' "
          f"({len(manifest.tools)} tool(s), risk={manifest.risk_level})")
    return manifest


def discover_skills(skills_dir: Optional[Path] = None) -> int:
    """Import every .py file under skills/ so they self-register via
    register_skill(). Idempotent — a module already imported is skipped,
    so it's safe to call more than once (e.g. on a future 'reload skills')."""
    if skills_dir is None:
        skills_dir = Path(__file__).resolve().parent.parent / "skills"
    if not skills_dir.exists():
        return 0

    loaded = 0
    for path in sorted(skills_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"skills.{path.stem}"
        if mod_name in sys.modules:
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            loaded += 1
        except Exception as e:
            print(f"[Skills] ⚠️ Failed to load skill '{path.name}': {e}")
            sys.modules.pop(mod_name, None)
    return loaded


def get_tool_declarations() -> list[dict]:
    """Flat list of Gemini function declarations from every registered skill —
    merge this into the tools list sent to the Gemini Live session."""
    decls = []
    for manifest in _skills.values():
        decls.extend(manifest.tools)
    return decls


def dispatch(tool_name: str, args: dict, ctx: dict | None = None):
    """Run the handler for a registered tool. Returns None if no skill
    owns this tool name — caller should fall back to legacy dispatch."""
    manifest = _tool_index.get(tool_name)
    if not manifest:
        return None
    return manifest.handler(tool_name, args, ctx or {})


def is_registered(tool_name: str) -> bool:
    return tool_name in _tool_index


def list_skills() -> list[dict]:
    """For introspection/debugging — e.g. a future dashboard panel."""
    return [
        {
            "name": m.name, "description": m.description, "version": m.version,
            "risk_level": m.risk_level, "permissions": m.permissions,
            "dependencies": m.dependencies,
            "tools": [t["name"] for t in m.tools],
        }
        for m in _skills.values()
    ]
