"""
skills/spotify.py — Spotify control skill.

This is a BRAND NEW capability that did not exist in Mark L before —
added purely by dropping this file into skills/. No changes to
main.py, core/, or any other file were needed. This is the concrete
proof of architecture-spec section 10 ("Add Spotify support").

Uses the spotify: URI scheme to hand off directly to the Spotify
desktop app (search screen) — no API key or OAuth needed. Falls back
to the web player if the desktop app isn't installed/registered.
"""
import platform
import subprocess
import webbrowser
from urllib.parse import quote_plus

from core.skill_registry import SkillManifest, register_skill


def _open_spotify_search(query: str) -> bool:
    """Try to hand off to the Spotify desktop app via URI scheme.
    Returns True if the app-launch call itself succeeded (best-effort —
    OS URI dispatch doesn't reliably report whether Spotify was actually
    installed, hence the web-player fallback either way is safe)."""
    uri = f"spotify:search:{quote_plus(query)}"
    system = platform.system()
    try:
        if system == "Windows":
            import os
            os.startfile(uri)  # noqa: S606 — trusted, locally-built URI
        elif system == "Darwin":
            subprocess.run(["open", uri], check=True)
        else:
            subprocess.run(["xdg-open", uri], check=True)
        return True
    except Exception:
        return False


def _handle(tool_name: str, args: dict, ctx: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "Sir, I need a song, artist, or playlist name to search on Spotify."

    if _open_spotify_search(query):
        return f"Opening '{query}' on Spotify, sir."

    # Fallback: web player, always works with just a browser
    webbrowser.open(f"https://open.spotify.com/search/{quote_plus(query)}")
    return f"Couldn't reach the Spotify app, sir — opened '{query}' in the web player instead."


SKILL = SkillManifest(
    name="spotify",
    description="Search and open songs, artists, or playlists on Spotify.",
    version="1.0",
    risk_level="low",
    permissions=["open_app", "open_browser"],
    dependencies=[],   # uses only the stdlib + the OS's own URI handling
    tools=[
        {
            "name": "spotify_play",
            "description": (
                "Search for and open a song, artist, album, or playlist on Spotify. "
                "Call this when the user asks to play music, open a song, or search Spotify."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {
                        "type": "STRING",
                        "description": "What to search for, e.g. 'Blinding Lights The Weeknd' or 'lofi study playlist'",
                    }
                },
                "required": ["query"],
            },
        }
    ],
    handler=_handle,
    examples=["Play Blinding Lights on Spotify", "Open my Discover Weekly", "Search lofi beats on Spotify"],
)

register_skill(SKILL)
