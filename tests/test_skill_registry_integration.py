"""Verification tests for Step 5 (SkillRegistry integration).

No new adapter module was written for this step (see the integration
notes in the accompanying response) — SkillRegistry's existing public
API (``dispatch(tool_name, args, ctx)``) already accepts/returns plain
``str``/``dict`` values that map directly onto HistoryManager,
ContextManager, LearningManager, and ReflectionManager's existing
public methods with no shape mismatch to translate. These tests
confirm that direct usage — the real ``core.skill_registry`` module
calling into unmodified Foundation modules through their existing
public APIs, with no adapter in between — actually works end to end.
"""

from __future__ import annotations

from typing import Any

from core.agent.context_manager import ContextManager
from core.agent.history_manager import HistoryManager
from core.agent.learning_manager import LearningCategory, LearningManager
from core.agent.reflection_manager import ReflectionManager
from core.skill_registry import SkillManifest, dispatch, is_registered, register_skill


def _weather_handler(tool_name: str, args: dict[str, Any], ctx: dict[str, Any]) -> str:
    return f"weather in {args.get('city', 'unknown')}: sunny"


def _register_weather_skill() -> None:
    # SkillRegistry's real _tool_index/_skills dicts are module-level global
    # state that persists for the whole test session — guard against
    # re-registering the same tool name across multiple tests, which would
    # otherwise correctly trigger SkillRegistry's own conflict detection.
    if is_registered("weather_report_test"):
        return
    manifest = SkillManifest(
        name="weather_test_skill",
        description="Test weather skill",
        tools=[
            {
                "name": "weather_report_test",
                "description": "test tool",
                "parameters": {"type": "OBJECT", "properties": {}},
            }
        ],
        handler=_weather_handler,
    )
    register_skill(manifest)


class TestSkillRegistryUnchanged:
    def test_dispatch_return_value_is_untouched_by_integration(self) -> None:
        _register_weather_skill()
        result = dispatch("weather_report_test", {"city": "Lucknow"}, {})
        assert result == "weather in Lucknow: sunny"

    def test_unregistered_tool_still_returns_none(self) -> None:
        assert dispatch("nonexistent_tool_xyz", {}, {}) is None

    def test_is_registered_still_works_normally(self) -> None:
        _register_weather_skill()
        assert is_registered("weather_report_test") is True
        assert is_registered("nonexistent_tool_xyz") is False


class TestDirectIntegrationWithHistoryManager:
    def test_dispatch_result_logged_via_existing_record_api(self) -> None:
        _register_weather_skill()
        history = HistoryManager()

        tool_name, args = "weather_report_test", {"city": "Lucknow"}
        result = dispatch(tool_name, args, {})
        # Direct call to HistoryManager's existing public API — no adapter.
        entry = history.record(
            "action",
            f"{tool_name}({args})",
            metadata={"args": args, "result": result},
        )

        assert entry.description == f"{tool_name}({args})"
        assert entry.metadata["result"] == "weather in Lucknow: sunny"
        assert len(history.get_history()) == 1


class TestDirectIntegrationWithContextManager:
    def test_dispatch_result_recorded_via_existing_set_api(self) -> None:
        _register_weather_skill()
        context = ContextManager()

        tool_name, args = "weather_report_test", {"city": "Lucknow"}
        result = dispatch(tool_name, args, {})
        # Direct calls to ContextManager's existing public API — no adapter.
        context.set("last_tool", tool_name)
        context.set("last_tool_result", result)

        assert context.get("last_tool") == "weather_report_test"
        assert context.get("last_tool_result") == "weather in Lucknow: sunny"


class TestDirectIntegrationWithLearningManager:
    def test_caller_classified_outcome_recorded_via_existing_api(self) -> None:
        _register_weather_skill()
        learning = LearningManager()

        result = dispatch("weather_report_test", {"city": "Lucknow"}, {})
        # The caller — not any adapter — decides this call succeeded, and
        # records it via LearningManager's existing public API directly.
        record = learning.record_successful_pattern(
            "weather_report_test", detail=str(result)
        )

        assert record.category == LearningCategory.SUCCESSFUL_PATTERN
        assert record.subject == "weather_report_test"


class TestDirectIntegrationWithReflectionManager:
    def test_caller_authored_reflection_recorded_via_existing_api(self) -> None:
        _register_weather_skill()
        reflection = ReflectionManager()

        dispatch("weather_report_test", {"city": "Lucknow"}, {})
        # Reflection is a deliberate review the caller chooses to make,
        # not something inferred automatically from the dispatch result.
        record = reflection.add_reflection(
            subject="weather_report_test",
            what_worked="returned a result on first call",
            confidence_level=1.0,
            completion_summary="tool call succeeded",
        )

        assert record.subject == "weather_report_test"
        assert record.confidence_level == 1.0


class TestNoDuplicationOfDispatchLogic:
    def test_conflicting_tool_registration_still_raises_from_real_module(self) -> None:
        first = SkillManifest(
            name="conflict_test_skill_a",
            description="first owner",
            tools=[
                {"name": "conflict_test_tool", "description": "x", "parameters": {}}
            ],
            handler=_weather_handler,
        )
        register_skill(first)

        second = SkillManifest(
            name="conflict_test_skill_b",
            description="conflicts on tool name",
            tools=[
                {"name": "conflict_test_tool", "description": "x", "parameters": {}}
            ],
            handler=_weather_handler,
        )
        try:
            register_skill(second)
            raised = False
        except ValueError:
            raised = True
        assert (
            raised
        ), "SkillRegistry's own conflict-detection must still fire unmodified"
