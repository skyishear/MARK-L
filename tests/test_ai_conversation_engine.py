"""Tests for v6.3 AI Conversation Engine."""

from __future__ import annotations

import pytest

from core.ai_conversation_engine import (
    AIConversationEngine,
    AIProviderUnavailableError,
)
from core.ai_provider import AIRequest, AIResponse, StaticMockProvider
from core.ai_provider_registry import AIProviderRegistry
from core.ai_provider_router import AIProviderRouter


@pytest.fixture
def engine() -> AIConversationEngine:
    registry = AIProviderRegistry()
    registry.register(StaticMockProvider(name="alpha", response="a-reply"))
    registry.register(StaticMockProvider(name="beta", response="b-reply"))
    return AIConversationEngine(AIProviderRouter(registry))


class TestSingleRequest:
    def test_existing_provider_receives_exactly_one_request(
        self, engine: AIConversationEngine
    ) -> None:
        provider = engine.router.select("alpha")
        before = provider.call_count
        engine.complete("alpha", AIRequest(prompt="hi"))
        assert provider.call_count - before == 1

    def test_returned_ai_response_is_unchanged(
        self, engine: AIConversationEngine
    ) -> None:
        out = engine.complete("beta", AIRequest(prompt="hello"))
        assert isinstance(out, AIResponse)
        assert out.text == "b-reply"
        assert out.provider_name == "beta"

    def test_request_prompt_is_forwarded(
        self, engine: AIConversationEngine
    ) -> None:
        # StaticMockProvider echoes prompt when echo=True — use a
        # custom mock to capture the exact request.
        seen: list[AIRequest] = []

        class CapturingProvider:
            name = "cap"
            def complete(self, request: AIRequest) -> AIResponse:
                seen.append(request)
                return AIResponse(text="ok", provider_name="cap")

        reg = AIProviderRegistry()
        reg.register(CapturingProvider())  # type: ignore[arg-type]
        eng = AIConversationEngine(AIProviderRouter(reg))
        eng.complete("cap", AIRequest(prompt="captured-prompt"))
        assert seen and seen[0].prompt == "captured-prompt"


class TestUnknownProviderRaises:
    def test_unknown_raises(self, engine: AIConversationEngine) -> None:
        with pytest.raises(AIProviderUnavailableError):
            engine.complete("nope", AIRequest(prompt="x"))


class TestRegistryAndRouterUnchanged:
    def test_engine_does_not_mutate_registry(
        self, engine: AIConversationEngine
    ) -> None:
        before = engine.router.registry.names()
        for _ in range(3):
            try:
                engine.complete("alpha", AIRequest(prompt="x"))
            except Exception:
                pass
        assert engine.router.registry.names() == before

    def test_engine_does_not_mutate_router(
        self, engine: AIConversationEngine
    ) -> None:
        before = engine.router.available_names()
        engine.complete("alpha", AIRequest(prompt="x"))
        assert engine.router.available_names() == before


class TestNoAdditionalProviderCalls:
    def test_only_the_selected_provider_is_called(
        self, engine: AIConversationEngine
    ) -> None:
        alpha = engine.router.select("alpha")
        beta = engine.router.select("beta")
        a_before, b_before = alpha.call_count, beta.call_count

        engine.complete("alpha", AIRequest(prompt="x"))

        assert alpha.call_count - a_before == 1
        assert beta.call_count - b_before == 0


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_modules(self) -> None:
        import ast

        from core import ai_conversation_engine as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {
            "core.ai_provider",
            "core.ai_provider_registry",
            "core.ai_provider_router",
            "__future__",
        }
        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
            "openai", "anthropic", "google", "ollama",
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