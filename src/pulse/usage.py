"""Pulse usage — import and query Claude Code usage statistics.

Reads stats-cache.json (daily aggregates) and transcript JSONL (per-session).
"""

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pulse.config import config as _cfg
from pulse.db import PulseDB

_STATS_CACHE_PATH = _cfg.stats_cache_path


def needs_import(db: PulseDB, stats_path: str | None = None) -> bool:
    """True if stats-cache.json is newer than the last import."""
    path = Path(stats_path) if stats_path else Path(_STATS_CACHE_PATH)
    if not path.exists():
        return False

    row = db.execute("SELECT MAX(imported_at) as last FROM daily_usage").fetchone()
    if row is None or row["last"] is None:
        return True

    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
    last_imported = datetime.fromisoformat(row["last"])
    return file_mtime > last_imported


def import_stats_cache(db: PulseDB, stats_path: str | None = None) -> int:
    """Import daily stats from Claude Code stats-cache.json.

    Returns number of days imported/updated.
    """
    path = Path(stats_path) if stats_path else Path(_STATS_CACHE_PATH)
    if not path.exists():
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Failed to read stats-cache: {e}", file=sys.stderr)
        return 0

    daily_activity = {d["date"]: d for d in data.get("dailyActivity", [])}
    daily_tokens = {d["date"]: d for d in data.get("dailyModelTokens", [])}

    all_dates = set(daily_activity.keys()) | set(daily_tokens.keys())
    count = 0

    for date in sorted(all_dates):
        activity = daily_activity.get(date, {})
        tokens = daily_tokens.get(date, {})

        message_count = activity.get("messageCount", 0)
        session_count = activity.get("sessionCount", 0)
        tool_call_count = activity.get("toolCallCount", 0)
        tokens_by_model = json.dumps(tokens.get("tokensByModel", {}))

        db.execute(
            """INSERT INTO daily_usage (date, message_count, session_count, tool_call_count, tokens_by_model, imported_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                message_count = excluded.message_count,
                session_count = excluded.session_count,
                tool_call_count = excluded.tool_call_count,
                tokens_by_model = excluded.tokens_by_model,
                imported_at = excluded.imported_at""",
            (date, message_count, session_count, tool_call_count, tokens_by_model, datetime.now().isoformat()),
        )
        count += 1

    db.execute("COMMIT")
    return count
