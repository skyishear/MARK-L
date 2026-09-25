"""Tests for v7.6 Context Manager (provider-agnostic context layer)."""

from __future__ import annotations

from core.agent import Agent
from core.ai_provider import AIRequest, AIResponse
from core.ai_service import AIService
from core.context_manager import ContextManager
from core.conversation_history import ConversationHistory, Message


class _CapturingProvider:
    name = "capture"

    def __init__(self) -> None:
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


class TestContextManagerBasics:
    def test_empty_history_returns_empty(self) -> None:
        cm = ContextManager()
        assert cm.prepare(ConversationHistory()) == ()

    def test_none_history_returns_empty(self) -> None:
        cm = ContextManager()
        assert cm.prepare(None) == ()

    def test_populated_history_returned_unchanged(self) -> None:
        h = ConversationHistory()
        h.append_user("u1")
        h.append_assistant("a1")
        h.append_user("u2")
        cm = ContextManager()
        out = cm.prepare(h)
        assert out == (
            Message(role="user", content="u1"),
            Message(role="assistant", content="a1"),
            Message(role="user", content="u2"),
        )

    def test_order_preserved(self) -> None:
        h = ConversationHistory()
        for i in range(5):
            role = "user" if i % 2 == 0 else "assistant"
            if role == "user":
                h.append_user(f"u{i}")
            else:
                h.append_assistant(f"a{i}")
        out = ContextManager().prepare(h)
        assert [m.content for m in out] == ["u0", "a1", "u2", "a3", "u4"]

    def test_returns_tuple_not_list(self) -> None:
        h = ConversationHistory()
        h.append_user("x")
        out = ContextManager().prepare(h)
        assert isinstance(out, tuple)


class TestAIServiceUsesContextManager:
    def test_aiservice_owns_context_manager(self) -> None:
        s = AIService()
        assert isinstance(s.context_manager, ContextManager)

    def test_injected_context_manager_is_used(self) -> None:
        cm = ContextManager()
        s = AIService(context_manager=cm)
        assert s.context_manager is cm

    def test_context_manager_runs_history_before_provider(self) -> None:
        cap = _CapturingProvider()
        svc = _RecordingAIService(cap)
        a = Agent(ai_service=svc)
        a.ask("capture", "u1")
        a.ask("capture", "u2")
        assert cap.calls[0]["messages"] == [{"role": "user", "content": "u1"}]
        assert cap.calls[1]["messages"] == [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "reply-1"},
            {"role": "user", "content": "u2"},
        ]

    def test_custom_context_manager_filters_history(self) -> None:
        """A custom ContextManager returning a subset must be respected."""

        class _FilteringCM(ContextManager):
            def prepare(self, history):  # type: ignore[override]
                return tuple(m for m in history.messages() if m.role == "user")

        from core.ai_conversation_engine import AIConversationEngine
        from core.ai_provider_registry import AIProviderRegistry
        from core.ai_provider_router import AIProviderRouter

        cap = _CapturingProvider()
        reg = AIProviderRegistry()
        reg.register(cap)
        engine = AIConversationEngine(AIProviderRouter(reg))

        h = ConversationHistory()
        h.append_user("u1")
        h.append_assistant("a1")
        h.append_user("u2")
        s = AIService(context_manager=_FilteringCM())

        prepared = s.context_manager.prepare(h)
        eff = ConversationHistory()
        eff.extend(prepared)
        engine.complete("capture", AIRequest(prompt="X", history=eff))
        assert cap.calls[0]["messages"] == [
            {"role": "user", "content": "u1"},
            {"role": "user", "content": "u2"},
            {"role": "user", "content": "X"},
        ]


class TestProvidersUnawareOfContextManager:
    def test_providers_do_not_import_context_manager(self) -> None:
        import ast
        import importlib

        for mod_name in (
            "core.openai_provider",
            "core.claude_provider",
            "core.gemini_provider",
            "core.ollama_provider",
        ):
            mod = importlib.import_module(mod_name)
            assert mod.__file__ is not None
            with open(mod.__file__, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("core.context_manager"), (
                        f"{mod_name} must not import ContextManager"
                    )
                if isinstance(node, ast.Import):
                    for n in node.names:
                        assert not n.name.startswith("core.context_manager"), (
                            f"{mod_name} must not import ContextManager"
                        )