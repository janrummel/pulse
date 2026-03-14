"""Pulse planner — Deadline forecasts and priority ranking.

Uses historical metrics from Analyzer to predict project completion
and recommend next actions.
"""

from datetime import datetime

from pulse.analyzer import Analyzer
from pulse.db import PulseDB


class Planner:
    """Computes forecasts and priorities based on historical metrics."""

    def __init__(self, db: PulseDB, analyzer: Analyzer) -> None:
        self.db = db
        self.analyzer = analyzer

    def project_forecast(self, project_name: str) -> dict | None:
        """Forecast whether a project will hit its deadline."""
        project = self.db.get_project(project_name)
        if not project:
            return None

        health = self.analyzer.project_health(project_name)
        if not health:
            return {"status": "insufficient_data", "recommendation": "Nicht genug Daten."}

        tasks_done = health["tasks_done"]
        tasks_total = health["tasks_total"]
        remaining = tasks_total - tasks_done

        if not project["deadline"]:
            return {
                "remaining_tasks": remaining,
                "estimated_hours": None,
                "available_hours": None,
                "buffer_hours": None,
                "status": "no_deadline",
                "recommendation": self._recommend_no_deadline(remaining, tasks_total),
            }

        # Calculate velocity from task data
        tasks = self.db.get_tasks(project["id"])
        done_tasks = [t for t in tasks if t["status"] == "done" and t.get("actual_minutes")]
        if done_tasks:
            avg_minutes_per_task = sum(t["actual_minutes"] for t in done_tasks) / len(done_tasks)
        elif health["total_session_hours"] > 0 and tasks_done > 0:
            avg_minutes_per_task = (health["total_session_hours"] * 60) / tasks_done
        else:
            return {
                "remaining_tasks": remaining,
                "estimated_hours": None,
                "available_hours": self._hours_until(project["deadline"]),
                "buffer_hours": None,
                "status": "insufficient_data",
                "recommendation": "Nicht genug Daten fuer Prognose. Mindestens 3 Tasks abschliessen.",
            }

        # Apply debug overhead
        debug_overhead = 1.0 + health["avg_debug_ratio"]
        estimated_minutes = remaining * avg_minutes_per_task * debug_overhead
        estimated_hours = estimated_minutes / 60

        available_hours = self._hours_until(project["deadline"])
        buffer_hours = available_hours - estimated_hours

        if buffer_hours > 0:
            status = "on_track"
        else:
            status = "at_risk"

        return {
            "remaining_tasks": remaining,
            "estimated_hours": round(estimated_hours, 1),
            "available_hours": round(available_hours, 1),
            "buffer_hours": round(buffer_hours, 1),
            "status": status,
            "recommendation": self._recommend(buffer_hours, remaining),
        }

    def priority_ranking(self) -> list[dict]:
        """Rank active projects by urgency."""
        projects = self.db.execute(
            "SELECT * FROM projects ORDER BY name"
        ).fetchall()

        if not projects:
            return []

        priorities = []
        for p in projects:
            p = dict(p)
            if p["status"] == "paused":
                priorities.append({
                    "project": p,
                    "urgency": 0.1,
                    "reason": "Pausiert — keine Aktion noetig.",
                })
                continue
            if p["status"] == "done":
                continue

            forecast = self.project_forecast(p["name"])
            urgency = self._calculate_urgency(p, forecast)
            reason = self._urgency_reason(p, forecast)
            priorities.append({
                "project": p,
                "forecast": forecast,
                "urgency": urgency,
                "reason": reason,
            })

        return sorted(priorities, key=lambda x: x["urgency"], reverse=True)

    def _calculate_urgency(self, project: dict, forecast: dict | None) -> float:
        """Urgency score: 0.0 (relaxed) to 1.0 (critical)."""
        if not project.get("deadline"):
            return 0.3

        if not forecast:
            return 0.5

        if forecast["status"] == "at_risk":
            return 0.9

        if forecast["status"] == "insufficient_data":
            return 0.5

        buffer = forecast.get("buffer_hours")
        if buffer is None:
            return 0.5
        if buffer < 2:
            return 0.8
        elif buffer < 5:
            return 0.6
        else:
            return 0.4

    def _urgency_reason(self, project: dict, forecast: dict | None) -> str:
        """Human-readable urgency explanation."""
        if not forecast:
            return "Keine Daten verfuegbar."

        status = forecast.get("status", "unknown")
        remaining = forecast.get("remaining_tasks", "?")

        if status == "at_risk":
            return f"Hinter Plan. {remaining} Tasks offen, Puffer aufgebraucht."
        elif status == "on_track":
            buffer = forecast.get("buffer_hours", 0)
            return f"{remaining} Tasks offen, {buffer:.1f}h Puffer."
        elif status == "no_deadline":
            return f"{remaining} Tasks offen, kein Deadline gesetzt."
        else:
            return f"{remaining} Tasks offen, nicht genug Daten fuer Prognose."

    @staticmethod
    def _hours_until(deadline_str: str) -> float:
        """Hours from now until a deadline."""
        deadline = datetime.fromisoformat(deadline_str)
        now = datetime.now()
        diff = (deadline - now).total_seconds() / 3600
        return max(0.0, diff)

    @staticmethod
    def _recommend(buffer: float, remaining: int) -> str:
        """Generate recommendation based on buffer and remaining tasks."""
        if remaining == 0:
            return "Alle Tasks erledigt."
        if buffer > remaining * 0.5:
            return "Komfortabler Puffer. Weiter wie bisher."
        elif buffer > 0:
            return "Knapp. Fokus auf kritische Tasks, Nice-to-haves streichen."
        elif buffer > -2:
            return "Hinter Plan. Scope reduzieren — welche Tasks koennen entfallen?"
        else:
            return "Deutlich hinter Plan. Deadline verschieben oder Scope drastisch kuerzen."

    @staticmethod
    def _recommend_no_deadline(remaining: int, total: int) -> str:
        if remaining == 0:
            return "Alle Tasks erledigt."
        pct = (total - remaining) / total * 100 if total > 0 else 0
        return f"{pct:.0f}% erledigt, {remaining} Tasks offen. Kein Zeitdruck."
