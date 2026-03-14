"""Pulse tracker — Automatic task completion detection from hook events.

Detects three signal types:
1. commit_mention: Git commit message mentions a task name (confidence: 0.9)
2. write_test_success: Write to file + passing tests (confidence: 0.7)
3. prompt_transition: User moves to next topic (confidence: 0.5)

Signals are suggestions, not certainties. apply_signals() respects
a min_confidence threshold to avoid false positives.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pulse.db import PulseDB


@dataclass
class TaskSignal:
    """A detected signal that a task may be completed."""
    task_name: str
    task_id: int
    project_name: str
    signal_type: str  # commit_mention | write_test_success | prompt_transition
    confidence: float  # 0.0 - 1.0
    evidence: str  # Human-readable explanation
    timestamp: str


class TaskTracker:
    """Detects task completion from hook event patterns."""

    def __init__(self, db: PulseDB) -> None:
        self.db = db

    def detect_signals(self, session_id: str) -> list[TaskSignal]:
        """Analyze a session's events and return task completion signals."""
        events = self.db.get_events_by_session(session_id)
        if not events:
            return []

        # Determine project from events
        project_path = events[0].get("project_path")
        if not project_path:
            return []

        # Find matching project and its pending tasks
        project = self._find_project_by_path(project_path)
        if not project:
            return []

        pending_tasks = self._get_pending_tasks(project["id"])
        if not pending_tasks:
            return []

        signals = []
        signals.extend(self._detect_commit_mentions(events, pending_tasks, project["name"]))
        signals.extend(self._detect_write_test_success(events, pending_tasks, project["name"]))
        signals.extend(self._detect_prompt_transitions(events, pending_tasks, project["name"]))

        # Deduplicate: keep highest confidence per task
        best: dict[str, TaskSignal] = {}
        for s in signals:
            if s.task_name not in best or s.confidence > best[s.task_name].confidence:
                best[s.task_name] = s

        return sorted(best.values(), key=lambda s: s.confidence, reverse=True)

    def apply_signals(
        self,
        signals: list[TaskSignal],
        min_confidence: float = 0.7,
    ) -> list[TaskSignal]:
        """Apply signals above the confidence threshold — mark tasks as done."""
        applied = []
        for signal in signals:
            if signal.confidence < min_confidence:
                continue

            self.db.update_task(
                signal.task_id,
                status="done",
                completed_at=signal.timestamp,
            )

            # Update project completed count
            project = self.db.get_project(signal.project_name)
            if project:
                tasks = self.db.get_tasks(project["id"])
                done_count = len([t for t in tasks if t["status"] == "done"])
                self.db.update_project(signal.project_name, completed_tasks=done_count)

            applied.append(signal)

        return applied

    def _detect_commit_mentions(
        self,
        events: list[dict],
        pending_tasks: list[dict],
        project_name: str,
    ) -> list[TaskSignal]:
        """Detect git commits that mention task names."""
        signals = []
        for event in events:
            if event["event_type"] != "PostToolUse":
                continue
            if event.get("tool_name") != "Bash":
                continue
            if event.get("tool_output_success") in (0, False):
                continue

            summary = event.get("tool_input_summary", "") or ""
            if "git commit" not in summary:
                continue

            # Extract commit message (after -m)
            commit_msg = summary.lower()

            for task in pending_tasks:
                task_name_lower = task["name"].lower()
                # Match task name in commit message
                if task_name_lower in commit_msg:
                    signals.append(TaskSignal(
                        task_name=task["name"],
                        task_id=task["id"],
                        project_name=project_name,
                        signal_type="commit_mention",
                        confidence=0.9,
                        evidence=f"Git commit erwaehnt '{task['name']}': {summary[:100]}",
                        timestamp=event["timestamp"],
                    ))

        return signals

    def _detect_write_test_success(
        self,
        events: list[dict],
        pending_tasks: list[dict],
        project_name: str,
    ) -> list[TaskSignal]:
        """Detect pattern: Write to file + test passes → task likely done."""
        signals = []

        # Collect files written in this session
        written_files: dict[str, str] = {}  # basename → timestamp
        last_test_success: str | None = None
        last_test_timestamp: str | None = None

        for event in events:
            if event["event_type"] != "PostToolUse":
                continue
            if event.get("tool_output_success") in (0, False, None):
                continue

            tool = event.get("tool_name", "")
            summary = event.get("tool_input_summary", "") or ""

            if tool in ("Write", "Edit") and summary.startswith("file: "):
                filepath = summary[6:]
                basename = Path(filepath).stem
                written_files[basename] = event["timestamp"]

            if tool == "Bash" and ("pytest" in summary or "test" in summary):
                last_test_success = summary
                last_test_timestamp = event["timestamp"]

        if not last_test_success:
            return signals

        # Match written files against task names
        for task in pending_tasks:
            task_stem = Path(task["name"]).stem.lower()
            for basename, write_ts in written_files.items():
                if task_stem == basename.lower() or task_stem in basename.lower():
                    signals.append(TaskSignal(
                        task_name=task["name"],
                        task_id=task["id"],
                        project_name=project_name,
                        signal_type="write_test_success",
                        confidence=0.7,
                        evidence=f"Write {basename} + Tests gruen",
                        timestamp=last_test_timestamp or write_ts,
                    ))

        return signals

    def _detect_prompt_transitions(
        self,
        events: list[dict],
        pending_tasks: list[dict],
        project_name: str,
    ) -> list[TaskSignal]:
        """Detect when user moves to a new topic, implying previous is done."""
        signals = []
        prompts = [e for e in events if e["event_type"] == "UserPromptSubmit"]

        if len(prompts) < 2:
            return signals

        for i in range(1, len(prompts)):
            prev_prompt = (prompts[i - 1].get("prompt_text") or "").lower()
            curr_prompt = (prompts[i].get("prompt_text") or "").lower()

            # Check if previous prompt mentioned a task
            for task in pending_tasks:
                task_name_lower = task["name"].lower()
                task_stem = Path(task["name"]).stem.lower()

                prev_mentions = task_name_lower in prev_prompt or task_stem in prev_prompt
                curr_mentions = task_name_lower in curr_prompt or task_stem in curr_prompt

                # Previous prompt mentioned this task, current doesn't → transition
                if prev_mentions and not curr_mentions:
                    # Check if work was done between the two prompts
                    work_done = any(
                        e["event_type"] == "PostToolUse"
                        and e.get("tool_name") in ("Write", "Edit")
                        and e["timestamp"] > prompts[i - 1]["timestamp"]
                        and e["timestamp"] < prompts[i]["timestamp"]
                        for e in events
                    )
                    if work_done:
                        signals.append(TaskSignal(
                            task_name=task["name"],
                            task_id=task["id"],
                            project_name=project_name,
                            signal_type="prompt_transition",
                            confidence=0.5,
                            evidence=f"User wechselt von '{task['name']}' zu neuem Thema",
                            timestamp=prompts[i]["timestamp"],
                        ))

        return signals

    def _find_project_by_path(self, path: str) -> dict | None:
        """Find a project whose path matches the event's project_path."""
        row = self.db.execute(
            "SELECT * FROM projects WHERE path=?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def _get_pending_tasks(self, project_id: int) -> list[dict]:
        """Get tasks that are not yet done."""
        tasks = self.db.get_tasks(project_id)
        return [t for t in tasks if t["status"] != "done"]
