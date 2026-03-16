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


def get_daily_usage(db: PulseDB, days: int = 7) -> list[dict]:
    """Get the last N days of usage data, most recent first."""
    rows = db.execute(
        "SELECT * FROM daily_usage ORDER BY date DESC LIMIT ?",
        (days,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_usage_summary(db: PulseDB, days: int = 7) -> dict:
    """Calculate totals and averages over the last N days."""
    usage = get_daily_usage(db, days)
    if not usage:
        return {
            "total_messages": 0,
            "total_sessions": 0,
            "total_tool_calls": 0,
            "avg_messages_per_session": 0,
            "model_mix": {},
            "days_count": 0,
        }

    total_messages = sum(d["message_count"] for d in usage)
    total_sessions = sum(d["session_count"] for d in usage)
    total_tool_calls = sum(d["tool_call_count"] for d in usage)

    # Aggregate model tokens
    model_totals: dict[str, int] = {}
    for d in usage:
        if d["tokens_by_model"]:
            tokens = json.loads(d["tokens_by_model"])
            for model, count in tokens.items():
                model_totals[model] = model_totals.get(model, 0) + count

    # Calculate percentages
    grand_total = sum(model_totals.values())
    model_mix = {}
    if grand_total > 0:
        for model, count in model_totals.items():
            model_mix[model] = round(count / grand_total * 100, 1)

    return {
        "total_messages": total_messages,
        "total_sessions": total_sessions,
        "total_tool_calls": total_tool_calls,
        "avg_messages_per_session": total_messages / total_sessions if total_sessions else 0,
        "model_mix": model_mix,
        "days_count": len(usage),
    }


def get_peak_hour(stats_path: str | None = None) -> tuple[str, int] | None:
    """Read hourCounts directly from stats-cache.json. Returns (hour, count) or None."""
    path = Path(stats_path) if stats_path else Path(_STATS_CACHE_PATH)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    hour_counts = data.get("hourCounts", {})
    if not hour_counts:
        return None

    peak = max(hour_counts.items(), key=lambda x: x[1])
    return peak


@dataclass
class SessionUsage:
    """Token usage stats for a single session, parsed from transcript JSONL."""

    session_id: str = ""
    primary_model: str = ""
    duration_minutes: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read: int = 0
    total_cache_creation: int = 0
    message_count: int = 0
    prompts_per_minute: float = 0.0


def parse_session_usage(transcript_path: str) -> SessionUsage:
    """Parse a transcript JSONL file for token usage stats."""
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_path}")

    session_id = ""
    model_counts: dict[str, int] = {}
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_creation = 0
    message_count = 0
    timestamps: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not session_id and entry.get("sessionId"):
            session_id = entry["sessionId"]

        if entry.get("timestamp"):
            timestamps.append(entry["timestamp"])

        if entry.get("type") != "assistant":
            continue

        msg = entry.get("message", {})
        usage = msg.get("usage", {})
        if not usage:
            continue

        message_count += 1
        total_input += usage.get("input_tokens", 0)
        total_output += usage.get("output_tokens", 0)
        total_cache_read += usage.get("cache_read_input_tokens", 0)
        total_cache_creation += usage.get("cache_creation_input_tokens", 0)

        model = msg.get("model", "")
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1

    # Duration from first to last timestamp
    duration_minutes = 0.0
    if len(timestamps) >= 2:
        try:
            first = datetime.fromisoformat(timestamps[0])
            last = datetime.fromisoformat(timestamps[-1])
            duration_minutes = (last - first).total_seconds() / 60
        except (ValueError, TypeError):
            pass

    # Primary model = most used
    primary_model = max(model_counts, key=model_counts.get) if model_counts else ""

    prompts_per_minute = message_count / duration_minutes if duration_minutes > 0 else 0.0

    return SessionUsage(
        session_id=session_id,
        primary_model=primary_model,
        duration_minutes=round(duration_minutes, 1),
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cache_read=total_cache_read,
        total_cache_creation=total_cache_creation,
        message_count=message_count,
        prompts_per_minute=round(prompts_per_minute, 1),
    )
