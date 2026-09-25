"""Tests for v7.4 Agent -> AIService integration."""

from __future__ import annotations

from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.conversation_history import ConversationHistory


class _RecordingAIService:
    """Test double for ``AIService`` that records every call."""

    def __init__(self, response: AIResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, AIRequest, ConversationHistory | None]] = []

    def complete(
        self,
        provider_name: str,
        request: AIRequest,
        history: ConversationHistory | None = None,
    ) -> AIResponse:
        self.calls.append((provider_name, request, history))
        return self._response


class TestAgentOwnsAIService:
    def test_default_constructor_owns_one_aiservice(self) -> None:
        a = Agent()
        assert isinstance(a.ai_service, AIService)

    def test_injected_aiservice_is_used(self) -> None:
        svc = _RecordingAIService(
            AIResponse(text="ok", provider_name="openai")
        )
        a = Agent(ai_service=svc)
        assert a.ai_service is svc

    def test_default_aiservice_is_a_fresh_instance(self) -> None:
        a1 = Agent()
        a2 = Agent()
        assert a1.ai_service is not a2.ai_service


class TestReasonDelegatesToAIService:
    def test_reason_calls_aiservice_once(self) -> None:
        svc = _RecordingAIService(
            AIResponse(text="hello", provider_name="openai")
        )
        a = Agent(ai_service=svc)
        out = a.reason("openai", "hi")
        assert len(svc.calls) == 1
        name, req, hist = svc.calls[0]
        assert name == "openai"
        assert req.prompt == "hi"
        assert hist is None
        assert out.text == "hello"
        assert out.provider_name == "openai"

    def test_reason_returns_ai_response_unchanged(self) -> None:
        target = AIResponse(text="payload", provider_name="claude")
        svc = _RecordingAIService(target)
        a = Agent(ai_service=svc)
        out = a.reason("claude", "anything")
        assert out is target

    def test_reason_propagates_unknown_provider(self) -> None:
        from core.ai_provider_router import AIProviderUnavailableError

        a = Agent()  # default AIService has no provider named "missing"
        try:
            a.reason("missing", "x")
        except AIProviderUnavailableError:
            return
        raise AssertionError("expected AIProviderUnavailableError")


class TestAgentNoProviderLogic:
    def test_agent_does_not_register_or_route_providers(self) -> None:
        """The Agent must not know provider internals — AIService is
        the single integration point."""
        a = Agent(ai_service=_RecordingAIService(
            AIResponse(text="x", provider_name="openai")
        ))
        # No provider-routing / registry attributes on Agent itself.
        for attr in ("providers", "router", "registry", "_router", "_registry"):
            assert not hasattr(a, attr), f"Agent leaked {attr}"
        # AIService still has its own state, untouched.
        assert isinstance(a.ai_service, _RecordingAIService)