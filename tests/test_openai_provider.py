"""Tests for v7.0 OpenAI Provider (Real Transport, mocked SDK)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core.ai_conversation_engine import AIConversationEngine
from core.ai_provider import AIProvider, AIRequest, AIResponse
from core.ai_provider_registry import AIProviderRegistry
from core.ai_provider_router import AIProviderRouter
from core.openai_provider import OpenAIProvider


class _FakeChoice:
    def __init__(self, text: str) -> None:
        self.message = SimpleNamespace(content=text)


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.reply_text: str = "openai-mock-reply"

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[_FakeChoice(self.reply_text)])


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()
        self.init_kwargs: dict = {}


def test_satisfies_ai_provider() -> None:
    provider: AIProvider = OpenAIProvider(client=_FakeOpenAIClient())
    assert hasattr(provider, "name")
    assert callable(getattr(provider, "complete", None))


def test_name_is_openai() -> None:
    assert OpenAIProvider(client=_FakeOpenAIClient()).name == "openai"


def test_default_model_stored() -> None:
    assert OpenAIProvider(client=_FakeOpenAIClient()).model == "gpt-4o-mini"


def test_custom_model_stored() -> None:
    p = OpenAIProvider(model="gpt-4o", client=_FakeOpenAIClient())
    assert p.model == "gpt-4o"


def test_injected_client_is_used() -> None:
    fake = _FakeOpenAIClient()
    p = OpenAIProvider(client=fake)
    out = p.complete(AIRequest(prompt="hi"))
    assert isinstance(out, AIResponse)
    assert out.provider_name == "openai"
    assert out.text == "openai-mock-reply"
    # The injected client received exactly one call.
    assert len(fake.chat.completions.calls) == 1


def test_prompt_forwarded_unchanged() -> None:
    fake = _FakeOpenAIClient()
    OpenAIProvider(client=fake).complete(AIRequest(prompt="forwarded-prompt"))
    call = fake.chat.completions.calls[0]
    assert call["messages"] == [{"role": "user", "content": "forwarded-prompt"}]


def test_model_forwarded_unchanged() -> None:
    fake = _FakeOpenAIClient()
    OpenAIProvider(model="gpt-4o", client=fake).complete(AIRequest(prompt="x"))
    call = fake.chat.completions.calls[0]
    assert call["model"] == "gpt-4o"


def test_ai_response_created_correctly() -> None:
    fake = _FakeOpenAIClient()
    fake.chat.completions.reply_text = "the-actual-reply"
    out = OpenAIProvider(client=fake).complete(AIRequest(prompt="x"))
    assert isinstance(out, AIResponse)
    assert out.text == "the-actual-reply"
    assert out.provider_name == "openai"


def test_provider_name_is_openai() -> None:
    fake = _FakeOpenAIClient()
    assert OpenAIProvider(client=fake).complete(AIRequest(prompt="x")).provider_name == "openai"


def test_call_count_increments() -> None:
    p = OpenAIProvider(client=_FakeOpenAIClient())
    assert p.call_count == 0
    p.complete(AIRequest(prompt="a"))
    p.complete(AIRequest(prompt="b"))
    assert p.call_count == 2


def test_lazy_client_creation() -> None:
    """No client supplied — provider must defer SDK init until first use."""
    p = OpenAIProvider(api_key="sk-test")
    # No real client should exist yet, and no OpenAI() call has happened.
    assert p._client is None
    # Now trigger lazy creation by injecting a fake via the import path
    # the provider uses. We assert that without an injected client the
    # provider attempts to import openai on demand.
    import core.openai_provider as mod
    real_get = mod.OpenAIProvider._get_client

    created: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            created["args"] = (a, kw)
            self.chat = _FakeChat()

    class _StubOpenAIModule:
        OpenAI = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "openai", _StubOpenAIModule())
        # Clear cached client and re-invoke.
        p._client = None
        client = real_get(p)
        assert isinstance(client, _StubSDKClient)
        assert "args" in created
    finally:
        monkey.undo()


def test_lazy_client_uses_api_key() -> None:
    """When no client is injected, the SDK client must receive the api_key."""
    import core.openai_provider as mod
    p = OpenAIProvider(api_key="sk-lazy")
    p._client = None

    captured: dict = {}

    class _StubSDKClient:
        def __init__(self, *a, **kw):
            captured["args"] = (a, kw)
            self.chat = _FakeChat()

    class _StubOpenAIModule:
        OpenAI = _StubSDKClient

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setitem(sys.modules, "openai", _StubOpenAIModule())
        mod.OpenAIProvider._get_client(p)
        # First positional-or-keyword arg must carry api_key.
        args, kwargs = captured["args"]
        assert kwargs.get("api_key") == "sk-lazy" or (
            args and getattr(args[0], "api_key", None) == "sk-lazy"
        )
    finally:
        monkey.undo()


def test_deterministic_mocked_responses() -> None:
    p = OpenAIProvider(client=_FakeOpenAIClient())
    a = p.complete(AIRequest(prompt="x"))
    b = p.complete(AIRequest(prompt="x"))
    assert a.text == b.text == "openai-mock-reply"


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_provider_and_openai(self) -> None:
        import ast

        from core import openai_provider as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_root_modules = {"core", "openai", "typing", "__future__", "json"}  # v8.40: tool-call arguments are JSON
        # When the import root is ``core``, the *first two* segments
        # identify the module (e.g. ``core.ai_provider``). The
        # check is split below.
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_registry", "core.ai_provider_router",
            "core.ai_conversation_engine", "core.ai_service",
            "core.default_ai_provider_registry",
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
        p = OpenAIProvider(client=_FakeOpenAIClient())
        reg.register(p)
        assert reg.has("openai")
        assert reg.get("openai") is p

    def test_duplicate_registration_raises(self) -> None:
        from core.ai_provider_registry import AIProviderAlreadyRegisteredError

        reg = AIProviderRegistry()
        reg.register(OpenAIProvider(client=_FakeOpenAIClient()))
        with pytest.raises(AIProviderAlreadyRegisteredError):
            reg.register(OpenAIProvider(client=_FakeOpenAIClient()))


class TestRouterCompatibility:
    def test_router_selects_openai(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeOpenAIClient()
        p = OpenAIProvider(client=fake)
        reg.register(p)
        selected = AIProviderRouter(reg).select("openai")
        assert selected is p
        out = selected.complete(AIRequest(prompt="hi"))
        assert out.text == "openai-mock-reply"

    def test_router_unknown_raises(self) -> None:
        from core.ai_provider_router import AIProviderUnavailableError

        with pytest.raises(AIProviderUnavailableError):
            AIProviderRouter(AIProviderRegistry()).select("openai")


class TestConversationEngineCompatibility:
    def test_engine_uses_openai_end_to_end(self) -> None:
        reg = AIProviderRegistry()
        fake = _FakeOpenAIClient()
        reg.register(OpenAIProvider(client=fake))
        out = AIConversationEngine(AIProviderRouter(reg)).complete(
            "openai", AIRequest(prompt="hi")
        )
        assert isinstance(out, AIResponse)
        assert out.text == "openai-mock-reply"
        assert out.provider_name == "openai"
        assert len(fake.chat.completions.calls) == 1