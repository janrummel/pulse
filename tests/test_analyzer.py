"""Tests for pulse.analyzer — Metrics computation from collected events."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pulse.analyzer import Analyzer
from pulse.db import PulseDB

# Add scripts to path for seed function
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from seed_demo_data import seed


@pytest.fixture
def analyzer(tmp_path):
    """Analyzer with seeded demo data."""
    db_path = str(tmp_path / "test.db")
    db = seed(db_path)
    return Analyzer(db)


@pytest.fixture
def empty_analyzer(tmp_path):
    """Analyzer with empty database."""
    db_path = str(tmp_path / "empty.db")
    db = PulseDB(db_path)
    return Analyzer(db)


class TestToolMix:
    def test_returns_percentages(self, analyzer):
        mix = analyzer.tool_mix("/Users/jan/Projects/watchdog")
        assert "write_pct" in mix
        assert "edit_pct" in mix
        assert "bash_pct" in mix
        assert "read_pct" in mix
        assert "explore_pct" in mix

    def test_percentages_sum_to_roughly_100(self, analyzer):
        mix = analyzer.tool_mix("/Users/jan/Projects/watchdog")
        total = mix["write_pct"] + mix["edit_pct"] + mix["bash_pct"] + mix["read_pct"] + mix["explore_pct"] + mix["other_pct"]
        assert 99.0 <= total <= 101.0

    def test_empty_project(self, empty_analyzer):
        mix = empty_analyzer.tool_mix("/nonexistent")
        assert mix["total_tool_calls"] == 0

    def test_has_interpretation(self, analyzer):
        mix = analyzer.tool_mix("/Users/jan/Projects/watchdog")
        assert "interpretation" in mix
        assert isinstance(mix["interpretation"], str)


class TestDebugRatio:
    def test_returns_ratio(self, analyzer):
        result = analyzer.debug_ratio(project_path="/Users/jan/Projects/watchdog")
        assert "ratio" in result
        assert 0.0 <= result["ratio"] <= 1.0

    def test_has_debug_cycles(self, analyzer):
        result = analyzer.debug_ratio(project_path="/Users/jan/Projects/watchdog")
        assert "debug_cycles" in result
        assert result["debug_cycles"] >= 0

    def test_has_total_tool_calls(self, analyzer):
        result = analyzer.debug_ratio(project_path="/Users/jan/Projects/watchdog")
        assert result["total_tool_calls"] > 0

    def test_empty_returns_zero(self, empty_analyzer):
        result = empty_analyzer.debug_ratio(project_path="/nonexistent")
        assert result["ratio"] == 0.0
        assert result["debug_cycles"] == 0


class TestHumanWaitTime:
    def test_returns_wait_metrics(self, analyzer):
        sessions = analyzer.db.get_session_ids()
        result = analyzer.human_wait_time(session_id=sessions[0])
        assert "total_wait_seconds" in result
        assert "avg_wait_seconds" in result
        assert "wait_pct" in result

    def test_wait_time_positive(self, analyzer):
        sessions = analyzer.db.get_session_ids()
        result = analyzer.human_wait_time(session_id=sessions[0])
        assert result["total_wait_seconds"] >= 0

    def test_empty_session(self, empty_analyzer):
        result = empty_analyzer.human_wait_time(session_id="nonexistent")
        assert result["total_wait_seconds"] == 0.0


class TestSessionSummary:
    def test_returns_summary(self, analyzer):
        sessions = analyzer.db.get_session_ids()
        summary = analyzer.session_summary(sessions[0])
        assert "duration_minutes" in summary
        assert "prompts" in summary
        assert "tool_calls" in summary
        assert "debug_cycles" in summary
        assert "debug_ratio" in summary
        assert "human_wait_pct" in summary

    def test_nonexistent_session(self, empty_analyzer):
        summary = empty_analyzer.session_summary("nonexistent")
        assert summary["prompts"] == 0
        assert summary["tool_calls"] == 0


class TestProjectHealth:
    def test_returns_health(self, analyzer):
        health = analyzer.project_health("watchdog")
        assert "tasks_done" in health
        assert "tasks_total" in health
        assert "avg_debug_ratio" in health
        assert "total_session_hours" in health
        assert "trend" in health

    def test_tasks_count(self, analyzer):
        health = analyzer.project_health("watchdog")
        assert health["tasks_done"] == 5
        assert health["tasks_total"] == 12

    def test_nonexistent_project(self, empty_analyzer):
        health = empty_analyzer.project_health("nonexistent")
        assert health is None
