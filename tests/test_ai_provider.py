"""Tests for v6.0 AI Provider Abstraction."""

from __future__ import annotations

import pytest

from core.ai_provider import (
    AIProvider,
    AIRequest,
    AIResponse,
    StaticMockProvider,
    default_provider,
)


class TestProviderInterface:
    def test_mock_provider_satisfies_protocol(self) -> None:
        provider: AIProvider = StaticMockProvider()
        # Protocol satisfaction is structural; verify the required
        # attributes exist and are callable.
        assert hasattr(provider, "name")
        assert callable(getattr(provider, "complete", None))

    def test_request_is_immutable(self) -> None:
        req = AIRequest(prompt="hello")
        with pytest.raises(Exception):
            req.prompt = "changed"  # type: ignore[misc]

    def test_response_is_immutable(self) -> None:
        resp = AIResponse(text="x", provider_name="mock")
        with pytest.raises(Exception):
            resp.text = "changed"  # type: ignore[misc]

    def test_complete_returns_ai_response(self) -> None:
        provider = StaticMockProvider(response="fixed-text")
        out = provider.complete(AIRequest(prompt="ignored"))
        assert isinstance(out, AIResponse)
        assert out.text == "fixed-text"
        assert out.provider_name == "mock"


class TestDeterminism:
    def test_same_request_same_response(self) -> None:
        provider = StaticMockProvider(response="stable")
        a = provider.complete(AIRequest(prompt="x"))
        b = provider.complete(AIRequest(prompt="x"))
        assert a.text == b.text == "stable"

    def test_echo_mode_returns_prompt(self) -> None:
        provider = StaticMockProvider(echo=True)
        out = provider.complete(AIRequest(prompt="ping"))
        assert out.text == "ping"

    def test_call_count_increments(self) -> None:
        provider = StaticMockProvider()
        assert provider.call_count == 0
        provider.complete(AIRequest(prompt="a"))
        provider.complete(AIRequest(prompt="b"))
        assert provider.call_count == 2


class TestNoNetworkIO:
    def test_no_request_leaves_the_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A leaked network or AI SDK call would replace ``complete``.
        Patch it on the type itself — if any code path bypasses the
        provider abstraction, that patch would not catch the leak."""

        def fail(*a, **kw):
            raise AssertionError("AI request left the process")

        monkeypatch.setattr(StaticMockProvider, "complete", fail)
        provider = StaticMockProvider()
        with pytest.raises(AssertionError):
            provider.complete(AIRequest(prompt="x"))


class TestDefaultFactory:
    def test_default_provider_returns_mock(self) -> None:
        provider = default_provider()
        assert isinstance(provider, StaticMockProvider)
        out = provider.complete(AIRequest(prompt="hi"))
        assert out.text == "mock-response"

    def test_custom_response(self) -> None:
        provider = default_provider(response="custom")
        out = provider.complete(AIRequest(prompt="hi"))
        assert out.text == "custom"


class TestArchitecturalIsolation:
    """The provider module must stay isolated — no imports from the
    frozen execution / planning / memory / reflection / learning /
    skill modules."""

    def test_no_execution_pipeline_dependencies(self) -> None:
        import ast

        from core import ai_provider

        with open(ai_provider.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        forbidden_substrings = (
            "core.planner", "core.execution_", "core.problem_solver",
            "core.memory", "core.reflection", "core.learning",
            "core.skill", "core.agent", "core.identity",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(
                    node.module.startswith(s) for s in forbidden_substrings
                ), f"AI provider imports forbidden module: {node.module}"
            if isinstance(node, ast.Import):
                for n in node.names:
                    assert not any(
                        n.name.startswith(s) for s in forbidden_substrings
                    ), f"AI provider imports forbidden module: {n.name}"