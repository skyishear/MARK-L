"""Tests for v6.8 Default AI Provider Bootstrap."""

from __future__ import annotations

from core.ai_conversation_engine import AIConversationEngine
from core.ai_provider import AIRequest
from core.ai_provider_registry import AIProviderRegistry
from core.ai_provider_router import AIProviderRouter
from core.claude_provider import ClaudeProvider
from core.default_ai_provider_registry import build_default_registry
from core.gemini_provider import GeminiProvider
from core.ollama_provider import OllamaProvider
from core.openai_provider import OpenAIProvider


class TestRegistryContents:
    def test_registry_contains_exactly_four_providers(self) -> None:
        registry = build_default_registry()
        assert registry.names() == ("openai", "claude", "gemini", "ollama")

    def test_registration_order_preserved(self) -> None:
        registry = build_default_registry()
        assert registry.names() == ("openai", "claude", "gemini", "ollama")

    def test_openai_registered_first(self) -> None:
        registry = build_default_registry()
        assert registry.names()[0] == "openai"
        assert isinstance(registry.get("openai"), OpenAIProvider)

    def test_claude_registered_second(self) -> None:
        registry = build_default_registry()
        assert registry.names()[1] == "claude"
        assert isinstance(registry.get("claude"), ClaudeProvider)

    def test_gemini_registered_third(self) -> None:
        registry = build_default_registry()
        assert registry.names()[2] == "gemini"
        assert isinstance(registry.get("gemini"), GeminiProvider)

    def test_ollama_registered_fourth(self) -> None:
        registry = build_default_registry()
        assert registry.names()[3] == "ollama"
        assert isinstance(registry.get("ollama"), OllamaProvider)

    def test_each_provider_retrievable(self) -> None:
        registry = build_default_registry()
        for name in ("openai", "claude", "gemini", "ollama"):
            assert registry.has(name)
            assert registry.get(name) is not None


class TestDeterministicBootstrap:
    def test_two_calls_produce_equivalent_state(self) -> None:
        a = build_default_registry()
        b = build_default_registry()
        assert a.names() == b.names()
        # Each call returns a fresh, independent registry.
        assert a is not b

    def test_each_call_returns_fresh_registry(self) -> None:
        a = build_default_registry()
        b = build_default_registry()
        a.clear()
        # Clearing one must not affect the other.
        assert b.names() == ("openai", "claude", "gemini", "ollama")


class TestNoDuplicateRegistration:
    def test_registering_default_providers_again_raises(self) -> None:
        """The default registry must not pre-register a provider under
        a name that the caller will also register."""
        from core.ai_provider_registry import AIProviderAlreadyRegisteredError

        registry = build_default_registry()
        with_error = None
        try:
            registry.register(OpenAIProvider())
        except AIProviderAlreadyRegisteredError as exc:
            with_error = exc
        assert with_error is not None


class TestRouterIntegration:
    def test_router_can_select_each_provider(self) -> None:
        registry = build_default_registry()
        router = AIProviderRouter(registry)
        for name in ("openai", "claude", "gemini", "ollama"):
            provider = router.select(name)
            assert provider.name == name


class TestConversationEngineIntegration:
    def test_engine_uses_each_default_provider(self) -> None:
        registry = build_default_registry()
        engine = AIConversationEngine(AIProviderRouter(registry))
        for name, expected_provider in (
            ("openai", OpenAIProvider),
            ("claude", ClaudeProvider),
            ("gemini", GeminiProvider),
            ("ollama", OllamaProvider),
        ):
            out = engine.complete(name, AIRequest(prompt="hi"))
            assert out.provider_name == name
            assert isinstance(registry.get(name), expected_provider)


class TestArchitecturalIsolation:
    def test_depends_only_on_registry_and_providers(self) -> None:
        import ast

        from core import default_ai_provider_registry as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {
            "core.ai_provider_registry",
            "core.openai_provider",
            "core.claude_provider",
            "core.gemini_provider",
            "core.ollama_provider",
            "__future__",
        }
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_router", "core.ai_conversation_engine",
            "core.ai_provider.",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module in allowed, f"Forbidden import: {node.module}"
                assert not any(
                    node.module.startswith(s) for s in forbidden_substrings
                )
            if isinstance(node, ast.Import):
                for n in node.names:
                    assert not any(
                        n.name.startswith(s) for s in forbidden_substrings
                    ), f"Forbidden import: {n.name}"