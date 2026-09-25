"""Tests for v6.9 AI Service."""

from __future__ import annotations

import pytest

from core.ai_provider import AIRequest, AIResponse
from core.ai_provider_registry import AIProviderRegistry
from core.ai_provider_router import AIProviderRouter
from core.ai_service import AIService, AIProviderUnavailableError


class TestServiceConstruction:
    def test_creates_default_registry(self) -> None:
        service = AIService()
        assert isinstance(service.registry, AIProviderRegistry)
        assert service.registry.names() == (
            "openai", "claude", "gemini", "ollama",
        )

    def test_creates_router_over_registry(self) -> None:
        service = AIService()
        assert isinstance(service.router, AIProviderRouter)

    def test_engine_is_wired_through_router(self) -> None:
        service = AIService()
        # The service's router is the engine's router — single source of truth.
        assert service.router.registry is service.registry


class TestAllFourProvidersAvailable:
    def test_all_four_providers_available(self) -> None:
        service = AIService()
        for name in ("openai", "claude", "gemini", "ollama"):
            assert service.router.is_available(name)
            assert service.registry.has(name)


class TestCompleteDelegation:
    def test_complete_using_openai(self) -> None:
        out = AIService().complete("openai", AIRequest(prompt="hi"))
        assert isinstance(out, AIResponse)
        assert out.provider_name == "openai"

    def test_complete_using_claude(self) -> None:
        out = AIService().complete("claude", AIRequest(prompt="hi"))
        assert isinstance(out, AIResponse)
        assert out.provider_name == "claude"

    def test_complete_using_gemini(self) -> None:
        out = AIService().complete("gemini", AIRequest(prompt="hi"))
        assert isinstance(out, AIResponse)
        assert out.provider_name == "gemini"

    def test_complete_using_ollama(self) -> None:
        out = AIService().complete("ollama", AIRequest(prompt="hi"))
        assert isinstance(out, AIResponse)
        assert out.provider_name == "ollama"


class TestUnknownProviderRaises:
    def test_unknown_raises(self) -> None:
        service = AIService()
        with pytest.raises(AIProviderUnavailableError):
            service.complete("nope", AIRequest(prompt="x"))


class TestDeterminism:
    def test_same_provider_same_response(self) -> None:
        service = AIService()
        a = service.complete("openai", AIRequest(prompt="x"))
        b = service.complete("openai", AIRequest(prompt="x"))
        assert a.text == b.text
        assert a.provider_name == b.provider_name

    def test_two_services_produce_same_default_state(self) -> None:
        a, b = AIService(), AIService()
        assert a.registry.names() == b.registry.names()


class TestArchitecturalIsolation:
    def test_depends_only_on_allowed_modules(self) -> None:
        import ast

        from core import ai_service as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {
            "core.default_ai_provider_registry",
            "core.ai_provider",
            "core.ai_provider_router",
            "core.ai_conversation_engine",
            "core.conversation_history",
            "core.context_manager",
            "__future__",
        }
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "core.ai_provider_registry", "core.openai_provider",
            "core.claude_provider", "core.gemini_provider",
            "core.ollama_provider",
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