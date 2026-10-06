"""Tests for v7.2 Gemini Provider (Real Transport, mocked SDK)."""

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
from core.gemini_provider import GeminiProvider


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply_text: str = "gemini-mock-reply"

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.reply_text)


class _FakeGenAIClient:
    def __init__(self) -> None:
        self.models = _FakeModels()
        self.init_kwargs: dict = {}


def test_satisfies_ai_provider() -> None:
    provider: AIProvider = GeminiProvider(client=_FakeGenAIClient())
    assert hasattr(provider, "name")
    assert callable(getattr(provider, "complete", None))


def test_name_is_gemini() -> None:
    assert GeminiProvider(client=_FakeGenAIClient()).name == "gemini"


def test_default_model_stored() -> None:
    assert GeminiProvider(client=_FakeGenAIClient()).model == "gemini-2.5-pro"


def test_custom_model_stored() -> None:
    p = GeminiProvider(model="gemini-2.0-flash", client=_FakeGenAIClient())
    assert p.model == "gemini-2.0-flash"


def test_injected_client_is_used() -> None:
    fake = _FakeGenAIClient()
    p = GeminiProvider(client=fake)
    out = p.complete(AIRequest(prompt="hi"))
    assert isinstance(out, AIResponse)
    assert out.provider_name == "gemini"
    assert out.text == "gemini-mock-reply"
    assert len(fake.models.calls) == 1


def test_prompt_forwarded_unchanged() -> None:
    fake = _FakeGenAIClient()
    GeminiProvider(client=fake).complete(AIRequest(prompt="forwarded-prompt"))
    call = fake.models.calls[0]
    assert call["contents"] == "forwarded-prompt"


def test_model_forwarded_unchanged() -> None:
    fake = _FakeGenAIClient()
    GeminiProvider(model="gemini-2.0-flash", client=fake).complete(AIRequest(prompt="x"))
    call = fake.models.calls[0]
    assert call["model"] == "gemini-2.0-flash"


def test_ai_response_created_correctly() -> None:
    fake = _FakeGenAIClient()
    fake.models.reply_text = "the-actual-reply"
    out = GeminiProvider(client=fake).complete(AIRequest(prompt="x"))
    assert isinstance(out, AIResponse)
    assert out.text == "the-actual-reply"
    assert out.provider_name == "gemini"


def test_provider_name_is_gemini() -> None:
    fake = _FakeGenAIClient()
    assert GeminiProvider(client=fake).complete(AIRequest(prompt="x")).provider_name == "gemini"


def test_call_count_increments() -> None:
    p = GeminiProvider(client=_FakeGenAIClient())
    assert p.call_count == 0
    p.complete(AIRequest(prompt="a"))
    p.complete(AIRequest(prompt="b"))
    assert p.call_count == 2


def test_lazy_client_creation() -> None:
    """No client supplied — provider must defer SDK init until first use."""
    p = GeminiProvider(api_key="gem-test-key")
    assert p._client is None
    import core.gemini_provider as mod
    real_get = mod.GeminiProvider._get_client

    created: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            created["args"] = (a, kw)
            self.models = _FakeModels()

    class _StubGenAIModule:
        Client = _StubSDKClient

    class _StubGoogleModule:
        genai = _StubGenAIModule()

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "google", _StubGoogleModule())
        p._client = None
        client = real_get(p)
        assert isinstance(client, _StubSDKClient)
        assert "args" in created
    finally:
        monkey.undo()


def test_lazy_client_uses_api_key() -> None:
    """When no client is injected, the SDK client must receive the api_key."""
    import core.gemini_provider as mod
    p = GeminiProvider(api_key="gem-lazy-key")
    p._client = None

    captured: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            captured["args"] = (a, kw)
            self.models = _FakeModels()

    class _StubGenAIModule:
        Client = _StubSDKClient

    class _StubGoogleModule:
        genai = _StubGenAIModule()

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "google", _StubGoogleModule())
        mod.GeminiProvider._get_client(p)
        args, kwargs = captured["args"]
        assert kwargs.get("api_key") == "gem-lazy-key" or (
            args and getattr(args[0], "api_key", None) == "gem-lazy-key"
        )
    finally:
        monkey.undo()


def test_deterministic_mocked_responses() -> None:
    p = GeminiProvider(client=_FakeGenAIClient())
    a = p.complete(AIRequest(prompt="x"))
    b = p.complete(AIRequest(prompt="x"))
    assert a.text == b.text == "gemini-mock-reply"


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_provider_and_google_sdk(self) -> None:
        import ast

        from core import gemini_provider as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_root_modules = {"core", "google", "typing", "__future__", "json"}  # v8.40: tool-call arguments are JSON
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_registry", "core.ai_provider_router",
            "core.ai_conversation_engine", "core.ai_service",
            "core.default_ai_provider_registry", "core.openai_provider",
            "core.claude_provider", "core.gemini_provider",
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
        p = GeminiProvider(client=_FakeGenAIClient())
        reg.register(p)
        assert reg.has("gemini")
        assert reg.get("gemini") is p

    def test_duplicate_gemini_registration_raises(self) -> None:
        reg = AIProviderRegistry()
        reg.register(GeminiProvider(client=_FakeGenAIClient()))
        with pytest.raises(AIProviderAlreadyRegisteredError):
            reg.register(GeminiProvider(client=_FakeGenAIClient()))


class TestRouterCompatibility:
    def test_router_selects_gemini(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeGenAIClient()
        p = GeminiProvider(client=fake)
        reg.register(p)
        selected = AIProviderRouter(reg).select("gemini")
        assert selected is p
        out = selected.complete(AIRequest(prompt="hi"))
        assert out.text == "gemini-mock-reply"

    def test_router_unknown_raises(self) -> None:
        with pytest.raises(AIProviderUnavailableError):
            AIProviderRouter(AIProviderRegistry()).select("gemini")


class TestConversationEngineCompatibility:
    def test_engine_uses_gemini_end_to_end(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeGenAIClient()
        reg.register(GeminiProvider(client=fake))
        out = AIConversationEngine(AIProviderRouter(reg)).complete(
            "gemini", AIRequest(prompt="hi")
        )
        assert isinstance(out, AIResponse)
        assert out.text == "gemini-mock-reply"
        assert out.provider_name == "gemini"
        assert len(fake.models.calls) == 1