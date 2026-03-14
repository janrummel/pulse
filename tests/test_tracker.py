"""Tests for pulse.tracker — Automatic task completion detection from events."""

from datetime import datetime, timedelta

import pytest

from pulse.db import PulseDB
from pulse.tracker import TaskTracker, TaskSignal


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    db = PulseDB(str(db_path))
    pid = db.add_project(name="watchdog", path="/Users/jan/Projects/watchdog", total_tasks=5)
    db.add_task(project_id=pid, name="vault.py")
    db.add_task(project_id=pid, name="scanner.py")
    db.add_task(project_id=pid, name="proxy.py")
    db.add_task(project_id=pid, name="tests")
    db.add_task(project_id=pid, name="cli.py")
    return db


@pytest.fixture
def tracker(db):
    return TaskTracker(db)


def _insert_events(db, session_id, project_path, events_spec):
    """Insert a sequence of events. Each spec is (offset_seconds, event_type, extras)."""
    base = datetime(2026, 3, 14, 14, 0, 0)
    for offset, event_type, extras in events_spec:
        db.insert_event({
            "timestamp": (base + timedelta(seconds=offset)).isoformat(),
            "session_id": session_id,
            "event_type": event_type,
            "project_path": project_path,
            "model": None,
            "tool_name": extras.get("tool_name"),
            "tool_input_summary": extras.get("tool_input_summary"),
            "tool_use_id": extras.get("tool_use_id"),
            "tool_output_success": extras.get("tool_output_success"),
            "prompt_text": extras.get("prompt_text"),
            "raw_json": "{}",
        })


class TestCommitDetection:
    def test_detects_commit_mentioning_task(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py + tests fertig"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        task_names = [s.task_name for s in signals]
        assert "vault.py" in task_names

    def test_commit_with_multiple_tasks(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "scanner.py und proxy.py implementiert"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        task_names = [s.task_name for s in signals]
        assert "scanner.py" in task_names
        assert "proxy.py" in task_names

    def test_failed_commit_ignored(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py done"',
                "tool_output_success": False,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert len(signals) == 0

    def test_no_match_returns_empty(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "refactored imports"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert len(signals) == 0


class TestWriteTestPattern:
    def test_detects_write_then_test_success(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Write",
                "tool_input_summary": "file: src/vault.py",
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
            (10, "PostToolUse", {
                "tool_name": "Write",
                "tool_input_summary": "file: tests/test_vault.py",
                "tool_output_success": True,
                "tool_use_id": "tu_2",
            }),
            (20, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": "bash: python3 -m pytest tests/test_vault.py -v",
                "tool_output_success": True,
                "tool_use_id": "tu_3",
            }),
        ])
        signals = tracker.detect_signals("s1")
        task_names = [s.task_name for s in signals]
        assert "vault.py" in task_names

    def test_write_then_test_fail_no_signal(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Write",
                "tool_input_summary": "file: src/vault.py",
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
            (10, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": "bash: pytest",
                "tool_output_success": False,
                "tool_use_id": "tu_2",
            }),
        ])
        signals = tracker.detect_signals("s1")
        # Should not signal task completion on failed tests
        commit_signals = [s for s in signals if s.signal_type == "write_test_success"]
        assert len(commit_signals) == 0


class TestPromptTransition:
    def test_detects_topic_switch(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "UserPromptSubmit", {
                "prompt_text": "Baue vault.py mit Tests",
            }),
            (60, "PostToolUse", {
                "tool_name": "Write",
                "tool_input_summary": "file: src/vault.py",
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
            (120, "UserPromptSubmit", {
                "prompt_text": "Jetzt scanner.py mit den Patterns",
            }),
        ])
        signals = tracker.detect_signals("s1")
        task_names = [s.task_name for s in signals]
        # vault.py should be signaled as likely done when user moves to scanner.py
        assert "vault.py" in task_names

    def test_no_signal_on_first_prompt(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "UserPromptSubmit", {
                "prompt_text": "Baue vault.py mit Tests",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert len(signals) == 0


class TestSignalProperties:
    def test_signal_has_confidence(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py fertig"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert len(signals) > 0
        assert 0.0 <= signals[0].confidence <= 1.0

    def test_commit_has_highest_confidence(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py done"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert signals[0].confidence >= 0.8

    def test_signal_has_type(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        assert signals[0].signal_type == "commit_mention"

    def test_only_pending_tasks_signaled(self, tracker, db):
        """Tasks already marked done should not be signaled again."""
        project = db.get_project("watchdog")
        tasks = db.get_tasks(project["id"])
        vault_task = [t for t in tasks if t["name"] == "vault.py"][0]
        db.update_task(vault_task["id"], status="done")

        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py updates"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        task_names = [s.task_name for s in signals]
        assert "vault.py" not in task_names


class TestApplySignals:
    def test_apply_marks_task_done(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "PostToolUse", {
                "tool_name": "Bash",
                "tool_input_summary": 'bash: git commit -m "vault.py fertig"',
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
        ])
        signals = tracker.detect_signals("s1")
        applied = tracker.apply_signals(signals, min_confidence=0.7)
        assert len(applied) > 0

        project = db.get_project("watchdog")
        tasks = db.get_tasks(project["id"])
        vault = [t for t in tasks if t["name"] == "vault.py"][0]
        assert vault["status"] == "done"

    def test_low_confidence_not_applied(self, tracker, db):
        _insert_events(db, "s1", "/Users/jan/Projects/watchdog", [
            (0, "UserPromptSubmit", {"prompt_text": "Baue vault.py"}),
            (60, "PostToolUse", {
                "tool_name": "Write",
                "tool_input_summary": "file: src/vault.py",
                "tool_output_success": True,
                "tool_use_id": "tu_1",
            }),
            (120, "UserPromptSubmit", {"prompt_text": "Jetzt scanner.py"}),
        ])
        signals = tracker.detect_signals("s1")
        applied = tracker.apply_signals(signals, min_confidence=0.9)
        # Prompt transitions have lower confidence, should not auto-apply at 0.9
        prompt_applied = [a for a in applied if a.signal_type == "prompt_transition"]
        assert len(prompt_applied) == 0
