"""Tests for pulse.usage — stats-cache import and usage queries."""

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from pulse.db import PulseDB
from pulse.usage import get_daily_usage, get_peak_hour, get_usage_summary, import_stats_cache, needs_import


STATS_CACHE_FIXTURE = {
    "version": 1,
    "lastComputedDate": "2026-03-16",
    "dailyActivity": [
        {"date": "2026-03-15", "messageCount": 89, "sessionCount": 5, "toolCallCount": 34},
        {"date": "2026-03-16", "messageCount": 142, "sessionCount": 8, "toolCallCount": 53},
    ],
    "dailyModelTokens": [
        {"date": "2026-03-15", "tokensByModel": {"claude-opus-4-6": 92000}},
        {"date": "2026-03-16", "tokensByModel": {"claude-opus-4-6": 125000, "claude-haiku-4-5-20251001": 3200}},
    ],
    "modelUsage": {
        "claude-opus-4-6": {
            "inputTokens": 975029,
            "outputTokens": 138210,
            "cacheReadInputTokens": 1144196957,
            "cacheCreationInputTokens": 139016144,
        }
    },
    "hourCounts": {"9": 45, "10": 120, "14": 234, "15": 189, "16": 98},
    "totalSessions": 415,
    "totalMessages": 28758,
}


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_pulse.db"
    return PulseDB(str(db_path))


@pytest.fixture
def stats_file(tmp_path):
    p = tmp_path / "stats-cache.json"
    p.write_text(json.dumps(STATS_CACHE_FIXTURE))
    return p


def test_import_stats_cache(db, stats_file):
    """Import fixture data, check daily_usage entries."""
    count = import_stats_cache(db, str(stats_file))
    assert count == 2

    rows = db.execute("SELECT * FROM daily_usage ORDER BY date").fetchall()
    assert len(rows) == 2

    day1 = dict(rows[0])
    assert day1["date"] == "2026-03-15"
    assert day1["message_count"] == 89
    assert day1["session_count"] == 5
    assert day1["tool_call_count"] == 34
    assert json.loads(day1["tokens_by_model"]) == {"claude-opus-4-6": 92000}

    day2 = dict(rows[1])
    assert day2["date"] == "2026-03-16"
    assert day2["message_count"] == 142
    assert json.loads(day2["tokens_by_model"])["claude-opus-4-6"] == 125000


def test_import_upsert(db, stats_file):
    """Double import overwrites correctly."""
    import_stats_cache(db, str(stats_file))
    import_stats_cache(db, str(stats_file))

    rows = db.execute("SELECT * FROM daily_usage").fetchall()
    assert len(rows) == 2  # Still 2 rows, not 4


def test_needs_import_no_file(db, tmp_path):
    """No stats-cache file → False."""
    assert needs_import(db, str(tmp_path / "nonexistent.json")) is False


def test_needs_import_fresh(db, stats_file):
    """File older than last import → False."""
    import_stats_cache(db, str(stats_file))
    assert needs_import(db, str(stats_file)) is False


def test_needs_import_stale(db, stats_file):
    """File newer than last import → True."""
    import_stats_cache(db, str(stats_file))
    db.execute("UPDATE daily_usage SET imported_at = '2020-01-01T00:00:00'")
    db.execute("COMMIT")
    assert needs_import(db, str(stats_file)) is True


def test_tokens_by_model_json(db, stats_file):
    """JSON string round-trips correctly."""
    import_stats_cache(db, str(stats_file))
    row = db.execute("SELECT tokens_by_model FROM daily_usage WHERE date='2026-03-16'").fetchone()
    parsed = json.loads(row[0])
    assert isinstance(parsed, dict)
    assert parsed["claude-opus-4-6"] == 125000


def test_import_malformed_json(db, tmp_path):
    """Truncated JSON → no crash, returns 0."""
    bad = tmp_path / "stats-cache.json"
    bad.write_text("{truncated")
    count = import_stats_cache(db, str(bad))
    assert count == 0


def test_get_daily_usage(db, stats_file):
    """Returns last N days ordered by date descending."""
    import_stats_cache(db, str(stats_file))
    days = get_daily_usage(db, days=7)
    assert len(days) == 2
    assert days[0]["date"] == "2026-03-16"  # Most recent first
    assert days[1]["date"] == "2026-03-15"


def test_get_usage_summary(db, stats_file):
    """Calculates totals and averages."""
    import_stats_cache(db, str(stats_file))
    summary = get_usage_summary(db, days=7)
    assert summary["total_messages"] == 89 + 142
    assert summary["total_sessions"] == 5 + 8
    assert summary["avg_messages_per_session"] == (89 + 142) / (5 + 8)
    assert "claude-opus-4-6" in summary["model_mix"]


def test_get_peak_hour(stats_file):
    """Finds hour with most messages from stats-cache.json."""
    hour, count = get_peak_hour(str(stats_file))
    assert hour == "14"
    assert count == 234


def test_get_peak_hour_no_file(tmp_path):
    """Missing file → None."""
    result = get_peak_hour(str(tmp_path / "nonexistent.json"))
    assert result is None


from pulse.usage import parse_session_usage, SessionUsage


TRANSCRIPT_LINES = [
    json.dumps({
        "uuid": "a1", "type": "user", "timestamp": "2026-03-16T14:00:00",
        "sessionId": "sess-123",
        "message": {"role": "user", "content": "Hello"}
    }),
    json.dumps({
        "uuid": "a2", "type": "assistant", "timestamp": "2026-03-16T14:00:05",
        "sessionId": "sess-123",
        "message": {
            "role": "assistant", "model": "claude-opus-4-6",
            "content": [{"type": "text", "text": "Hi there"}],
            "usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 1000
            }
        }
    }),
    json.dumps({
        "uuid": "a3", "type": "user", "timestamp": "2026-03-16T14:01:00",
        "sessionId": "sess-123",
        "message": {"role": "user", "content": "Do something"}
    }),
    json.dumps({
        "uuid": "a4", "type": "assistant", "timestamp": "2026-03-16T14:01:10",
        "sessionId": "sess-123",
        "message": {
            "role": "assistant", "model": "claude-opus-4-6",
            "content": [{"type": "text", "text": "Done"}],
            "usage": {
                "input_tokens": 200, "output_tokens": 30,
                "cache_read_input_tokens": 8000, "cache_creation_input_tokens": 500
            }
        }
    }),
]


def test_parse_session_usage(tmp_path):
    """Parses transcript JSONL correctly."""
    p = tmp_path / "sess-123.jsonl"
    p.write_text("\n".join(TRANSCRIPT_LINES))

    result = parse_session_usage(str(p))
    assert result.session_id == "sess-123"
    assert result.primary_model == "claude-opus-4-6"
    assert result.total_input_tokens == 300
    assert result.total_output_tokens == 50
    assert result.total_cache_read == 13000
    assert result.total_cache_creation == 1500
    assert result.message_count == 2  # Only assistant messages counted
    assert result.duration_minutes > 0


def test_parse_session_usage_empty(tmp_path):
    """Empty file → sensible defaults."""
    p = tmp_path / "empty.jsonl"
    p.write_text("")

    result = parse_session_usage(str(p))
    assert result.total_input_tokens == 0
    assert result.total_output_tokens == 0
    assert result.message_count == 0
    assert result.duration_minutes == 0
