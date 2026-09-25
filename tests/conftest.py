"""Test infrastructure: install stub ``openai`` and ``anthropic``
packages if the real ones are not importable, so the v7.x lazy
SDK imports always succeed without contacting the network and
without the test suite requiring those optional dependencies.

This is a test-only fixture (auto-discovered by pytest). It does
NOT alter production code, modules, services, registries, routers,
or any architectural component.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace


def _install_openai_stub() -> None:
    if "openai" in sys.modules:
        return

    stub = types.ModuleType("openai")

    class _StubCompletions:
        def __init__(self) -> None:
            self.reply_text = "openai-mock-reply"
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply_text))]
            )

    class _StubChat:
        def __init__(self) -> None:
            self.completions = _StubCompletions()

    class _StubClient:
        def __init__(self, *args, **kwargs):
            self.chat = _StubChat()
            self.init_args = (args, kwargs)

    stub.OpenAI = _StubClient
    sys.modules["openai"] = stub


def _install_anthropic_stub() -> None:
    if "anthropic" in sys.modules:
        return

    stub = types.ModuleType("anthropic")

    class _StubMessages:
        def __init__(self) -> None:
            self.reply_text = "claude-mock-reply"
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=self.reply_text)]
            )

    class _StubClient:
        def __init__(self, *args, **kwargs):
            self.messages = _StubMessages()
            self.init_args = (args, kwargs)

    stub.Anthropic = _StubClient
    sys.modules["anthropic"] = stub


_install_openai_stub()
_install_anthropic_stub()


def _install_ollama_stub() -> None:
    """Stub the ``ollama`` SDK surface used by v7.3's lazy import path."""
    if "ollama" in sys.modules:
        return

    stub = types.ModuleType("ollama")

    class _StubClient:
        def __init__(self, *args, **kwargs):
            self.calls: list[dict] = []
            self.reply_text = "ollama-mock-reply"
            self.init_args = (args, kwargs)

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return {"response": self.reply_text}

    stub.Client = _StubClient
    sys.modules["ollama"] = stub


_install_ollama_stub()


def _install_google_stub() -> None:
    """Stub the ``google`` / ``google.genai`` SDK surface used by
    v7.2's lazy import path. ``google`` is a namespace package so
    we install a single ``google`` module exposing ``genai``."""
    if "google" in sys.modules and getattr(
        sys.modules.get("google"), "genai", None
    ) is not None:
        return

    class _StubModels:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.reply_text = "gemini-mock-reply"

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text=self.reply_text)

    class _StubClient:
        def __init__(self, *args, **kwargs):
            self.models = _StubModels()
            self.init_args = (args, kwargs)

    class _StubGenAI:
        Client = _StubClient

    google_mod = sys.modules.get("google")
    if google_mod is None:
        google_mod = types.ModuleType("google")
        sys.modules["google"] = google_mod
    google_mod.genai = _StubGenAI


_install_google_stub()