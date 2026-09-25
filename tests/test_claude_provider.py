"""Tests for v7.1 Claude Provider (Real Transport, mocked SDK)."""

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
from core.claude_provider import ClaudeProvider


class _FakeTextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply_text: str = "claude-mock-reply"

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[_FakeTextBlock(self.reply_text)])


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()
        self.init_kwargs: dict = {}


def test_satisfies_ai_provider() -> None:
    provider: AIProvider = ClaudeProvider(client=_FakeAnthropicClient())
    assert hasattr(provider, "name")
    assert callable(getattr(provider, "complete", None))


def test_name_is_claude() -> None:
    assert ClaudeProvider(client=_FakeAnthropicClient()).name == "claude"


def test_default_model_stored() -> None:
    assert ClaudeProvider(client=_FakeAnthropicClient()).model == "claude-3-5-sonnet-latest"


def test_custom_model_stored() -> None:
    p = ClaudeProvider(model="claude-3-opus-latest", client=_FakeAnthropicClient())
    assert p.model == "claude-3-opus-latest"


def test_injected_client_is_used() -> None:
    fake = _FakeAnthropicClient()
    p = ClaudeProvider(client=fake)
    out = p.complete(AIRequest(prompt="hi"))
    assert isinstance(out, AIResponse)
    assert out.provider_name == "claude"
    assert out.text == "claude-mock-reply"
    assert len(fake.messages.calls) == 1


def test_prompt_forwarded_unchanged() -> None:
    fake = _FakeAnthropicClient()
    ClaudeProvider(client=fake).complete(AIRequest(prompt="forwarded-prompt"))
    call = fake.messages.calls[0]
    assert call["messages"] == [{"role": "user", "content": "forwarded-prompt"}]


def test_model_forwarded_unchanged() -> None:
    fake = _FakeAnthropicClient()
    ClaudeProvider(model="claude-3-opus-latest", client=fake).complete(AIRequest(prompt="x"))
    call = fake.messages.calls[0]
    assert call["model"] == "claude-3-opus-latest"


def test_ai_response_created_correctly() -> None:
    fake = _FakeAnthropicClient()
    fake.messages.reply_text = "the-actual-reply"
    out = ClaudeProvider(client=fake).complete(AIRequest(prompt="x"))
    assert isinstance(out, AIResponse)
    assert out.text == "the-actual-reply"
    assert out.provider_name == "claude"


def test_provider_name_is_claude() -> None:
    fake = _FakeAnthropicClient()
    assert ClaudeProvider(client=fake).complete(AIRequest(prompt="x")).provider_name == "claude"


def test_call_count_increments() -> None:
    p = ClaudeProvider(client=_FakeAnthropicClient())
    assert p.call_count == 0
    p.complete(AIRequest(prompt="a"))
    p.complete(AIRequest(prompt="b"))
    assert p.call_count == 2


def test_lazy_client_creation() -> None:
    """No client supplied — provider must defer SDK init until first use."""
    p = ClaudeProvider(api_key="sk-test-ant")
    assert p._client is None
    import core.claude_provider as mod
    real_get = mod.ClaudeProvider._get_client

    created: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            created["args"] = (a, kw)
            self.messages = _FakeMessages()

    class _StubAnthropicModule:
        Anthropic = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "anthropic", _StubAnthropicModule())
        p._client = None
        client = real_get(p)
        assert isinstance(client, _StubSDKClient)
        assert "args" in created
    finally:
        monkey.undo()


def test_lazy_client_uses_api_key() -> None:
    """When no client is injected, the SDK client must receive the api_key."""
    import core.claude_provider as mod
    p = ClaudeProvider(api_key="sk-lazy-ant")
    p._client = None

    captured: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            captured["args"] = (a, kw)
            self.messages = _FakeMessages()

    class _StubAnthropicModule:
        Anthropic = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "anthropic", _StubAnthropicModule())
        mod.ClaudeProvider._get_client(p)
        args, kwargs = captured["args"]
        assert kwargs.get("api_key") == "sk-lazy-ant" or (
            args and getattr(args[0], "api_key", None) == "sk-lazy-ant"
        )
    finally:
        monkey.undo()


def test_deterministic_mocked_responses() -> None:
    p = ClaudeProvider(client=_FakeAnthropicClient())
    a = p.complete(AIRequest(prompt="x"))
    b = p.complete(AIRequest(prompt="x"))
    assert a.text == b.text == "claude-mock-reply"


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_provider_and_anthropic(self) -> None:
        import ast

        from core import claude_provider as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_root_modules = {"core", "anthropic", "typing", "__future__"}
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_registry", "core.ai_provider_router",
            "core.ai_conversation_engine", "core.ai_service",
            "core.default_ai_provider_registry", "core.openai_provider",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                root = parts[0]
                assert root in allowed_root_modules, (
                    f"Forbidden import: {node.module}"
                )
                if root == "core":
                    assert len(parts) >= 2 and parts[1] == "ai_provider", (
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
                        assert len(parts) >= 2 and parts[1] == "ai_provider", (
                            f"Forbidden import: {n.name}"
                        )


class TestRegistryCompatibility:
    def test_registers_in_ai_provider_registry(self) -> None:
        reg = AIProviderRegistry()
        p = ClaudeProvider(client=_FakeAnthropicClient())
        reg.register(p)
        assert reg.has("claude")
        assert reg.get("claude") is p

    def test_duplicate_claude_registration_raises(self) -> None:
        reg = AIProviderRegistry()
        reg.register(ClaudeProvider(client=_FakeAnthropicClient()))
        with pytest.raises(AIProviderAlreadyRegisteredError):
            reg.register(ClaudeProvider(client=_FakeAnthropicClient()))


class TestRouterCompatibility:
    def test_router_selects_claude(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeAnthropicClient()
        p = ClaudeProvider(client=fake)
        reg.register(p)
        selected = AIProviderRouter(reg).select("claude")
        assert selected is p
        out = selected.complete(AIRequest(prompt="hi"))
        assert out.text == "claude-mock-reply"

    def test_router_unknown_raises(self) -> None:
        with pytest.raises(AIProviderUnavailableError):
            AIProviderRouter(AIProviderRegistry()).select("claude")


class TestConversationEngineCompatibility:
    def test_engine_uses_claude_end_to_end(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeAnthropicClient()
        reg.register(ClaudeProvider(client=fake))
        out = AIConversationEngine(AIProviderRouter(reg)).complete(
            "claude", AIRequest(prompt="hi")
        )
        assert isinstance(out, AIResponse)
        assert out.text == "claude-mock-reply"
        assert out.provider_name == "claude"
        assert len(fake.messages.calls) == 1