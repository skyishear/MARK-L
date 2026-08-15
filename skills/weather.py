"""
skills/weather.py — Weather report skill.

Migrated from the old hardcoded main.py entry into the skill registry,
as the first worked example of the new plugin pattern. The underlying
logic (actions/weather_report.py) is untouched — this file is just the
manifest + a thin handler that plugs it into the registry.
"""
from core.skill_registry import SkillManifest, register_skill
from actions.weather_report import weather_action


def _handle(tool_name: str, args: dict, ctx: dict) -> str:
    ui = ctx.get("ui")
    return weather_action(parameters=args, player=ui) or "Weather delivered."


SKILL = SkillManifest(
    name="weather",
    description="Shows live weather for a city by opening a search in the browser.",
    version="1.0",
    risk_level="low",
    permissions=["open_browser"],
    dependencies=[],
    tools=[
        {
            "name": "weather_report",
            "description": "Gives the weather report to user",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "city": {"type": "STRING", "description": "City name"},
                    "time": {"type": "STRING", "description": "e.g. 'today', 'tomorrow', 'this weekend' (optional)"},
                },
                "required": ["city"],
            },
        }
    ],
    handler=_handle,
    examples=["What's the weather in Mumbai?", "Weather in Delhi tomorrow"],
)

register_skill(SKILL)
