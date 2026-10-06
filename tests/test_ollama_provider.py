"""Tests for v7.3 Ollama Provider (Real Transport, mocked SDK)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core.ai_conversation_engine import AIConversationEngine
from core.ai_provider import AIProvider, AIRequest, AIResponse
from core.ai_provider_registry import (
    AIProviderAlreadyRegisteredError,
    AIProviderRegistry,
)
from core.ai_provider_router import AIProviderRouter, AIProviderUnavailableError
from core.ollama_provider import OllamaProvider


class _FakeOllamaClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply_text: str = "ollama-mock-reply"
        self.init_kwargs: dict = {}

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {"response": self.reply_text}


def test_satisfies_ai_provider() -> None:
    provider: AIProvider = OllamaProvider(client=_FakeOllamaClient())
    assert hasattr(provider, "name")
    assert callable(getattr(provider, "complete", None))


def test_name_is_ollama() -> None:
    assert OllamaProvider(client=_FakeOllamaClient()).name == "ollama"


def test_default_model_stored() -> None:
    assert OllamaProvider(client=_FakeOllamaClient()).model == "llama3.1"


def test_custom_model_stored() -> None:
    p = OllamaProvider(model="qwen2.5:7b", client=_FakeOllamaClient())
    assert p.model == "qwen2.5:7b"


def test_injected_client_is_used() -> None:
    fake = _FakeOllamaClient()
    p = OllamaProvider(client=fake)
    out = p.complete(AIRequest(prompt="hi"))
    assert isinstance(out, AIResponse)
    assert out.provider_name == "ollama"
    assert out.text == "ollama-mock-reply"
    assert len(fake.calls) == 1


def test_prompt_forwarded_unchanged() -> None:
    fake = _FakeOllamaClient()
    OllamaProvider(client=fake).complete(AIRequest(prompt="forwarded-prompt"))
    call = fake.calls[0]
    assert call["prompt"] == "forwarded-prompt"


def test_model_forwarded_unchanged() -> None:
    fake = _FakeOllamaClient()
    OllamaProvider(model="qwen2.5:7b", client=fake).complete(AIRequest(prompt="x"))
    call = fake.calls[0]
    assert call["model"] == "qwen2.5:7b"


def test_ai_response_created_correctly() -> None:
    fake = _FakeOllamaClient()
    fake.reply_text = "the-actual-reply"
    out = OllamaProvider(client=fake).complete(AIRequest(prompt="x"))
    assert isinstance(out, AIResponse)
    assert out.text == "the-actual-reply"
    assert out.provider_name == "ollama"


def test_provider_name_is_ollama() -> None:
    fake = _FakeOllamaClient()
    assert OllamaProvider(client=fake).complete(AIRequest(prompt="x")).provider_name == "ollama"


def test_call_count_increments() -> None:
    p = OllamaProvider(client=_FakeOllamaClient())
    assert p.call_count == 0
    p.complete(AIRequest(prompt="a"))
    p.complete(AIRequest(prompt="b"))
    assert p.call_count == 2


def test_lazy_client_creation() -> None:
    """No client supplied — provider must defer SDK init until first use."""
    p = OllamaProvider(host="http://localhost:11434")
    assert p._client is None
    import core.ollama_provider as mod
    real_get = mod.OllamaProvider._get_client

    created: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            created["args"] = (a, kw)
            self.generate_calls: list = []

        def generate(self, **kwargs):
            self.generate_calls.append(kwargs)
            return {"response": "stub-reply"}

    class _StubOllamaModule:
        Client = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "ollama", _StubOllamaModule())
        p._client = None
        client = real_get(p)
        assert isinstance(client, _StubSDKClient)
        assert "args" in created
    finally:
        monkey.undo()


def test_lazy_client_uses_host() -> None:
    """When no client is injected, the SDK client must receive the host."""
    import core.ollama_provider as mod
    p = OllamaProvider(host="http://example.test:11434")
    p._client = None

    captured: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            captured["args"] = (a, kw)
            self.generate_calls: list = []

        def generate(self, **kwargs):
            return {"response": "stub-reply"}

    class _StubOllamaModule:
        Client = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "ollama", _StubOllamaModule())
        mod.OllamaProvider._get_client(p)
        args, kwargs = captured["args"]
        assert kwargs.get("host") == "http://example.test:11434" or (
            args and getattr(args[0], "host", None) == "http://example.test:11434"
        )
    finally:
        monkey.undo()


def test_deterministic_mocked_responses() -> None:
    p = OllamaProvider(client=_FakeOllamaClient())
    a = p.complete(AIRequest(prompt="x"))
    b = p.complete(AIRequest(prompt="x"))
    assert a.text == b.text == "ollama-mock-reply"


def test_attribute_response_format_supported() -> None:
    """The provider must also work when the SDK returns an object
    (e.g. ``SimpleNamespace``) instead of a dict."""
    fake = _FakeOllamaClient()
    # Replace the underlying generate to return an attribute-style object.
    def _gen(**kwargs):
        fake.calls.append(kwargs)
        return SimpleNamespace(response="attr-reply")
    fake.generate = _gen  # type: ignore[method-assign]
    out = OllamaProvider(client=fake).complete(AIRequest(prompt="x"))
    assert out.text == "attr-reply"
    assert out.provider_name == "ollama"


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_provider_and_ollama_sdk(self) -> None:
        import ast

        from core import ollama_provider as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_root_modules = {"core", "ollama", "typing", "__future__", "json"}  # v8.40: tool-call arguments are JSON
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_registry", "core.ai_provider_router",
            "core.ai_conversation_engine", "core.ai_service",
            "core.default_ai_provider_registry", "core.openai_provider",
            "core.claude_provider", "core.gemini_provider",
            "core.ollama_provider",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                root = parts[0]
                assert root in allowed_root_modules, (
                    f"Forbidden import: {node.module}"
                )
                if root == "core":
                    assert len(parts) >= 2 and parts[1] in ("ai_provider", "tool_calling"), (
                        f"Forbidden import: {node.module}"
                    )
                assert not any(
                    node.module.startswith(s) for s in forbidden_substrings
                )
            if isinstance(node, ast.Import):
                for n in node.names:
                    parts = n.name.split(".")
                    root = parts[0]
                    assert root in allowed_root_modules, (
                        f"Forbidden import: {n.name}"
                    )
                    if root == "core":
                        assert len(parts) >= 2 and parts[1] in ("ai_provider", "tool_calling"), (
                            f"Forbidden import: {n.name}"
                        )


class TestRegistryCompatibility:
    def test_registers_in_ai_provider_registry(self) -> None:
        reg = AIProviderRegistry()
        p = OllamaProvider(client=_FakeOllamaClient())
        reg.register(p)
        assert reg.has("ollama")
        assert reg.get("ollama") is p

    def test_duplicate_ollama_registration_raises(self) -> None:
        reg = AIProviderRegistry()
        reg.register(OllamaProvider(client=_FakeOllamaClient()))
        with pytest.raises(AIProviderAlreadyRegisteredError):
            reg.register(OllamaProvider(client=_FakeOllamaClient()))


class TestRouterCompatibility:
    def test_router_selects_ollama(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeOllamaClient()
        p = OllamaProvider(client=fake)
        reg.register(p)
        selected = AIProviderRouter(reg).select("ollama")
        assert selected is p
        out = selected.complete(AIRequest(prompt="hi"))
        assert out.text == "ollama-mock-reply"

    def test_router_unknown_raises(self) -> None:
        with pytest.raises(AIProviderUnavailableError):
            AIProviderRouter(AIProviderRegistry()).select("ollama")


class TestConversationEngineCompatibility:
    def test_engine_uses_ollama_end_to_end(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeOllamaClient()
        reg.register(OllamaProvider(client=fake))
        out = AIConversationEngine(AIProviderRouter(reg)).complete(
            "ollama", AIRequest(prompt="hi")
        )
        assert isinstance(out, AIResponse)
        assert out.text == "ollama-mock-reply"
        assert out.provider_name == "ollama"
        assert len(fake.calls) == 1