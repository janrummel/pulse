"""Tests for pulse.db — Schema creation, event storage, session/project management."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pulse.db import PulseDB


@pytest.fixture
def db(tmp_path):
    """Create a fresh PulseDB in a temp directory."""
    db_path = tmp_path / "test_pulse.db"
    return PulseDB(str(db_path))


@pytest.fixture
def db_with_events(db):
    """DB pre-filled with a realistic session of events."""
    session_id = "sess_abc123"
    base_time = datetime(2026, 3, 14, 14, 0, 0)

    events = [
        {
            "timestamp": base_time.isoformat(),
            "session_id": session_id,
            "event_type": "SessionStart",
            "project_path": "/tmp/projects/example-app",
            "model": "claude-opus-4-6",
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "SessionStart"}',
        },
        {
            "timestamp": (base_time + timedelta(seconds=30)).isoformat(),
            "session_id": session_id,
            "event_type": "UserPromptSubmit",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": "Baue vault.py",
            "raw_json": '{"hook_event_name": "UserPromptSubmit"}',
        },
        {
            "timestamp": (base_time + timedelta(minutes=1)).isoformat(),
            "session_id": session_id,
            "event_type": "PreToolUse",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": "Write",
            "tool_input_summary": "file: src/vault.py",
            "tool_use_id": "tu_001",
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "PreToolUse"}',
        },
        {
            "timestamp": (base_time + timedelta(minutes=1, seconds=15)).isoformat(),
            "session_id": session_id,
            "event_type": "PostToolUse",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": "Write",
            "tool_input_summary": "file: src/vault.py",
            "tool_use_id": "tu_001",
            "tool_output_success": True,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "PostToolUse"}',
        },
        {
            "timestamp": (base_time + timedelta(minutes=2)).isoformat(),
            "session_id": session_id,
            "event_type": "PreToolUse",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": "Bash",
            "tool_input_summary": "bash: pytest",
            "tool_use_id": "tu_002",
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "PreToolUse"}',
        },
        {
            "timestamp": (base_time + timedelta(minutes=2, seconds=10)).isoformat(),
            "session_id": session_id,
            "event_type": "PostToolUse",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": "Bash",
            "tool_input_summary": "bash: pytest",
            "tool_use_id": "tu_002",
            "tool_output_success": False,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "PostToolUse"}',
        },
        {
            "timestamp": (base_time + timedelta(minutes=10)).isoformat(),
            "session_id": session_id,
            "event_type": "Stop",
            "project_path": "/tmp/projects/example-app",
            "model": None,
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "Stop"}',
        },
    ]

    for event in events:
        db.insert_event(event)

    return db, session_id


class TestSchemaCreation:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "new.db"
        assert not db_path.exists()
        PulseDB(str(db_path))
        assert db_path.exists()

    def test_creates_events_table(self, db):
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "events" in table_names

    def test_creates_sessions_table(self, db):
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "sessions" in table_names

    def test_creates_projects_table(self, db):
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "projects" in table_names

    def test_creates_tasks_table(self, db):
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        assert "tasks" in table_names

    def test_wal_mode_enabled(self, db):
        result = db.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"

    def test_idempotent_init(self, tmp_path):
        """Creating PulseDB twice on same file should not error."""
        db_path = tmp_path / "idem.db"
        db1 = PulseDB(str(db_path))
        db1.insert_event({
            "timestamp": "2026-03-14T14:00:00",
            "session_id": "s1",
            "event_type": "SessionStart",
            "project_path": "/tmp",
            "model": "opus",
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": "{}",
        })
        db2 = PulseDB(str(db_path))
        count = db2.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1


class TestEventInsert:
    def test_insert_event(self, db):
        db.insert_event({
            "timestamp": "2026-03-14T14:00:00",
            "session_id": "sess_001",
            "event_type": "SessionStart",
            "project_path": "/tmp/projects/test",
            "model": "claude-opus-4-6",
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"hook_event_name": "SessionStart"}',
        })
        count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1

    def test_insert_returns_id(self, db):
        event_id = db.insert_event({
            "timestamp": "2026-03-14T14:00:00",
            "session_id": "sess_001",
            "event_type": "SessionStart",
            "project_path": "/tmp",
            "model": None,
            "tool_name": None,
            "tool_input_summary": None,
            "tool_use_id": None,
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": "{}",
        })
        assert isinstance(event_id, int)
        assert event_id >= 1

    def test_insert_preserves_all_fields(self, db):
        db.insert_event({
            "timestamp": "2026-03-14T14:01:00",
            "session_id": "sess_002",
            "event_type": "PreToolUse",
            "project_path": "/tmp/projects/test",
            "model": None,
            "tool_name": "Write",
            "tool_input_summary": "file: src/main.py",
            "tool_use_id": "tu_abc",
            "tool_output_success": None,
            "prompt_text": None,
            "raw_json": '{"tool_name": "Write"}',
        })
        row = db.execute("SELECT * FROM events WHERE session_id='sess_002'").fetchone()
        assert row is not None
        assert row["timestamp"] == "2026-03-14T14:01:00"
        assert row["session_id"] == "sess_002"
        assert row["tool_name"] == "Write"
        assert row["tool_use_id"] == "tu_abc"


class TestEventQueries:
    def test_get_events_by_session(self, db_with_events):
        db, session_id = db_with_events
        events = db.get_events_by_session(session_id)
        assert len(events) == 7

    def test_get_events_by_session_empty(self, db):
        events = db.get_events_by_session("nonexistent")
        assert events == []

    def test_get_events_by_type(self, db_with_events):
        db, session_id = db_with_events
        events = db.get_events_by_type(session_id, "PreToolUse")
        assert len(events) == 2

    def test_get_events_by_project(self, db_with_events):
        db, _ = db_with_events
        events = db.get_events_by_project("/tmp/projects/example-app")
        assert len(events) == 7

    def test_get_session_ids(self, db_with_events):
        db, session_id = db_with_events
        sessions = db.get_session_ids()
        assert session_id in sessions


class TestProjectManagement:
    def test_add_project(self, db):
        project_id = db.add_project(
            name="example-app",
            path="/tmp/projects/example-app",
            deadline="2026-03-19T08:59:00",
            total_tasks=12,
        )
        assert isinstance(project_id, int)

    def test_get_project(self, db):
        db.add_project(name="example-app", path="/tmp/wd")
        project = db.get_project("example-app")
        assert project is not None
        assert project["name"] == "example-app"
        assert project["status"] == "active"

    def test_get_project_not_found(self, db):
        project = db.get_project("nonexistent")
        assert project is None

    def test_get_active_projects(self, db):
        db.add_project(name="proj_a", path="/a", status="active")
        db.add_project(name="proj_b", path="/b", status="paused")
        db.add_project(name="proj_c", path="/c", status="active")
        active = db.get_active_projects()
        assert len(active) == 2
        names = [p["name"] for p in active]
        assert "proj_a" in names
        assert "proj_c" in names

    def test_update_project(self, db):
        db.add_project(name="proj", path="/p", total_tasks=10)
        db.update_project("proj", completed_tasks=5, status="active")
        project = db.get_project("proj")
        assert project["completed_tasks"] == 5


class TestTaskManagement:
    def test_add_task(self, db):
        pid = db.add_project(name="proj", path="/p")
        task_id = db.add_task(project_id=pid, name="vault.py")
        assert isinstance(task_id, int)

    def test_get_tasks_for_project(self, db):
        pid = db.add_project(name="proj", path="/p")
        db.add_task(project_id=pid, name="vault.py")
        db.add_task(project_id=pid, name="scanner.py")
        tasks = db.get_tasks(pid)
        assert len(tasks) == 2

    def test_update_task_status(self, db):
        pid = db.add_project(name="proj", path="/p")
        tid = db.add_task(project_id=pid, name="vault.py")
        db.update_task(tid, status="done", actual_minutes=8.0, debug_cycles=1)
        tasks = db.get_tasks(pid)
        done_task = [t for t in tasks if t["id"] == tid][0]
        assert done_task["status"] == "done"
        assert done_task["actual_minutes"] == 8.0
        assert done_task["debug_cycles"] == 1


class TestMdSyncColumns:
    def test_projects_has_md_sync_columns(self, db):
        """New md_source_path and md_last_synced columns exist."""
        columns = [
            r[1] for r in db.execute("PRAGMA table_info(projects)").fetchall()
        ]
        assert "md_source_path" in columns
        assert "md_last_synced" in columns


class TestSessionManagement:
    def test_upsert_session(self, db):
        db.upsert_session(
            session_id="sess_001",
            project_path="/tmp/test",
            model="opus",
            started_at="2026-03-14T14:00:00",
        )
        session = db.get_session("sess_001")
        assert session is not None
        assert session["model"] == "opus"

    def test_update_session_on_end(self, db):
        db.upsert_session(
            session_id="sess_001",
            project_path="/tmp",
            model="opus",
            started_at="2026-03-14T14:00:00",
        )
        db.upsert_session(
            session_id="sess_001",
            ended_at="2026-03-14T14:30:00",
            duration_seconds=1800.0,
            prompt_count=5,
            tool_call_count=20,
            tool_error_count=2,
        )
        session = db.get_session("sess_001")
        assert session["duration_seconds"] == 1800.0
        assert session["prompt_count"] == 5
        assert session["tool_error_count"] == 2

    def test_get_recent_sessions(self, db):
        for i in range(5):
            db.upsert_session(
                session_id=f"sess_{i:03d}",
                project_path="/tmp/test",
                started_at=f"2026-03-14T{10+i}:00:00",
            )
        recent = db.get_recent_sessions("/tmp/test", limit=3)
        assert len(recent) == 3
