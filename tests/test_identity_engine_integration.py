"""Verification tests for Step 6 (IdentityEngine integration).

No new adapter module was written for this step (see the integration
notes in the accompanying response) — IdentitySession's public
surface (``mode: str``, ``confidence: float``, ``pin_unlocked: bool``,
``status() -> str``) is made entirely of plain, primitive types that
map directly onto ContextManager, LearningManager, and
KnowledgeManager's existing public methods with no shape mismatch to
translate. These tests confirm that direct usage — the real
``core.identity_engine`` module feeding unmodified Foundation modules
through their existing public APIs, with no adapter in between —
actually works end to end.
"""

from __future__ import annotations

from core.agent.context_manager import ContextManager
from core.agent.knowledge_manager import KnowledgeManager
from core.agent.learning_manager import LearningCategory, LearningManager
from core.identity_engine import IdentitySession


class TestIdentityEngineUnchanged:
    def test_session_starts_unknown_with_zero_confidence(self) -> None:
        session = IdentitySession()
        assert session.mode == "unknown"
        assert session.confidence == 0.0
        assert session.pin_unlocked is False

    def test_update_from_voice_with_no_profile_falls_back_to_owner(self) -> None:
        # No voice_profile.json present in this sandbox — exercises
        # IdentitySession's own existing "no_profile -> owner" fallback,
        # confirming that behavior is untouched by this integration step.
        session = IdentitySession()
        session.update_from_voice(b"\x00" * 32000)
        assert session.mode == "owner"

    def test_is_authorized_low_risk_unchanged(self) -> None:
        session = IdentitySession()
        session.mode = "owner"
        assert session.is_authorized("low") is True

    def test_is_authorized_high_risk_requires_pin_unchanged(self) -> None:
        session = IdentitySession()
        session.mode = "owner"
        assert session.is_authorized("high") is False
        session.pin_unlocked = True
        assert session.is_authorized("high") is True

    def test_status_string_format_unchanged(self) -> None:
        session = IdentitySession()
        session.mode = "guest"
        session.confidence = 0.42
        text = session.status()
        assert "mode=guest" in text
        assert "confidence=0.42" in text
        assert "pin_unlocked=False" in text


class TestDirectIntegrationWithContextManager:
    def test_session_state_recorded_via_existing_set_api(self) -> None:
        session = IdentitySession()
        session.mode = "owner"
        session.confidence = 0.91
        context = ContextManager()

        # Direct calls to ContextManager's existing public API — no adapter.
        context.set("identity_mode", session.mode)
        context.set("identity_confidence", session.confidence)
        context.set("identity_pin_unlocked", session.pin_unlocked)

        assert context.get("identity_mode") == "owner"
        assert context.get("identity_confidence") == 0.91
        assert context.get("identity_pin_unlocked") is False


class TestDirectIntegrationWithLearningManager:
    def test_repeated_guest_detection_recorded_via_existing_api(self) -> None:
        session = IdentitySession()
        session.mode = "guest"
        session.confidence = 0.3
        learning = LearningManager()

        # The caller — not any adapter — decides this is worth recording,
        # via LearningManager's existing public API directly.
        record = learning.record_observation(
            "speaker_identity",
            detail=f"detected mode={session.mode} confidence={session.confidence}",
        )

        assert record.category == LearningCategory.OBSERVATION
        assert record.subject == "speaker_identity"


class TestDirectIntegrationWithKnowledgeManager:
    def test_identity_status_recorded_via_existing_add_api(self) -> None:
        session = IdentitySession()
        session.mode = "owner"
        knowledge = KnowledgeManager()

        # Direct call to KnowledgeManager's existing public API — no adapter.
        reference = knowledge.add(
            topic="identity",
            content=session.status(),
            source="identity_engine",
            tags={"speaker_session"},
        )

        assert reference.topic == "identity"
        assert "mode=owner" in reference.content
        assert reference.source == "identity_engine"
