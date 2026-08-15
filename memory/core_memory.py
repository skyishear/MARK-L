"""
core_memory.py — JARVIS Core Memory Engine

This is the CORE memory system described in the architecture spec:
  - Categorized long-term facts with metadata (importance, confidence,
    source, project, sensitivity, expiration).
  - Separate memory_type: permanent | temporary | session | project.
  - Decision memory: WHAT was decided AND WHY (reasoning + constraints),
    so past decisions can be recalled and re-evaluated later.
  - A single, importance-aware context formatter for the system prompt,
    replacing the old "dump everything, trim oldest" JSON approach.

This module is intentionally independent of any specific skill/action —
it is CORE, not a feature. Skills call into it through the small public
API at the bottom of this file (remember / forget / recall /
record_decision / get_decisions / why / format_context_for_prompt).

Storage: SQLite (stdlib only — no new dependency). One connection is
opened per call and closed immediately; a module-level lock serializes
writes since the Gemini Live loop may call this from multiple threads.
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock

# ── Paths ─────────────────────────────────────────────────────────────────

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR   = get_base_dir()
DB_PATH    = BASE_DIR / "memory" / "core_memory.db"
LEGACY_JSON = BASE_DIR / "memory" / "long_term.json"   # old memory_manager.py store

_lock = Lock()

VALID_CATEGORIES = {
    "identity", "preferences", "habits", "goals_long", "goals_short",
    "projects", "technical", "people", "workflows", "problems_solutions",
    "instructions", "notes",
}
VALID_MEMORY_TYPES = {"permanent", "temporary", "session", "project"}

MAX_VALUE_LENGTH  = 500
CONTEXT_MAX_CHARS = 2200   # budget for what gets injected into the system prompt
MAX_ROWS_SOFT_CAP = 800    # trigger importance-aware pruning above this


# ── Schema ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                category    TEXT NOT NULL,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'permanent',
                importance  INTEGER NOT NULL DEFAULT 3,
                confidence  REAL NOT NULL DEFAULT 1.0,
                source      TEXT DEFAULT 'user_stated',
                project     TEXT,
                sensitive   INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL,
                last_used   TEXT NOT NULL,
                expires_at  TEXT,
                UNIQUE(category, key, project)
            );

            CREATE TABLE IF NOT EXISTS decisions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project       TEXT NOT NULL,
                decision      TEXT NOT NULL,
                reasoning     TEXT,
                constraints   TEXT,
                status        TEXT NOT NULL DEFAULT 'active',
                superseded_by INTEGER,
                created_at    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
            CREATE INDEX IF NOT EXISTS idx_mem_project  ON memories(project);
            CREATE INDEX IF NOT EXISTS idx_dec_project   ON decisions(project);
            """
        )


# ── Internal helpers ─────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truncate(val: str) -> str:
    val = str(val)
    return val if len(val) <= MAX_VALUE_LENGTH else val[:MAX_VALUE_LENGTH].rstrip() + "…"


def _norm_category(category: str) -> str:
    category = (category or "notes").strip().lower().replace(" ", "_")
    return category if category in VALID_CATEGORIES else "notes"


# ── Public API: facts ────────────────────────────────────────────────────

def remember(
    category: str,
    key: str,
    value: str,
    *,
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "user_stated",
    project: str | None = None,
    memory_type: str = "permanent",
    sensitive: bool = False,
    ttl_days: int | None = None,
) -> str:
    """Upsert a fact. Same (category, key, project) overwrites in place."""
    if not key or value is None or not str(value).strip():
        return "skipped: empty key/value"

    category = _norm_category(category)
    value    = _truncate(value)
    importance = max(1, min(5, int(importance)))
    confidence = max(0.0, min(1.0, float(confidence)))
    memory_type = memory_type if memory_type in VALID_MEMORY_TYPES else "permanent"
    expires_at  = (
        (datetime.now() + timedelta(days=ttl_days)).strftime("%Y-%m-%d %H:%M:%S")
        if ttl_days else None
    )

    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO memories
                (category, key, value, memory_type, importance, confidence,
                 source, project, sensitive, created_at, last_used, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(category, key, project) DO UPDATE SET
                value=excluded.value, memory_type=excluded.memory_type,
                importance=excluded.importance, confidence=excluded.confidence,
                source=excluded.source, sensitive=excluded.sensitive,
                last_used=excluded.last_used, expires_at=excluded.expires_at
            """,
            (category, key.strip(), value, memory_type, importance, confidence,
             source, project, int(sensitive), _now(), _now(), expires_at),
        )
    _maybe_prune()
    return f"remembered: {category}/{key}"


def forget(*, key: str | None = None, category: str | None = None,
           project: str | None = None) -> int:
    """Delete matching memories. At least one filter must be given. Returns rows deleted."""
    if not any([key, category, project]):
        return 0
    clauses, params = [], []
    if key:
        clauses.append("key = ?"); params.append(key)
    if category:
        clauses.append("category = ?"); params.append(_norm_category(category))
    if project:
        clauses.append("project = ?"); params.append(project)
    with _lock, _connect() as conn:
        cur = conn.execute(f"DELETE FROM memories WHERE {' AND '.join(clauses)}", params)
        return cur.rowcount


def recall(*, query: str | None = None, category: str | None = None,
           project: str | None = None, memory_type: str | None = None,
           limit: int = 25) -> list[dict]:
    """Search/filter memories. Touches last_used on returned rows."""
    clauses, params = ["(expires_at IS NULL OR expires_at > ?)"], [_now()]
    if query:
        clauses.append("(key LIKE ? OR value LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if category:
        clauses.append("category = ?"); params.append(_norm_category(category))
    if project:
        clauses.append("project = ?"); params.append(project)
    if memory_type:
        clauses.append("memory_type = ?"); params.append(memory_type)

    sql = (
        f"SELECT * FROM memories WHERE {' AND '.join(clauses)} "
        f"ORDER BY importance DESC, last_used DESC LIMIT ?"
    )
    params.append(limit)

    with _lock, _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(
                f"UPDATE memories SET last_used = ? WHERE id IN ({','.join('?'*len(ids))})",
                [_now(), *ids],
            )
    return [dict(r) for r in rows]


def _maybe_prune(max_rows: int = MAX_ROWS_SOFT_CAP) -> None:
    """Importance-aware pruning: drop the lowest importance/oldest rows first,
    never sensitive or importance>=4 rows, once the table grows too large."""
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
        if total <= max_rows:
            return
        excess = total - max_rows
        conn.execute(
            """
            DELETE FROM memories WHERE id IN (
                SELECT id FROM memories
                WHERE sensitive = 0 AND importance <= 2
                ORDER BY last_used ASC LIMIT ?
            )
            """,
            (excess,),
        )


def cleanup_expired() -> int:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (_now(),))
        return cur.rowcount


# ── Public API: decisions ────────────────────────────────────────────────

def record_decision(project: str, decision: str, reasoning: str = "",
                     constraints: str = "") -> str:
    if not project or not decision:
        return "skipped: project/decision required"
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO decisions (project, decision, reasoning, constraints, created_at)
               VALUES (?,?,?,?,?)""",
            (project.strip(), _truncate(decision), _truncate(reasoning),
             _truncate(constraints), _now()),
        )
    return f"decision recorded for project '{project}'"


