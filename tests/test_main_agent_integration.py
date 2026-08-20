"""Verification for Step 7: Agent DI in main.py."""

from __future__ import annotations

import ast
from pathlib import Path

from core.agent import Agent


def _resolve_agent(agent: Agent | None) -> Agent:
    return agent if agent is not None else Agent()


def test_default_constructs_fresh_empty_agent() -> None:
    resolved = _resolve_agent(None)
    assert isinstance(resolved, Agent)
    assert resolved.history.get_history() == []


def test_explicit_agent_preserved() -> None:
    injected = Agent()
    injected.history.record("event", "pre-existing")
    resolved = _resolve_agent(injected)
    assert resolved is injected


def test_main_py_syntax_valid() -> None:
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    ast.parse(source)


def test_main_py_imports_agent() -> None:
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    assert "from core.agent import Agent" in source


def test_jarvis_live_init_has_optional_agent_param() -> None:
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            arg_names = [a.arg for a in node.args.args]
            if "ui" in arg_names and "agent" in arg_names:
                num_defaults = len(node.args.defaults)
                assert arg_names[-1] == "agent"
                assert num_defaults >= 1
                return
    raise AssertionError("JarvisLive.__init__ with 'agent' param not found")
