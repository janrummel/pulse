"""Tests for pulse.cli — CLI command routing and output."""

import json
from unittest.mock import patch
from io import StringIO

import pytest

from pulse.cli import main
from pulse.db import PulseDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    return PulseDB(str(db_path))


@pytest.fixture
def mock_db_path(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("pulse.cli._DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr("pulse.collector._DEFAULT_DB_PATH", db_path)
    return db_path


class TestCollectCommand:
    def test_collect_reads_stdin(self, mock_db_path, monkeypatch):
        payload = json.dumps({
            "session_id": "s1",
            "hook_event_name": "SessionStart",
            "cwd": "/tmp",
            "permission_mode": "default",
            "transcript_path": "/tmp/t.json",
            "model": "opus",
        })
        monkeypatch.setattr("sys.stdin", StringIO(payload))
        main(["collect", "--event", "SessionStart"])
        db = PulseDB(mock_db_path)
        events = db.get_events_by_session("s1")
        assert len(events) == 1


class TestInstallCommand:
    def test_install_prints_confirmation(self, tmp_path, monkeypatch, capsys):
        settings_path = str(tmp_path / "settings.json")
        monkeypatch.setattr("pulse.hooks._DEFAULT_SETTINGS_PATH", settings_path)
        main(["install"])
        captured = capsys.readouterr()
        assert "installiert" in captured.out.lower()


class TestAddCommand:
    def test_add_project(self, mock_db_path, capsys):
        main(["add", "example-app", "/tmp/example-app", "--tasks", "12"])
        db = PulseDB(mock_db_path)
        project = db.get_project("example-app")
        assert project is not None
        assert project["total_tasks"] == 12

    def test_add_with_deadline(self, mock_db_path, capsys):
        main(["add", "proj", "/tmp/p", "--deadline", "2026-03-19T08:59:00"])
        db = PulseDB(mock_db_path)
        project = db.get_project("proj")
        assert project["deadline"] == "2026-03-19T08:59:00"


class TestStatusCommand:
    def test_status_no_projects(self, mock_db_path, capsys):
        main(["status"])
        captured = capsys.readouterr()
        assert "keine projekte" in captured.out.lower()

    def test_status_shows_projects(self, mock_db_path, capsys):
        db = PulseDB(mock_db_path)
        db.add_project(name="alpha", path="/a", total_tasks=10, status="active")
        db.add_project(name="beta", path="/b", status="paused")
        main(["status"])
        captured = capsys.readouterr()
        assert "alpha" in captured.out
        assert "beta" in captured.out


class TestProjectCommand:
    def test_project_not_found(self, mock_db_path, capsys):
        with pytest.raises(SystemExit):
            main(["project", "nonexistent"])

    def test_project_shows_details(self, mock_db_path, capsys):
        db = PulseDB(mock_db_path)
        db.add_project(name="test", path="/tmp/test", total_tasks=5)
        main(["project", "test"])
        captured = capsys.readouterr()
        assert "test" in captured.out
        assert "0/5" in captured.out


class TestTaskCommand:
    def test_task_add(self, mock_db_path, capsys):
        db = PulseDB(mock_db_path)
        db.add_project(name="proj", path="/p")
        main(["task", "add", "proj", "vault.py"])
        tasks = db.get_tasks(db.get_project("proj")["id"])
        assert len(tasks) == 1
        assert tasks[0]["name"] == "vault.py"

    def test_task_done(self, mock_db_path, capsys):
        db = PulseDB(mock_db_path)
        pid = db.add_project(name="proj", path="/p", total_tasks=3)
        db.add_task(project_id=pid, name="vault.py")
        main(["task", "done", "proj", "vault.py"])
        tasks = db.get_tasks(pid)
        assert tasks[0]["status"] == "done"
        project = db.get_project("proj")
        assert project["completed_tasks"] == 1
