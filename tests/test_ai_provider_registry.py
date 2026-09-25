"""Tests for v6.1 AI Provider Registry."""

from __future__ import annotations

import pytest

from core.ai_provider import StaticMockProvider
from core.ai_provider_registry import (
    AIProviderAlreadyRegisteredError,
    AIProviderNotFoundError,
    AIProviderRegistry,
)


class TestRegisterAndLookup:
    def test_register_and_get(self) -> None:
        reg = AIProviderRegistry()
        p = StaticMockProvider(name="alpha", response="a-reply")
        reg.register(p)
        assert reg.get("alpha") is p

    def test_register_returns_provider(self) -> None:
        reg = AIProviderRegistry()
        p = StaticMockProvider(name="x")
        assert reg.register(p) is p

    def test_names_returns_insertion_order(self) -> None:
        reg = AIProviderRegistry()
        reg.register(StaticMockProvider(name="b"))
        reg.register(StaticMockProvider(name="a"))
        reg.register(StaticMockProvider(name="c"))
        assert reg.names() == ("b", "a", "c")

    def test_list_providers_in_insertion_order(self) -> None:
        reg = AIProviderRegistry()
        p1 = StaticMockProvider(name="p1")
        p2 = StaticMockProvider(name="p2")
        reg.register(p1)
        reg.register(p2)
        providers = reg.list_providers()
        assert providers == (p1, p2)

    def test_has(self) -> None:
        reg = AIProviderRegistry()
        reg.register(StaticMockProvider(name="x"))
        assert reg.has("x") is True
        assert reg.has("nope") is False


class TestDuplicateRegistrationFails:
    def test_duplicate_name_raises(self) -> None:
        reg = AIProviderRegistry()
        reg.register(StaticMockProvider(name="dup", response="first"))
        with pytest.raises(AIProviderAlreadyRegisteredError):
            reg.register(StaticMockProvider(name="dup", response="second"))

    def test_re_registration_with_same_instance_is_idempotent(self) -> None:
        reg = AIProviderRegistry()
        p = StaticMockProvider(name="x")
        reg.register(p)
        reg.register(p)  # same instance — no error
        assert reg.get("x") is p


class TestUnknownProviderRaises:
    def test_get_unknown_raises(self) -> None:
        reg = AIProviderRegistry()
        with pytest.raises(AIProviderNotFoundError):
            reg.get("missing")

    def test_unregister_unknown_is_silent(self) -> None:
        reg = AIProviderRegistry()
        reg.unregister("missing")  # no-op, no raise


class TestDeterminism:
    def test_two_registries_with_same_input_same_state(self) -> None:
        a, b = AIProviderRegistry(), AIProviderRegistry()
        for name in ("z", "y", "x"):
            a.register(StaticMockProvider(name=name, response=name))
            b.register(StaticMockProvider(name=name, response=name))
        assert a.names() == b.names()
        assert [p.name for p in a.list_providers()] == [
            p.name for p in b.list_providers()
        ]


class TestArchitecturalIsolation:
    """The registry must depend only on ``core.ai_provider``."""

    def test_only_ai_provider_dependency(self) -> None:
        import ast

        from core import ai_provider_registry as mod

        with open(mod.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {"core.ai_provider", "__future__", "typing"}
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


class TestClear:
    def test_clear_removes_all(self) -> None:
        reg = AIProviderRegistry()
        reg.register(StaticMockProvider(name="a"))
        reg.register(StaticMockProvider(name="b"))
        reg.clear()
        assert reg.names() == ()
        assert reg.list_providers() == ()