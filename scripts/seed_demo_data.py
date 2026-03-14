#!/usr/bin/env python3
"""Seed realistic demo data into a Pulse database.

Creates 3 projects with multiple sessions, tool calls, debug cycles,
and varying velocities — useful for testing the Analyzer, Planner, and Dashboard.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from pulse.db import PulseDB

# Use a separate demo DB to not pollute real data
DEMO_DB_PATH = str(Path.home() / ".pulse" / "pulse-demo.db")


def seed(db_path: str | None = None) -> PulseDB:
    """Seed a database with realistic demo data."""
    db = PulseDB(db_path or DEMO_DB_PATH)

    # --- Projects ---
    p1 = db.add_project(
        name="example-app",
        path="/tmp/projects/example-app",
        deadline="2026-03-19T08:59:00",
        total_tasks=12,
        status="active",
    )
    p2 = db.add_project(
        name="data-pipeline",
        path="/tmp/projects/data-pipeline",
        total_tasks=8,
        status="active",
    )
    p3 = db.add_project(
        name="infra-tools",
        path="/tmp/projects/infra-tools",
        total_tasks=6,
        status="paused",
    )

    # --- Tasks for example-app ---
    tasks_app = [
        ("vault.py", "done", 3.0, 0),
        ("scanner.py + patterns", "done", 12.0, 1),
        ("proxy.py", "done", 47.0, 6),
        ("rehydrator.py", "done", 4.0, 0),
        ("anomaly.py", "done", 12.0, 2),
        ("alerter.py", "in_progress", None, 0),
        ("agent.py", "pending", None, 0),
        ("dashboard.py", "pending", None, 0),
        ("config.py", "pending", None, 0),
        ("cli.py", "pending", None, 0),
        ("tests", "pending", None, 0),
        ("demo.sh", "pending", None, 0),
    ]
    for name, status, actual, debug in tasks_app:
        tid = db.add_task(project_id=p1, name=name, estimated_minutes=actual)
        db.update_task(tid, status=status, actual_minutes=actual, debug_cycles=debug)

    db.update_project("example-app", completed_tasks=5)

    # --- Tasks for data-pipeline ---
    tasks_kf = [
        ("pipeline.py", "done", 18.0, 2),
        ("indexer.py", "done", 8.0, 0),
        ("search.py", "done", 15.0, 3),
        ("embeddings.py", "in_progress", None, 0),
        ("cache.py", "pending", None, 0),
        ("api.py", "pending", None, 0),
        ("cli.py", "pending", None, 0),
        ("tests", "pending", None, 0),
    ]
    for name, status, actual, debug in tasks_kf:
        tid = db.add_task(project_id=p2, name=name)
        db.update_task(tid, status=status, actual_minutes=actual, debug_cycles=debug)

    db.update_project("data-pipeline", completed_tasks=3)

    # --- Sessions ---
    _seed_sessions(db, "/tmp/projects/example-app", "example-app", 3)
    _seed_sessions(db, "/tmp/projects/data-pipeline", "data-pipeline", 2)

    return db


def _seed_sessions(db: PulseDB, project_path: str, prefix: str, count: int) -> None:
    """Generate realistic sessions with tool calls and debug cycles."""
    base_date = datetime(2026, 3, 12, 10, 0, 0)

    for s in range(count):
        session_id = f"sess_{prefix}_{s:03d}"
        session_start = base_date + timedelta(days=s, hours=random.randint(0, 4))
        cursor = session_start

        # SessionStart
        _add_event(db, cursor, session_id, "SessionStart", project_path,
                   model="claude-opus-4-6")
        cursor += timedelta(seconds=2)

        # Simulate 3-8 prompt rounds per session
        num_rounds = random.randint(3, 8)
        tool_calls = 0
        tool_errors = 0
        prompts = 0

        for r in range(num_rounds):
            # UserPromptSubmit
            prompts += 1
            prompt_texts = [
                "Baue vault.py mit Tests",
                "Jetzt scanner.py mit den Patterns",
                "Weiter mit proxy.py",
                "Fix den Testfehler",
                "Refactor die Config",
                "Schreib Integration-Tests",
                "Optimiere die Performance",
                "Dokumentation aktualisieren",
            ]
            _add_event(db, cursor, session_id, "UserPromptSubmit", project_path,
                       prompt_text=random.choice(prompt_texts))
            cursor += timedelta(seconds=random.randint(1, 5))

            # 3-10 tool calls per round
            num_tools = random.randint(3, 10)
            for t in range(num_tools):
                tool_use_id = f"tu_{session_id}_{r}_{t}"
                tool = random.choices(
                    ["Write", "Edit", "Bash", "Read", "Glob", "Grep", "Agent"],
                    weights=[15, 20, 25, 15, 10, 10, 5],
                )[0]

                tool_input = _make_tool_input(tool)

                # PreToolUse
                _add_event(db, cursor, session_id, "PreToolUse", project_path,
                           tool_name=tool, tool_input_summary=tool_input,
                           tool_use_id=tool_use_id)
                cursor += timedelta(seconds=random.uniform(0.5, 3))

                # PostToolUse — 15% chance of failure
                success = random.random() > 0.15
                tool_calls += 1
                if not success:
                    tool_errors += 1

                _add_event(db, cursor, session_id, "PostToolUse", project_path,
                           tool_name=tool, tool_input_summary=tool_input,
                           tool_use_id=tool_use_id, tool_output_success=success)
                cursor += timedelta(seconds=random.uniform(0.2, 1))

            # Stop (agent done, waiting for human)
            _add_event(db, cursor, session_id, "Stop", project_path)
            # Human wait time: 30s to 5min
            cursor += timedelta(seconds=random.randint(30, 300))

        # SessionEnd
        duration = (cursor - session_start).total_seconds()
        _add_event(db, cursor, session_id, "SessionEnd", project_path)

        db.upsert_session(
            session_id=session_id,
            project_path=project_path,
            model="claude-opus-4-6",
            started_at=session_start.isoformat(),
            ended_at=cursor.isoformat(),
            duration_seconds=duration,
            prompt_count=prompts,
            tool_call_count=tool_calls,
            tool_error_count=tool_errors,
        )


def _add_event(
    db: PulseDB,
    timestamp: datetime,
    session_id: str,
    event_type: str,
    project_path: str,
    model: str | None = None,
    tool_name: str | None = None,
    tool_input_summary: str | None = None,
    tool_use_id: str | None = None,
    tool_output_success: bool | None = None,
    prompt_text: str | None = None,
) -> None:
    raw = {
        "session_id": session_id,
        "hook_event_name": event_type,
        "cwd": project_path,
    }
    if model:
        raw["model"] = model
    if tool_name:
        raw["tool_name"] = tool_name

    db.insert_event({
        "timestamp": timestamp.isoformat(),
        "session_id": session_id,
        "event_type": event_type,
        "project_path": project_path,
        "model": model,
        "tool_name": tool_name,
        "tool_input_summary": tool_input_summary,
        "tool_use_id": tool_use_id,
        "tool_output_success": tool_output_success,
        "prompt_text": prompt_text,
        "raw_json": json.dumps(raw),
    })


def _make_tool_input(tool: str) -> str:
    files = ["vault.py", "scanner.py", "proxy.py", "config.py", "cli.py",
             "test_vault.py", "test_scanner.py", "main.py"]
    if tool == "Write":
        return f"file: src/{random.choice(files)}"
    elif tool == "Edit":
        return f"file: src/{random.choice(files)}"
    elif tool == "Bash":
        cmds = ["pytest tests/ -v", "python3 -m pytest", "git status",
                 "pip install -e .", "mypy src/", "ls -la"]
        return f"bash: {random.choice(cmds)}"
    elif tool == "Read":
        return f"file: src/{random.choice(files)}"
    elif tool in ("Glob", "Grep"):
        return f"pattern: **/*.py"
    elif tool == "Agent":
        return "keys: prompt, description"
    return ""


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    db = seed(path)
    total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    projects = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    print(f"Seeded: {total} events, {sessions} sessions, {projects} projects")
    if not path:
        print(f"DB: {DEMO_DB_PATH}")
