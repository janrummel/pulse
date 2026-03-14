"""Tests for pulse.collector — Hook event handler that reads JSON from stdin and writes to DB."""

import json
from datetime import datetime
from io import StringIO
from unittest.mock import patch

import pytest

from pulse.collector import collect, _summarize_input, _check_success
from pulse.db import PulseDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_pulse.db"
    return PulseDB(str(db_path))


def _make_hook_payload(
    event_type: str,
    session_id: str = "sess_test_001",
    cwd: str = "/tmp/projects/example-app",
    **extra,
) -> dict:
    """Build a realistic hook payload."""
    base = {
        "session_id": session_id,
        "transcript_path": "/tmp/transcript.json",
        "cwd": cwd,
        "permission_mode": "default",
        "hook_event_name": event_type,
    }
    base.update(extra)
    return base


class TestSummarizeInput:
    def test_bash_command(self):
        result = _summarize_input({"command": "pytest tests/ -v", "description": "Run tests"})
        assert result == "bash: pytest tests/ -v"

    def test_file_path(self):
        result = _summarize_input({"file_path": "/src/vault.py"})
        assert result == "file: /src/vault.py"

    def test_pattern(self):
        result = _summarize_input({"pattern": "**/*.py"})
        assert "**/*.py" in result

    def test_long_command_truncated(self):
        long_cmd = "x" * 300
        result = _summarize_input({"command": long_cmd})
        assert len(result) <= 210  # "bash: " + 200 chars

    def test_empty_input(self):
        result = _summarize_input({})
        assert result is None

    def test_prompt_field(self):
        result = _summarize_input({"prompt": "Build vault.py with tests"})
        assert "Build vault.py" in result


class TestCheckSuccess:
    def test_non_post_tool_use_returns_none(self):
        payload = _make_hook_payload("PreToolUse", tool_name="Write")
        assert _check_success(payload) is None

    def test_session_start_returns_none(self):
        payload = _make_hook_payload("SessionStart")
        assert _check_success(payload) is None

    def test_successful_tool_response(self):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Write",
            tool_response={"content": "File written successfully"},
        )
        assert _check_success(payload) is True

    def test_error_in_response(self):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Bash",
            tool_response={"content": "Error: ModuleNotFoundError: No module named 'foo'"},
        )
        assert _check_success(payload) is False

    def test_traceback_detected(self):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Bash",
            tool_response={"content": "Traceback (most recent call last):\n  File..."},
        )
        assert _check_success(payload) is False

    def test_failed_test_detected(self):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Bash",
            tool_response={"content": "FAILED tests/test_foo.py::test_bar - AssertionError"},
        )
        assert _check_success(payload) is False


class TestCollect:
    def test_session_start(self, db, tmp_path):
        payload = _make_hook_payload(
            "SessionStart",
            model="claude-opus-4-6",
            source="startup",
        )
        collect(
            stdin_data=json.dumps(payload),
            event_type="SessionStart",
            db=db,
        )
        events = db.get_events_by_session("sess_test_001")
        assert len(events) == 1
        assert events[0]["event_type"] == "SessionStart"
        assert events[0]["model"] == "claude-opus-4-6"
        assert events[0]["project_path"] == "/tmp/projects/example-app"

    def test_session_start_creates_session_record(self, db):
        payload = _make_hook_payload(
            "SessionStart",
            model="claude-opus-4-6",
        )
        collect(stdin_data=json.dumps(payload), event_type="SessionStart", db=db)
        session = db.get_session("sess_test_001")
        assert session is not None
        assert session["model"] == "claude-opus-4-6"

    def test_pre_tool_use(self, db):
        payload = _make_hook_payload(
            "PreToolUse",
            tool_name="Write",
            tool_input={"file_path": "/src/vault.py", "content": "..."},
            tool_use_id="tu_001",
        )
        collect(stdin_data=json.dumps(payload), event_type="PreToolUse", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert len(events) == 1
        assert events[0]["tool_name"] == "Write"
        assert events[0]["tool_use_id"] == "tu_001"
        assert events[0]["tool_input_summary"] == "file: /src/vault.py"

    def test_post_tool_use_success(self, db):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Write",
            tool_input={"file_path": "/src/vault.py"},
            tool_response={"content": "File written"},
            tool_use_id="tu_001",
        )
        collect(stdin_data=json.dumps(payload), event_type="PostToolUse", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert events[0]["tool_output_success"] == 1  # SQLite stores bool as int

    def test_post_tool_use_failure(self, db):
        payload = _make_hook_payload(
            "PostToolUse",
            tool_name="Bash",
            tool_input={"command": "pytest"},
            tool_response={"content": "FAILED 2 tests"},
            tool_use_id="tu_002",
        )
        collect(stdin_data=json.dumps(payload), event_type="PostToolUse", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert events[0]["tool_output_success"] == 0  # SQLite stores bool as int

    def test_user_prompt_submit(self, db):
        payload = _make_hook_payload(
            "UserPromptSubmit",
            prompt="Baue vault.py mit Tests",
        )
        collect(stdin_data=json.dumps(payload), event_type="UserPromptSubmit", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert events[0]["prompt_text"] == "Baue vault.py mit Tests"

    def test_prompt_text_truncated(self, db):
        long_prompt = "x" * 1000
        payload = _make_hook_payload("UserPromptSubmit", prompt=long_prompt)
        collect(stdin_data=json.dumps(payload), event_type="UserPromptSubmit", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert len(events[0]["prompt_text"]) <= 500

    def test_stop_event(self, db):
        payload = _make_hook_payload(
            "Stop",
            stop_hook_active=True,
            last_assistant_message="Done.",
        )
        collect(stdin_data=json.dumps(payload), event_type="Stop", db=db)
        events = db.get_events_by_session("sess_test_001")
        assert events[0]["event_type"] == "Stop"

    def test_raw_json_stored(self, db):
        payload = _make_hook_payload("SessionStart", model="opus")
        collect(stdin_data=json.dumps(payload), event_type="SessionStart", db=db)
        events = db.get_events_by_session("sess_test_001")
        raw = json.loads(events[0]["raw_json"])
        assert raw["session_id"] == "sess_test_001"

    def test_multiple_events_same_session(self, db):
        for event_type in ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]:
            extra = {}
            if event_type == "SessionStart":
                extra = {"model": "opus"}
            elif event_type == "UserPromptSubmit":
                extra = {"prompt": "do stuff"}
            elif event_type in ("PreToolUse", "PostToolUse"):
                extra = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "tu_1"}
            if event_type == "PostToolUse":
                extra["tool_response"] = {"content": "ok"}
            payload = _make_hook_payload(event_type, **extra)
            collect(stdin_data=json.dumps(payload), event_type=event_type, db=db)

        events = db.get_events_by_session("sess_test_001")
        assert len(events) == 5

    def test_no_secrets_in_tool_input_summary(self, db):
        """Ensure we don't log file content, only the path."""
        payload = _make_hook_payload(
            "PreToolUse",
            tool_name="Write",
            tool_input={
                "file_path": "/src/.env",
                "content": "API_KEY=sk-secret-12345",
            },
            tool_use_id="tu_sec",
        )
        collect(stdin_data=json.dumps(payload), event_type="PreToolUse", db=db)
        events = db.get_events_by_session("sess_test_001")
        summary = events[0]["tool_input_summary"]
        assert "sk-secret" not in summary
        assert "file: /src/.env" == summary
