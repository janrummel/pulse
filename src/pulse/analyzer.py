"""Pulse analyzer — Computes metrics from collected hook events.

Provides: tool_mix, debug_ratio, human_wait_time, session_summary, project_health.
"""

from datetime import datetime

from pulse.db import PulseDB


class Analyzer:
    """Computes metrics from Pulse event data."""

    def __init__(self, db: PulseDB) -> None:
        self.db = db

    def tool_mix(self, project_path: str | None = None) -> dict:
        """Distribution of tool usage across a project."""
        if project_path:
            rows = self.db.execute(
                "SELECT tool_name, COUNT(*) as cnt FROM events "
                "WHERE project_path=? AND event_type='PreToolUse' AND tool_name IS NOT NULL "
                "GROUP BY tool_name",
                (project_path,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT tool_name, COUNT(*) as cnt FROM events "
                "WHERE event_type='PreToolUse' AND tool_name IS NOT NULL "
                "GROUP BY tool_name",
            ).fetchall()

        total = sum(r["cnt"] for r in rows)
        if total == 0:
            return {
                "write_pct": 0.0, "edit_pct": 0.0, "bash_pct": 0.0,
                "read_pct": 0.0, "explore_pct": 0.0, "other_pct": 0.0,
                "total_tool_calls": 0, "interpretation": "No data",
            }

        counts = {r["tool_name"]: r["cnt"] for r in rows}
        write = counts.get("Write", 0)
        edit = counts.get("Edit", 0)
        bash = counts.get("Bash", 0)
        read = counts.get("Read", 0)
        explore = counts.get("Glob", 0) + counts.get("Grep", 0)
        other = total - write - edit - bash - read - explore

        pct = lambda n: round(n / total * 100, 1)

        # Interpretation
        bash_pct = bash / total
        write_pct = write / total
        edit_pct = edit / total
        if bash_pct > 0.35:
            interpretation = "Viel Bash = Debug/Test-Phase"
        elif write_pct > 0.3:
            interpretation = "Viel Write = aktive Entwicklung"
        elif edit_pct > 0.3:
            interpretation = "Viel Edit = Refactoring/Anpassung"
        else:
            interpretation = "Ausgewogener Mix"

        return {
            "write_pct": pct(write),
            "edit_pct": pct(edit),
            "bash_pct": pct(bash),
            "read_pct": pct(read),
            "explore_pct": pct(explore),
            "other_pct": pct(other),
            "total_tool_calls": total,
            "interpretation": interpretation,
        }

    def debug_ratio(
        self,
        session_id: str | None = None,
        project_path: str | None = None,
    ) -> dict:
        """Fraction of tool calls that are part of debug cycles.

        A debug cycle: PostToolUse with failure, followed by PreToolUse
        on the same resource within the next 3 events.
        """
        if session_id:
            events = self.db.get_events_by_session(session_id)
        elif project_path:
            events = self.db.get_events_by_project(project_path)
        else:
            events = []

        tool_events = [e for e in events if e["event_type"] in ("PreToolUse", "PostToolUse")]
        total = len([e for e in events if e["event_type"] == "PreToolUse"])

        if total == 0:
            return {
                "ratio": 0.0,
                "total_tool_calls": 0,
                "debug_cycles": 0,
                "worst_file": None,
            }

        cycles = self._detect_debug_cycles(tool_events)

        # Find worst file
        file_counts: dict[str, int] = {}
        for cycle in cycles:
            f = cycle.get("file")
            if f:
                file_counts[f] = file_counts.get(f, 0) + 1
        worst = max(file_counts, key=file_counts.get) if file_counts else None

        return {
            "ratio": round(len(cycles) / total, 3) if total else 0.0,
            "total_tool_calls": total,
            "debug_cycles": len(cycles),
            "worst_file": worst,
        }

    def _detect_debug_cycles(self, tool_events: list[dict]) -> list[dict]:
        """Detect debug cycles from tool event sequence.

        A debug cycle is:
        1. PostToolUse with failure (tool_output_success == 0/False)
        2. Followed by PreToolUse on the same file within next 3 events
        """
        cycles = []
        for i, event in enumerate(tool_events):
            if event["event_type"] != "PostToolUse":
                continue
            if event["tool_output_success"] not in (0, False):
                continue

            trigger_file = self._extract_file(event)
            lookahead = tool_events[i + 1: i + 4]
            for ne in lookahead:
                if ne["event_type"] == "PreToolUse":
                    fix_file = self._extract_file(ne)
                    if trigger_file and fix_file and trigger_file == fix_file:
                        cycles.append({
                            "trigger_event": event,
                            "fix_event": ne,
                            "file": trigger_file,
                        })
                        break
                    # Also match: bash failure followed by edit on any file
                    if event.get("tool_name") == "Bash" and ne.get("tool_name") in ("Edit", "Write"):
                        cycles.append({
                            "trigger_event": event,
                            "fix_event": ne,
                            "file": fix_file,
                        })
                        break
        return cycles

    @staticmethod
    def _extract_file(event: dict) -> str | None:
        """Extract file path from tool_input_summary."""
        summary = event.get("tool_input_summary", "") or ""
        if summary.startswith("file: "):
            return summary[6:]
        return None

    def human_wait_time(self, session_id: str) -> dict:
        """Time the agent spent waiting for human input.

        Measured as time between Stop events and the next UserPromptSubmit.
        """
        events = self.db.get_events_by_session(session_id)
        if not events:
            return {
                "total_wait_seconds": 0.0,
                "avg_wait_seconds": 0.0,
                "wait_pct": 0.0,
                "longest_wait_seconds": 0.0,
            }

        waits = []
        for i, event in enumerate(events):
            if event["event_type"] != "Stop":
                continue
            # Find next UserPromptSubmit
            for ne in events[i + 1:]:
                if ne["event_type"] == "UserPromptSubmit":
                    stop_time = datetime.fromisoformat(event["timestamp"])
                    prompt_time = datetime.fromisoformat(ne["timestamp"])
                    wait = (prompt_time - stop_time).total_seconds()
                    if wait > 0:
                        waits.append(wait)
                    break

        total_wait = sum(waits)
        # Calculate total session time
        first = datetime.fromisoformat(events[0]["timestamp"])
        last = datetime.fromisoformat(events[-1]["timestamp"])
        total_session = (last - first).total_seconds()

        return {
            "total_wait_seconds": round(total_wait, 1),
            "avg_wait_seconds": round(total_wait / len(waits), 1) if waits else 0.0,
            "wait_pct": round(total_wait / total_session * 100, 1) if total_session > 0 else 0.0,
            "longest_wait_seconds": round(max(waits), 1) if waits else 0.0,
        }

    def session_summary(self, session_id: str) -> dict:
        """Summary of a single session."""
        events = self.db.get_events_by_session(session_id)
        if not events:
            return {
                "duration_minutes": 0.0,
                "prompts": 0,
                "tool_calls": 0,
                "debug_cycles": 0,
                "files_touched": [],
                "debug_ratio": 0.0,
                "human_wait_pct": 0.0,
                "model": None,
            }

        first = datetime.fromisoformat(events[0]["timestamp"])
        last = datetime.fromisoformat(events[-1]["timestamp"])
        duration = (last - first).total_seconds() / 60

        prompts = len([e for e in events if e["event_type"] == "UserPromptSubmit"])
        tool_calls = len([e for e in events if e["event_type"] == "PreToolUse"])

        tool_events = [e for e in events if e["event_type"] in ("PreToolUse", "PostToolUse")]
        debug_cycles = len(self._detect_debug_cycles(tool_events))

        files = set()
        for e in events:
            f = self._extract_file(e)
            if f:
                files.add(f)

        wait = self.human_wait_time(session_id)
        dr = self.debug_ratio(session_id=session_id)

        model = None
        for e in events:
            if e.get("model"):
                model = e["model"]
                break

        return {
            "duration_minutes": round(duration, 1),
            "prompts": prompts,
            "tool_calls": tool_calls,
            "debug_cycles": debug_cycles,
            "files_touched": sorted(files),
            "debug_ratio": dr["ratio"],
            "human_wait_pct": wait["wait_pct"],
            "model": model,
        }

    def project_health(self, project_name: str) -> dict | None:
        """Overall health status of a project."""
        project = self.db.get_project(project_name)
        if not project:
            return None

        tasks = self.db.get_tasks(project["id"])
        done = len([t for t in tasks if t["status"] == "done"])
        total = len(tasks) if tasks else (project["total_tasks"] or 0)

        sessions = self.db.get_recent_sessions(project["path"], limit=20)
        total_hours = sum(
            (s["duration_seconds"] or 0) / 3600 for s in sessions
        )

        # Average debug ratio across sessions
        debug_ratios = []
        for s in sessions:
            dr = self.debug_ratio(session_id=s["session_id"])
            if dr["total_tool_calls"] > 0:
                debug_ratios.append(dr["ratio"])
        avg_dr = sum(debug_ratios) / len(debug_ratios) if debug_ratios else 0.0

        # Trend: compare last 2 sessions velocity
        trend = "stable"
        if len(sessions) >= 2:
            recent_calls = sessions[0]["tool_call_count"] or 0
            prev_calls = sessions[1]["tool_call_count"] or 0
            if recent_calls > prev_calls * 1.2:
                trend = "accelerating"
            elif recent_calls < prev_calls * 0.8:
                trend = "slowing"

        return {
            "tasks_done": done,
            "tasks_total": total,
            "avg_debug_ratio": round(avg_dr, 3),
            "total_session_hours": round(total_hours, 1),
            "last_session": sessions[0]["started_at"] if sessions else None,
            "trend": trend,
        }
