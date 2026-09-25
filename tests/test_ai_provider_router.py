"""Tests for v6.2 AI Provider Routing."""

from __future__ import annotations

import pytest

from core.ai_provider import AIRequest, StaticMockProvider
from core.ai_provider_registry import AIProviderRegistry
from core.ai_provider_router import AIProviderRouter, AIProviderUnavailableError


@pytest.fixture
def registry() -> AIProviderRegistry:
    reg = AIProviderRegistry()
    reg.register(StaticMockProvider(name="alpha", response="a-reply"))
    reg.register(StaticMockProvider(name="beta", response="b-reply"))
    return reg


class TestSelection:
    def test_select_existing_provider(self, registry: AIProviderRegistry) -> None:
        router = AIProviderRouter(registry)
        p = router.select("alpha")
        assert isinstance(p, StaticMockProvider)
        assert p.name == "alpha"

    def test_select_returns_provider_that_can_complete(
        self, registry: AIProviderRegistry
    ) -> None:
        router = AIProviderRouter(registry)
        provider = router.select("beta")
        out = provider.complete(AIRequest(prompt="hi"))
        assert out.text == "b-reply"
        assert out.provider_name == "beta"

    def test_select_is_deterministic(self, registry: AIProviderRegistry) -> None:
        router = AIProviderRouter(registry)
        a = router.select("alpha")
        b = router.select("alpha")
        assert a is b


class TestUnknownProviderRaises:
    def test_unknown_raises(self, registry: AIProviderRegistry) -> None:
        router = AIProviderRouter(registry)
        with pytest.raises(AIProviderUnavailableError):
            router.select("nope")


class TestAvailabilityAndListing:
    def test_is_available(self, registry: AIProviderRegistry) -> None:
        router = AIProviderRouter(registry)
        assert router.is_available("alpha") is True
        assert router.is_available("nope") is False

    def test_available_names(self, registry: AIProviderRegistry) -> None:
        router = AIProviderRouter(registry)
        assert router.available_names() == ("alpha", "beta")


class TestRegistryUnchanged:
    def test_router_does_not_mutate_registry(
        self, registry: AIProviderRegistry
    ) -> None:
        before = registry.names()
        router = AIProviderRouter(registry)
        for _ in range(3):
            router.select("alpha")
        assert registry.names() == before


class TestNoProviderExecution:
    def test_router_does_not_execute_provider(
        self, registry: AIProviderRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Select must never call ``complete`` on the chosen provider."""

        def fail(*a, **kw):
            raise AssertionError("router must not execute providers")

        monkeypatch.setattr(StaticMockProvider, "complete", fail)
        router = AIProviderRouter(registry)
        router.select("alpha")  # must not raise
        router.select("beta")  # must not raise


class TestArchitecturalIsolation:
    def test_depends_only_on_ai_provider_modules(self) -> None:
        import ast

        from core import ai_provider_router as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {"core.ai_provider", "core.ai_provider_registry", "__future__"}
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