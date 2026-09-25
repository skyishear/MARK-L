"""Tests for v7.5 Conversation History."""

from __future__ import annotations

from types import SimpleNamespace

from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.conversation_history import ConversationHistory, Message


class _CapturingProvider:
    """Minimal AIProvider that records every call's messages payload."""

    def __init__(self) -> None:
        self.name = "capture"
        self.calls: list[dict] = []

    def complete(self, request: AIRequest) -> AIResponse:
        msgs: list = []
        if request.history is not None:
            for m in request.history.messages():
                msgs.append({"role": m.role, "content": m.content})
        msgs.append({"role": "user", "content": request.prompt})
        self.calls.append({"messages": msgs})
        return AIResponse(text=f"reply-{len(self.calls)}", provider_name=self.name)


class _RecordingAIService:
    def __init__(self, provider) -> None:
        self._provider = provider
        self.calls: list[tuple[str, AIRequest, ConversationHistory | None]] = []

    def complete(
        self,
        provider_name: str,
        request: AIRequest,
        history: ConversationHistory | None = None,
    ) -> AIResponse:
        self.calls.append((provider_name, request, history))
        return self._provider.complete(
            AIRequest(prompt=request.prompt, history=history)
        )


class TestConversationHistoryBasic:
    def test_starts_empty(self) -> None:
        h = ConversationHistory()
        assert h.messages() == ()
        assert len(h) == 0

    def test_append_user(self) -> None:
        h = ConversationHistory()
        m = h.append_user("hi")
        assert m.role == "user"
        assert m.content == "hi"
        assert len(h) == 1
        assert h.messages() == (Message(role="user", content="hi"),)

    def test_append_assistant(self) -> None:
        h = ConversationHistory()
        h.append_assistant("hello")
        assert h.messages() == (Message(role="assistant", content="hello"),)

    def test_ordering_preserved(self) -> None:
        h = ConversationHistory()
        h.append_user("u1")
        h.append_assistant("a1")
        h.append_user("u2")
        h.append_assistant("a2")
        msgs = h.messages()
        assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert [m.content for m in msgs] == ["u1", "a1", "u2", "a2"]

    def test_clear(self) -> None:
        h = ConversationHistory()
        h.append_user("x")
        h.clear()
        assert h.messages() == ()

    def test_messages_is_immutable_snapshot(self) -> None:
        h = ConversationHistory()
        h.append_user("x")
        snap = h.messages()
        h.append_user("y")
        assert snap == (Message(role="user", content="x"),)


class TestConversationHistoryMessagePayloads:
    def test_to_openai_payload(self) -> None:
        m = Message(role="user", content="hi")
        assert m.to_openai_payload() == {"role": "user", "content": "hi"}

    def test_to_anthropic_payload(self) -> None:
        m = Message(role="assistant", content="hello")
        assert m.to_anthropic_payload() == {"role": "assistant", "content": "hello"}


class TestAIServiceForwardsHistory:
    def test_complete_without_history_passes_none(self) -> None:
        cap = _CapturingProvider()
        svc = _RecordingAIService(cap)
        out = svc.complete("capture", AIRequest(prompt="x"), None)
        assert out.text == "reply-1"
        assert svc.calls[0][2] is None

    def test_complete_with_history_attaches_to_request(self) -> None:
        cap = _CapturingProvider()
        svc = _RecordingAIService(cap)
        h = ConversationHistory()
        h.append_user("u1")
        h.append_assistant("a1")
        svc.complete("capture", AIRequest(prompt="u2"), h)
        assert cap.calls[0]["messages"] == [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]


class TestAgentConversationHistory:
    def test_agent_owns_one_conversation_history(self) -> None:
        a = Agent()
        assert isinstance(a.conversation_history, ConversationHistory)
        assert len(a.conversation_history) == 0

    def test_injected_history_is_used(self) -> None:
        h = ConversationHistory()
        h.append_user("preset")
        a = Agent(conversation_history=h)
        assert a.conversation_history is h

    def test_ask_appends_user_and_assistant(self) -> None:
        cap = _CapturingProvider()
        svc = _RecordingAIService(cap)
        a = Agent(ai_service=svc)
        out = a.ask("capture", "hello")
        msgs = a.conversation_history.messages()
        assert len(msgs) == 2
        assert msgs[0].role == "user" and msgs[0].content == "hello"
        assert msgs[1].role == "assistant" and msgs[1].content == "reply-1"
        assert out.text == "reply-1"

    def test_ask_preserves_multi_turn_order(self) -> None:
        cap = _CapturingProvider()
        svc = _RecordingAIService(cap)
        a = Agent(ai_service=svc)
        a.ask("capture", "u1")
        a.ask("capture", "u2")
        # First call: prior history is empty; provider sees [u1].
        # Second call: prior history is [u1, a1]; provider sees [u1, a1, u2].
        assert cap.calls[0]["messages"] == [{"role": "user", "content": "u1"}]
        assert cap.calls[1]["messages"] == [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "reply-1"},
            {"role": "user", "content": "u2"},
        ]
        msgs = a.conversation_history.messages()
        assert [m.content for m in msgs] == ["u1", "reply-1", "u2", "reply-2"]