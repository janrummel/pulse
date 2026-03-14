"""Tests for pulse.planner — Deadline forecasts and priority ranking."""

import sys
from pathlib import Path

import pytest

from pulse.analyzer import Analyzer
from pulse.db import PulseDB
from pulse.planner import Planner

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from seed_demo_data import seed


@pytest.fixture
def planner(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = seed(db_path)
    analyzer = Analyzer(db)
    return Planner(db, analyzer)


@pytest.fixture
def empty_planner(tmp_path):
    db_path = str(tmp_path / "empty.db")
    db = PulseDB(db_path)
    analyzer = Analyzer(db)
    return Planner(db, analyzer)


class TestProjectForecast:
    def test_returns_forecast(self, planner):
        forecast = planner.project_forecast("watchdog")
        assert forecast is not None
        assert "remaining_tasks" in forecast
        assert "status" in forecast
        assert "recommendation" in forecast

    def test_remaining_tasks_correct(self, planner):
        forecast = planner.project_forecast("watchdog")
        assert forecast["remaining_tasks"] == 7  # 12 total - 5 done

    def test_status_is_valid(self, planner):
        forecast = planner.project_forecast("watchdog")
        assert forecast["status"] in ("on_track", "at_risk", "insufficient_data")

    def test_nonexistent_project(self, planner):
        forecast = planner.project_forecast("nonexistent")
        assert forecast is None

    def test_no_deadline_project(self, planner):
        forecast = planner.project_forecast("knowledge-factory")
        assert forecast is not None
        assert forecast["status"] == "no_deadline"

    def test_recommendation_is_string(self, planner):
        forecast = planner.project_forecast("watchdog")
        assert isinstance(forecast["recommendation"], str)
        assert len(forecast["recommendation"]) > 0


class TestPriorityRanking:
    def test_returns_list(self, planner):
        ranking = planner.priority_ranking()
        assert isinstance(ranking, list)
        assert len(ranking) > 0

    def test_sorted_by_urgency(self, planner):
        ranking = planner.priority_ranking()
        urgencies = [r["urgency"] for r in ranking]
        assert urgencies == sorted(urgencies, reverse=True)

    def test_each_entry_has_fields(self, planner):
        ranking = planner.priority_ranking()
        for entry in ranking:
            assert "project" in entry
            assert "urgency" in entry
            assert "reason" in entry

    def test_paused_projects_low_urgency(self, planner):
        ranking = planner.priority_ranking()
        paused = [r for r in ranking if r["project"]["status"] == "paused"]
        if paused:
            assert paused[0]["urgency"] <= 0.2

    def test_empty_db(self, empty_planner):
        ranking = empty_planner.priority_ranking()
        assert ranking == []