def get_decisions(project: str, limit: int = 20) -> list[dict]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE project = ? AND status = 'active' "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def why(project: str, topic: str) -> list[dict]:
    """Find the reasoning behind past decisions matching a topic within a project."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions WHERE project = ? AND status = 'active' "
            "AND (decision LIKE ? OR reasoning LIKE ?) ORDER BY created_at DESC",
            (project, f"%{topic}%", f"%{topic}%"),
        ).fetchall()
    return [dict(r) for r in rows]


def supersede_decision(decision_id: int, new_decision_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE decisions SET status='superseded', superseded_by=? WHERE id=?",
            (new_decision_id, decision_id),
        )


# ── Prompt formatting ────────────────────────────────────────────────────

def format_context_for_prompt(project: str | None = None,
                               max_chars: int = CONTEXT_MAX_CHARS) -> str:
    """Build the block injected into the system prompt each turn.
    Pulls high-importance facts (globally + for the given project, if any)
    plus recent decisions for that project. Importance-ordered, budget-capped."""
    cleanup_expired()
    with _lock, _connect() as conn:
        facts = conn.execute(
            """SELECT * FROM memories
               WHERE expires_at IS NULL OR expires_at > ?
               ORDER BY importance DESC, last_used DESC LIMIT 60""",
            (_now(),),
        ).fetchall()
        decisions = []
        if project:
            decisions = conn.execute(
                "SELECT * FROM decisions WHERE project=? AND status='active' "
                "ORDER BY created_at DESC LIMIT 10",
                (project,),
            ).fetchall()

    by_cat: dict[str, list] = {}
    for f in facts:
        by_cat.setdefault(f["category"], []).append(f)

    lines = []
    cat_order = ["identity", "preferences", "habits", "projects", "goals_long",
                 "goals_short", "technical", "people", "workflows",
                 "problems_solutions", "instructions", "notes"]
    for cat in cat_order:
        rows = by_cat.get(cat)
        if not rows:
            continue
        lines.append(f"{cat.replace('_', ' ').title()}:")
        for r in rows[:10]:
            conf_note = "" if r["confidence"] >= 0.8 else "  (uncertain)"
            lines.append(f"  - {r['key'].replace('_', ' ')}: {r['value']}{conf_note}")

    if decisions:
        lines.append("")
        lines.append(f"Past decisions for project '{project}':")
        for d in decisions:
            reason = f"  — because: {d['reasoning']}" if d["reasoning"] else ""
            lines.append(f"  - {d['decision']}{reason}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 1] + "…"
    return result + "\n"


# ── One-time migration from the old flat JSON store ─────────────────────

def migrate_from_json() -> int:
    """Idempotent: pulls identity/preferences/projects/relationships/wishes/notes
    from the legacy long_term.json into the new engine, tagged source='migrated'.
    Safe to call on every startup — ON CONFLICT just re-updates the same rows."""
    if not LEGACY_JSON.exists():
        return 0
    try:
        data = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return 0

    cat_map = {
        "identity": "identity", "preferences": "preferences",
        "projects": "projects", "relationships": "people",
        "wishes": "goals_long", "notes": "notes",
    }
    count = 0
    for old_cat, new_cat in cat_map.items():
        for key, entry in (data.get(old_cat) or {}).items():
            val = entry.get("value") if isinstance(entry, dict) else entry
            if not val:
                continue
            remember(new_cat, key, val, importance=3, confidence=1.0,
                     source="migrated")
            count += 1
    return count
