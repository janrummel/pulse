"""Pulse App — Unified Textual TUI with tabbed navigation.

One app, multiple views, consistent navigation everywhere.
[1] Launcher  [2] Dashboard  [3] Recap  [4] Portfolio  [q] Beenden
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from pulse.analyzer import Analyzer
from pulse.db import PulseDB
from pulse.planner import Planner
from pulse.sync import get_next_step, sync_all
from pulse import theme

from pulse.config import config as _cfg

_DEFAULT_DB_PATH = _cfg.db_path


# ── Project List Item ──────────────────────────────────────────────

class ProjectItem(ListItem):
    def __init__(self, project: dict, context: str, last_info: str) -> None:
        super().__init__()
        self.project = project
        self.context = context
        self.last_info = last_info

    def compose(self) -> ComposeResult:
        p = self.project
        dot = theme.STATUS_DOT.get(p["status"], "·")
        cont = " ↻" if p.get("project_type") == "continuous" else ""
        yield Label(f" {dot}  {p['name']}{cont}")


# ── Views ──────────────────────────────────────────────────────────

class LauncherView(Static):
    """Project launcher — select and start Claude."""

    def compose(self) -> ComposeResult:
        db = PulseDB(_DEFAULT_DB_PATH)
        sync_all(db)
        projects = db.execute(
            "SELECT * FROM projects WHERE status != 'done' ORDER BY category, name"
        ).fetchall()

        items = []
        self._projects = {}
        for p in projects:
            p = dict(p)
            ctx = get_next_step(db, p["name"])
            last = theme.time_ago(self._last_event(db, p["path"]))
            item = ProjectItem(p, ctx, last)
            items.append(item)
            self._projects[p["name"]] = (p, ctx, last)

        with Horizontal():
            yield ListView(*items, id="project-list")
            yield Static("  Projekt waehlen...", id="detail")

    def _last_event(self, db: PulseDB, path: str) -> str:
        row = db.execute(
            "SELECT timestamp FROM events WHERE project_path=? ORDER BY timestamp DESC LIMIT 1",
            (path,),
        ).fetchone()
        return row["timestamp"] if row else ""

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, ProjectItem):
            p = event.item.project
            detail = self.query_one("#detail", Static)
            lines = (
                f"  {p['name']}\n"
                f"  {theme.CATEGORY_LABEL.get(p.get('category', ''), '')}  ·  {p['status']}\n"
                f"  {p['path']}\n\n"
                f"  Letzte Aktivitaet: {event.item.last_info}\n\n"
                f"  → {event.item.context}"
            )
            detail.update(lines)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item and isinstance(event.item, ProjectItem):
            self.app._launch_claude(event.item.project)


class DashboardView(Static):
    """Live metrics dashboard — auto-refreshes."""

    def compose(self) -> ComposeResult:
        yield Static("", id="dashboard-content")

    def on_mount(self) -> None:
        self.refresh_dashboard()
        self.set_interval(3.0, self.refresh_dashboard)

    def refresh_dashboard(self) -> None:
        from rich.console import Group
        from pulse.dashboard import (
            build_hero_panel, build_session_panel, build_tool_mix_panel,
            build_activity_panel, build_portfolio_panel,
        )

        db = PulseDB(_DEFAULT_DB_PATH)
        analyzer = Analyzer(db)

        content = Group(
            build_hero_panel(db, analyzer),
            build_session_panel(db, analyzer),
            build_tool_mix_panel(db, analyzer),
            build_activity_panel(db, analyzer),
        )

        widget = self.query_one("#dashboard-content", Static)
        widget.update(content)


class RecapView(Static):
    """Daily/weekly recap."""

    def compose(self) -> ComposeResult:
        yield Static("", id="recap-content")

    def on_mount(self) -> None:
        self.refresh_recap()

    def refresh_recap(self) -> None:
        db = PulseDB(_DEFAULT_DB_PATH)
        analyzer = Analyzer(db)
        recap = analyzer.daily_recap()

        tasks_done = len(recap["tasks_completed"])
        lines = []

        if tasks_done > 0:
            lines.append(f"  {tasks_done} Tasks erledigt  {recap['date']}\n")
        else:
            lines.append(f"  Recap  {recap['date']}\n")

        lines.append(f"  Sessions     {recap['sessions']}")
        lines.append(f"  Arbeitszeit  {theme.duration_human(recap['total_minutes'])}")
        lines.append(f"  Prompts      {recap['prompts']}")
        lines.append(f"  Tool-Calls   {recap['tool_calls']}")
        lines.append(f"  Debug        {recap['debug_cycles']}")
        lines.append(f"  Think-Time   {recap['think_time_pct']:.0f}%")
        lines.append(f"  Dateien      {len(recap['files_touched'])}")

        if recap["tasks_completed"]:
            lines.append("")
            for tc in recap["tasks_completed"]:
                lines.append(f"  ✓ {tc['task']}  {tc['project']}")

        if recap["grouped_activity"]:
            lines.append("\n  Prompt-Runden")
            for g in recap["grouped_activity"][-8:]:
                try:
                    t = datetime.fromisoformat(g["start"]).strftime("%H:%M")
                except (ValueError, TypeError):
                    t = "?"
                marker = "!" if g["errors"] > 0 else "·"
                prompt = (g.get("prompt") or "")[:45]
                lines.append(f"  {t} {marker} {prompt}  [{g['tool_calls']}]")

        widget = self.query_one("#recap-content", Static)
        widget.update("\n".join(lines))


class PortfolioView(Static):
    """Full project portfolio."""

    def compose(self) -> ComposeResult:
        yield Static("", id="portfolio-content")

    def on_mount(self) -> None:
        self.refresh_portfolio()

    def refresh_portfolio(self) -> None:
        db = PulseDB(_DEFAULT_DB_PATH)
        projects = db.execute(
            "SELECT * FROM projects ORDER BY category, status DESC, name"
        ).fetchall()

        cats: dict[str, list] = {}
        for p in projects:
            p = dict(p)
            cats.setdefault(p.get("category") or "tools", []).append(p)

        lines = []
        counts = {"active": 0, "paused": 0, "done": 0}

        for cat_key in ["tools", "learning", "system", "research", "content", "career"]:
            if cat_key not in cats:
                continue
            label = theme.CATEGORY_LABEL.get(cat_key, cat_key)
            lines.append(f"\n  {label}")

            for p in cats[cat_key]:
                s = p["status"]
                dot = theme.STATUS_DOT.get(s, "·")
                cont = " ↻" if p.get("project_type") == "continuous" else ""
                counts[s] = counts.get(s, 0) + 1

                done = p.get("completed_tasks") or 0
                total = p.get("total_tasks") or 0
                progress = ""
                if total > 0 and s != "done":
                    progress = f"  {theme.bar(done / total * 100, 100, 6)} {done}/{total}"

                lines.append(f"  {dot} {p['name']}{cont}{progress}")

        lines.append(f"\n  {counts.get('active', 0)} aktiv  {counts.get('paused', 0)} pausiert  {counts.get('done', 0)} fertig")

        widget = self.query_one("#portfolio-content", Static)
        widget.update("\n".join(lines))


# ── Main App ───────────────────────────────────────────────────────

class PulseApp(App):
    """Pulse — unified TUI."""

    CSS = """
    Screen { layout: vertical; }

    #tab-bar {
        dock: top;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }

    #view-container {
        height: 1fr;
    }

    #project-list {
        width: 36;
        border: solid $primary;
    }

    #detail {
        width: 1fr;
        padding: 1;
    }

    ListItem { padding: 0 1; }
    """

    BINDINGS = [
        Binding("1", "show_launcher", "Launcher"),
        Binding("2", "show_dashboard", "Dashboard"),
        Binding("3", "show_recap", "Recap"),
        Binding("4", "show_portfolio", "Portfolio"),
        Binding("r", "open_report", "Report"),
        Binding("q", "quit", "Beenden"),
    ]

    current_view = reactive("launcher")

    def compose(self) -> ComposeResult:
        yield Label(
            " [1] Launcher  [2] Dashboard  [3] Recap  [4] Portfolio  [r] Report  [q] Beenden",
            id="tab-bar",
        )
        yield VerticalScroll(id="view-container")
        yield Footer()

    def on_mount(self) -> None:
        self.action_show_launcher()

    def _switch_view(self, view: Static) -> None:
        container = self.query_one("#view-container", VerticalScroll)
        container.remove_children()
        container.mount(view)

    def action_show_launcher(self) -> None:
        self.current_view = "launcher"
        self._switch_view(LauncherView())
        self.query_one("#tab-bar", Label).update(
            " [bold][1] Launcher[/bold]  [2] Dashboard  [3] Recap  [4] Portfolio  [r] Report  [q] Beenden"
        )

    def action_show_dashboard(self) -> None:
        self.current_view = "dashboard"
        self._switch_view(DashboardView())
        self.query_one("#tab-bar", Label).update(
            " [1] Launcher  [bold][2] Dashboard[/bold]  [3] Recap  [4] Portfolio  [r] Report  [q] Beenden"
        )

    def action_show_recap(self) -> None:
        self.current_view = "recap"
        self._switch_view(RecapView())
        self.query_one("#tab-bar", Label).update(
            " [1] Launcher  [2] Dashboard  [bold][3] Recap[/bold]  [4] Portfolio  [r] Report  [q] Beenden"
        )

    def action_show_portfolio(self) -> None:
        self.current_view = "portfolio"
        self._switch_view(PortfolioView())
        self.query_one("#tab-bar", Label).update(
            " [1] Launcher  [2] Dashboard  [3] Recap  [bold][4] Portfolio[/bold]  [r] Report  [q] Beenden"
        )

    def action_open_report(self) -> None:
        """Generate and open HTML report in browser."""
        from pulse.report import generate_report
        db_path = str(_DEFAULT_DB_PATH)
        generate_report(db_path=db_path, open_browser=True)
        self.notify("Report geöffnet im Browser")

    def _launch_claude(self, project: dict) -> None:
        """Suspend app, launch Claude, resume on exit."""
        path = project["path"]
        if not Path(path).exists():
            self.notify(f"Pfad nicht gefunden: {path}", severity="error")
            return

        with self.suspend():
            db = PulseDB(_DEFAULT_DB_PATH)
            ctx = get_next_step(db, project["name"])
            print(f"\n  → {project['name']}")
            if ctx and ctx != "Kein naechster Schritt definiert.":
                print(f"  {ctx}\n")

            subprocess.run(["claude", ctx if ctx else ""], cwd=path)


def run_app(db_path: str | None = None) -> None:
    """Start the unified Pulse app."""
    app = PulseApp()
    app.run()
