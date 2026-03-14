"""Pulse Launcher — Interactive command center for Claude Code projects.

Select a project, see its state, launch Claude with full context.
When Claude exits, return to the launcher.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from pulse.analyzer import Analyzer
from pulse.db import PulseDB

_DEFAULT_DB_PATH = str(Path.home() / ".pulse" / "pulse.db")
_ORCHESTRATOR_DIR = Path.home() / ".claude" / "orchestrator" / "projects"

_CAT_LABELS = {
    "tools": "Tools",
    "learning": "Learning",
    "system": "System",
    "research": "Research",
    "content": "Content",
    "career": "Career",
}

_STATUS_DOT = {"active": "●", "paused": "○", "done": "✓"}
_STATUS_STYLE = {"active": "green", "paused": "yellow", "done": "dim"}


def _load_project_context(project_name: str) -> str:
    """Load next steps from orchestrator project file."""
    # Try exact match first, then fuzzy
    candidates = [
        _ORCHESTRATOR_DIR / f"{project_name}.md",
        _ORCHESTRATOR_DIR / f"{project_name.replace('-', '_')}.md",
    ]
    for path in candidates:
        if path.exists():
            return _extract_next_steps(path)
    return ""


def _extract_next_steps(path: Path) -> str:
    """Extract open todos from an orchestrator project file."""
    text = path.read_text()
    lines = text.split("\n")
    in_todos = False
    todos = []

    for line in lines:
        if "Offene Todos" in line or "offene todos" in line.lower():
            in_todos = True
            continue
        if in_todos:
            if line.startswith("##") or line.startswith("# "):
                break
            stripped = line.strip()
            if stripped.startswith(("- [ ]", "1.", "2.", "3.", "4.", "5.")):
                # Clean up the line
                clean = stripped.lstrip("0123456789.-[] ").strip()
                if clean:
                    todos.append(clean)

    if not todos:
        return "Kein naechster Schritt definiert."
    return todos[0]


def _get_last_session_info(db: PulseDB, project_path: str) -> str:
    """Get info about the last session for this project."""
    events = db.execute(
        "SELECT timestamp FROM events WHERE project_path=? ORDER BY timestamp DESC LIMIT 1",
        (project_path,),
    ).fetchone()
    if not events:
        return "Noch keine Sessions"
    try:
        ts = datetime.fromisoformat(events["timestamp"])
        now = datetime.now()
        diff = now - ts
        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                return f"Vor {diff.seconds // 60} min"
            return f"Vor {hours}h"
        elif diff.days == 1:
            return "Gestern"
        else:
            return f"Vor {diff.days} Tagen"
    except (ValueError, TypeError):
        return "?"


class ProjectItem(ListItem):
    """A selectable project item in the list."""

    def __init__(self, project: dict, context: str, last_session: str) -> None:
        super().__init__()
        self.project = project
        self.context = context
        self.last_session = last_session

    def compose(self) -> ComposeResult:
        p = self.project
        status = p["status"]
        dot = _STATUS_DOT.get(status, "·")
        style = _STATUS_STYLE.get(status, "")
        name = p["name"]
        ptype = " ↻" if p.get("project_type") == "continuous" else ""

        # Progress
        done = p.get("completed_tasks") or 0
        total = p.get("total_tasks") or 0
        if total > 0 and status != "done":
            progress = f"  {done}/{total}"
        else:
            progress = ""

        yield Label(
            f" {dot}  {name}{ptype}{progress}",
            classes=f"project-{status}",
        )


class DetailPanel(Static):
    """Shows details for the selected project."""

    def update_project(self, project: dict, context: str, last_session: str) -> None:
        name = project["name"]
        status = project["status"]
        path = project["path"]
        cat = _CAT_LABELS.get(project.get("category", ""), "")

        lines = []
        lines.append(f"  {name}")
        lines.append(f"  {cat}  ·  {status}")
        lines.append(f"  {path}")
        lines.append("")
        lines.append(f"  Letzte Aktivitaet: {last_session}")
        lines.append("")
        lines.append(f"  Naechster Schritt:")
        lines.append(f"  → {context}")

        self.update("\n".join(lines))


class PulseLauncher(App):
    """Interactive project launcher."""

    CSS = """
    Screen {
        layout: horizontal;
    }

    #project-list {
        width: 40;
        border: solid $primary;
        border-title-color: $text;
    }

    #detail {
        width: 1fr;
        border: solid $secondary;
        border-title-color: $text;
        padding: 1;
    }

    ListItem {
        padding: 0 1;
    }

    ListItem.--highlight {
        background: $boost;
    }

    .project-active {
        color: $success;
    }

    .project-paused {
        color: $warning;
    }

    .project-done {
        color: $text-muted;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("r", "recap", "Recap"),
        Binding("p", "portfolio", "Portfolio"),
        Binding("q", "quit", "Beenden"),
    ]

    def __init__(self, db_path: str | None = None) -> None:
        super().__init__()
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db = PulseDB(self.db_path)
        self.projects_data: list[tuple[dict, str, str]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Load projects
        projects = self.db.execute(
            "SELECT * FROM projects WHERE status != 'done' "
            "ORDER BY category, name"
        ).fetchall()

        items = []
        for p in projects:
            p = dict(p)
            context = _load_project_context(p["name"])
            last = _get_last_session_info(self.db, p["path"])
            self.projects_data.append((p, context, last))
            items.append(ProjectItem(p, context, last))

        with Horizontal():
            yield ListView(*items, id="project-list")
            yield DetailPanel("  Projekt waehlen...", id="detail")

        yield Label(
            " [Enter] Claude starten  [r] Recap  [p] Portfolio  [q] Beenden",
            id="status-bar",
        )
        yield Footer()

    @on(ListView.Highlighted)
    def on_highlight(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, ProjectItem):
            detail = self.query_one("#detail", DetailPanel)
            detail.update_project(
                event.item.project,
                event.item.context,
                event.item.last_session,
            )
            detail.border_title = event.item.project["name"]

    @on(ListView.Selected)
    def on_selected(self, event: ListView.Selected) -> None:
        """Launch Claude when Enter is pressed on a project."""
        if event.item and isinstance(event.item, ProjectItem):
            self._launch_claude(event.item.project)

    def _launch_claude(self, project: dict) -> None:
        """Suspend the app, launch Claude, then resume."""
        project_path = project["path"]

        if not Path(project_path).exists():
            self.notify(f"Pfad existiert nicht: {project_path}", severity="error")
            return

        # Suspend Pulse TUI, launch Claude
        with self.suspend():
            print(f"\n  🫀 Pulse → Starte Claude in {project['name']}...")
            print(f"  Pfad: {project_path}")

            context = _load_project_context(project["name"])
            if context and context != "Kein naechster Schritt definiert.":
                print(f"  Naechster Schritt: {context}")

            print()

            next_step = _load_project_context(project["name"])
            prompt = f'Dein aktives Projekt ist {project["name"]}. '
            if next_step and next_step != "Kein naechster Schritt definiert.":
                prompt += f"Naechster Schritt: {next_step}"

            try:
                # Start Claude with project context as initial prompt
                subprocess.run(
                    ["claude", "--prompt", prompt],
                    cwd=project_path,
                )
            except FileNotFoundError:
                print("  'claude' nicht gefunden. Ist Claude Code installiert?")
                input("  [Enter] zurueck zu Pulse...")

        # Back to Pulse — refresh data
        self.db = PulseDB(self.db_path)

    def action_recap(self) -> None:
        """Show recap in a subprocess."""
        with self.suspend():
            subprocess.run(["pulse", "recap"])
            input("\n  [Enter] zurueck zu Pulse...")

    def action_portfolio(self) -> None:
        """Show full portfolio in a subprocess."""
        with self.suspend():
            subprocess.run(["pulse", "portfolio"])
            input("\n  [Enter] zurueck zu Pulse...")


def run_launcher(db_path: str | None = None) -> None:
    """Start the interactive launcher."""
    app = PulseLauncher(db_path)
    app.run()
