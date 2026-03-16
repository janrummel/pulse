# Usage-Tracking Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Claude Code's stats-cache.json into Pulse's SQLite DB and display token usage, model mix, and session intensity via `pulse usage` and `pulse recap`.

**Architecture:** New `usage.py` module reads stats-cache.json (daily aggregates) and transcript JSONL (per-session, on-demand). Lazy import on CLI invocation via mtime check. New `daily_usage` table stores imported data.

**Tech Stack:** Python stdlib (`json`, `pathlib`, `dataclasses`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-16-usage-tracking-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/pulse/db.py` | Modify | Add `daily_usage` table to `_SCHEMA` |
| `src/pulse/config.py` | Modify | Add `stats_cache_path` default + property |
| `src/pulse/usage.py` | Create | Import logic, query helpers, transcript parser |
| `tests/test_usage.py` | Create | All usage tests (import, query, transcript, edge cases) |
| `src/pulse/cli.py` | Modify | Add `pulse usage` command + recap integration + lazy import helper |

---

## Chunk 1: DB Schema + Config + Import Foundation

### Task 1: Add daily_usage table to DB schema + stats_cache_path to config

**Files:**
- Modify: `src/pulse/db.py:58-70` (add CREATE TABLE to _SCHEMA, after tasks table)
- Modify: `src/pulse/config.py:14-22` (_DEFAULTS) and add property
- Test: `tests/test_db.py`, `tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_db.py`, add:

```python
def test_daily_usage_table_exists(db):
    """daily_usage table is created with schema."""
    columns = [r[1] for r in db.execute("PRAGMA table_info(daily_usage)").fetchall()]
    assert "date" in columns
    assert "message_count" in columns
    assert "tokens_by_model" in columns
    assert "imported_at" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_db.py::test_daily_usage_table_exists -v`

- [ ] **Step 3: Add daily_usage table to _SCHEMA in db.py**

In `src/pulse/db.py`, append after the `tasks` CREATE TABLE block (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS daily_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    message_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    tokens_by_model TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- [ ] **Step 4: Add stats_cache_path to config.py**

In `src/pulse/config.py`, add to `_DEFAULTS` dict:

```python
"stats_cache_path": str(Path.home() / ".claude" / "stats-cache.json"),
```

Add property to `PulseConfig` class (after `dashboard_refresh`):

```python
@property
def stats_cache_path(self) -> str:
    return str(Path(self._data["stats_cache_path"]).expanduser())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/pulse/db.py src/pulse/config.py tests/test_db.py
git commit -m "feat(db): add daily_usage table and stats_cache_path config"
```

### Task 2: Create usage.py with import_stats_cache and needs_import

**Files:**
- Create: `src/pulse/usage.py`
- Create: `tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_usage.py`:

```python
"""Tests for pulse.usage — stats-cache import and usage queries."""

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pytest

from pulse.db import PulseDB
from pulse.usage import import_stats_cache, needs_import


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
    # imported_at is now(), file mtime is in the past
    assert needs_import(db, str(stats_file)) is False


def test_needs_import_stale(db, stats_file):
    """File newer than last import → True."""
    import_stats_cache(db, str(stats_file))
    # Backdate imported_at
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_usage.py -v`

- [ ] **Step 3: Create usage.py with import + needs_import**

Create `src/pulse/usage.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_usage.py -v`

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest -v`

- [ ] **Step 6: Commit**

```bash
git add src/pulse/usage.py tests/test_usage.py
git commit -m "feat(usage): add import_stats_cache and needs_import"
```

---

## Chunk 2: Query Helpers + Transcript Parser

### Task 3: Add get_daily_usage, get_usage_summary, get_peak_hour

**Files:**
- Modify: `src/pulse/usage.py`
- Modify: `tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_usage.py`:

```python
from pulse.usage import get_daily_usage, get_usage_summary, get_peak_hour


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_usage.py::test_get_daily_usage -v`

- [ ] **Step 3: Implement query functions**

Append to `src/pulse/usage.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_usage.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/pulse/usage.py tests/test_usage.py
git commit -m "feat(usage): add get_daily_usage, get_usage_summary, get_peak_hour"
```

### Task 4: Add parse_session_usage (transcript parser)

**Files:**
- Modify: `src/pulse/usage.py`
- Modify: `tests/test_usage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_usage.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_usage.py::test_parse_session_usage -v`

- [ ] **Step 3: Implement parse_session_usage**

Append to `src/pulse/usage.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_usage.py -v`

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest -v`

- [ ] **Step 6: Commit**

```bash
git add src/pulse/usage.py tests/test_usage.py
git commit -m "feat(usage): add parse_session_usage transcript parser"
```

---

## Chunk 3: CLI Integration

### Task 5: Add `pulse usage` CLI command

**Files:**
- Modify: `src/pulse/cli.py`
- Modify: `tests/test_usage.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_usage.py`:

```python
from pulse.cli import main


def test_cli_usage_command(db, stats_file, capsys, monkeypatch):
    """pulse usage runs without error."""
    monkeypatch.setattr("pulse.cli._DEFAULT_DB_PATH", str(db._path))
    monkeypatch.setattr("pulse.usage._STATS_CACHE_PATH", str(stats_file))

    main(["usage"])
    captured = capsys.readouterr()
    assert "Usage" in captured.out or "usage" in captured.out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_usage.py::test_cli_usage_command -v`

- [ ] **Step 3: Add usage subparser and handler to cli.py**

In `src/pulse/cli.py`, add after the `sync` subparser:

```python
# usage
p_usage = sub.add_parser("usage", help="Show token usage statistics")
p_usage.add_argument("--days", type=int, default=7, help="Number of days to show (default: 7)")
p_usage.add_argument("--session", help="Session ID for detailed transcript analysis")
```

Add `_ensure_usage_imported` helper after `_ensure_synced`:

```python
def _ensure_usage_imported(db: PulseDB) -> None:
    """Lazy import: import stats-cache.json if changed."""
    from pulse.usage import import_stats_cache, needs_import
    if needs_import(db):
        import_stats_cache(db)
```

In the command dispatch block, add:

```python
elif args.command == "usage":
    _cmd_usage(args)
```

Add the handler function:

```python
def _cmd_usage(args: argparse.Namespace) -> None:
    """Show token usage statistics."""
    from rich.console import Console
    from rich.table import Table
    from rich import box as rich_box

    db = PulseDB(_DEFAULT_DB_PATH)
    _ensure_usage_imported(db)

    if args.session:
        _show_session_usage(args.session)
        return

    from pulse.usage import get_daily_usage, get_usage_summary, get_peak_hour

    console = Console()
    usage = get_daily_usage(db, days=args.days)

    if not usage:
        console.print("\n  Noch keine Usage-Daten importiert.\n")
        return

    console.print(f"\n  [bold]Usage (letzte {args.days} Tage)[/bold]\n")

    table = Table(show_header=True, box=rich_box.SIMPLE)
    table.add_column("Tag", width=12)
    table.add_column("Messages", width=10, justify="right")
    table.add_column("Sessions", width=10, justify="right")
    table.add_column("Tokens", width=12, justify="right")

    for day in usage:
        tokens = ""
        if day["tokens_by_model"]:
            import json
            total = sum(json.loads(day["tokens_by_model"]).values())
            if total >= 1000:
                tokens = f"{total // 1000}k"
            else:
                tokens = str(total)

        table.add_row(
            day["date"],
            str(day["message_count"]),
            str(day["session_count"]),
            tokens,
        )

    console.print(table)

    # Summary
    summary = get_usage_summary(db, days=args.days)
    if summary["model_mix"]:
        parts = []
        for model, pct in sorted(summary["model_mix"].items(), key=lambda x: -x[1]):
            short = model.split("-")[1].capitalize() if "-" in model else model
            parts.append(f"{short} {pct:.0f}%")
        console.print(f"  Model-Mix: {'  '.join(parts)}")

    peak = get_peak_hour()
    if peak:
        hour, count = peak
        console.print(f"  Peak: {hour}:00-{int(hour)+1}:00")

    if summary["total_sessions"] > 0:
        avg = summary["avg_messages_per_session"]
        console.print(f"  Durchschnitt: {avg:.0f} msg/session")

    console.print()


def _show_session_usage(session_id: str) -> None:
    """Show detailed usage for a single session from transcript."""
    from rich.console import Console
    from pulse.usage import parse_session_usage

    db = PulseDB(_DEFAULT_DB_PATH)
    console = Console()

    # Find transcript path from events
    row = db.execute(
        "SELECT raw_json FROM events WHERE session_id=? AND event_type='SessionStart' LIMIT 1",
        (session_id,),
    ).fetchone()

    if not row or not row["raw_json"]:
        console.print(f"\n  Session '{session_id}' nicht gefunden.\n")
        return

    import json
    event_data = json.loads(row["raw_json"])
    transcript_path = event_data.get("transcript_path")

    if not transcript_path or not Path(transcript_path).exists():
        console.print(f"\n  Transcript nicht gefunden fuer Session '{session_id}'.\n")
        return

    usage = parse_session_usage(transcript_path)

    console.print(f"\n  [bold]Session {session_id[:12]}... ({usage.duration_minutes:.0f} min)[/bold]\n")

    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1000:
            return f"{n // 1000}k"
        return str(n)

    console.print(f"  Input:   {_fmt(usage.total_input_tokens)} tokens")
    console.print(f"  Output:  {_fmt(usage.total_output_tokens)} tokens")
    console.print(f"  Cache:   {_fmt(usage.total_cache_read)} read / {_fmt(usage.total_cache_creation)} created")
    if usage.primary_model:
        console.print(f"  Model:   {usage.primary_model}")
    if usage.prompts_per_minute > 0:
        console.print(f"  Rate:    {usage.prompts_per_minute:.1f} prompts/min")
    console.print()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_usage.py::test_cli_usage_command -v`

- [ ] **Step 5: Commit**

```bash
git add src/pulse/cli.py tests/test_usage.py
git commit -m "feat(cli): add pulse usage command"
```

### Task 6: Integrate usage into pulse recap

**Files:**
- Modify: `src/pulse/cli.py:363-463` (_cmd_recap function)

- [ ] **Step 1: Add usage line to daily recap**

In `_cmd_recap`, after the existing table output (around line 441, after `console.print(table)`), add usage info for the daily recap path (the `else` branch):

```python
        # Usage info (after the existing table.add_row calls, before tasks_completed)
        _ensure_usage_imported(db)
        from pulse.usage import get_daily_usage
        import json as _json
        day_usage = db.execute(
            "SELECT tokens_by_model FROM daily_usage WHERE date=?",
            (recap["date"],),
        ).fetchone()
        if day_usage and day_usage["tokens_by_model"]:
            tokens = _json.loads(day_usage["tokens_by_model"])
            total = sum(tokens.values())
            grand = f"{total // 1000}k" if total >= 1000 else str(total)
            parts = []
            grand_total = sum(tokens.values())
            for model, count in sorted(tokens.items(), key=lambda x: -x[1]):
                short = model.split("-")[1].capitalize() if "-" in model else model
                pct = count / grand_total * 100 if grand_total else 0
                parts.append(f"{short} {pct:.0f}%")
            table.add_row("Token-Verbrauch", f"{grand} ({', '.join(parts)})")
```

Insert this block right after the last `table.add_row("Dateien", ...)` line and before `console.print(table)`.

- [ ] **Step 2: Run full test suite**

Run: `python3 -m pytest -v`

- [ ] **Step 3: Commit**

```bash
git add src/pulse/cli.py
git commit -m "feat(cli): add token usage line to pulse recap"
```

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest -v`

- [ ] **Step 2: Smoke test — import real stats-cache**

Run: `pulse usage`
Expected: Table with daily usage data from real stats-cache.json

- [ ] **Step 3: Smoke test — recap with usage**

Run: `pulse recap`
Expected: Existing recap output plus a "Token-Verbrauch" line

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during usage-tracking smoke test"
```
