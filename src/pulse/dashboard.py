"""Pulse dashboard — Rich TUI for live session and project metrics.

Provides an interactive terminal dashboard with:
- Active session overview
- Tool mix visualization
- Project status with progress bars
- Recent activity feed
"""

from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from pulse.analyzer import Analyzer
from pulse.db import PulseDB
from pulse.planner import Planner


def _bar(value: float, max_val: float = 100.0, width: int = 10) -> str:
    """Create a simple bar chart string."""
    filled = int(width * min(value, max_val) / max_val) if max_val > 0 else 0
    return "█" * filled + "░" * (width - filled)


def _status_icon(status: str) -> str:
    icons = {"active": "🟢", "paused": "🟡", "done": "✅", "blocked": "🔴"}
    return icons.get(status, "⚪")


def _task_icon(status: str) -> str:
    icons = {"done": "✅", "in_progress": "🔄", "pending": "⬜", "blocked": "🚫"}
    return icons.get(status, "⬜")


def build_overview_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Build the main overview panel with active session info."""
    # Find the most recent session — prefer events table (more reliable)
    row = db.execute(
        "SELECT session_id, project_path, MAX(timestamp) as last_ts "
        "FROM events GROUP BY session_id ORDER BY last_ts DESC LIMIT 1"
    ).fetchone()

    if not row:
        return Panel("Keine Sessions gefunden.", title="AKTIVE SESSION", border_style="dim")

    sid = row["session_id"]
    events = db.get_events_by_session(sid)

    # Try to get session record, fall back to events data
    session = db.get_session(sid) or {}
    prompts = len([e for e in events if e["event_type"] == "UserPromptSubmit"])
    tool_calls = len([e for e in events if e["event_type"] == "PreToolUse"])
    errors = len([e for e in events if e["event_type"] == "PostToolUse" and e.get("tool_output_success") == 0])

    # Duration
    if events:
        first = datetime.fromisoformat(events[0]["timestamp"])
        last = datetime.fromisoformat(events[-1]["timestamp"])
        duration_min = (last - first).total_seconds() / 60
    else:
        duration_min = 0

    # Debug cycles
    summary = analyzer.session_summary(sid)

    # Project path — from session record or from events
    project = session.get("project_path") or row["project_path"] or "?"
    if project and len(project) > 40:
        project = "..." + project[-37:]

    # Model — from session record or first event with model field
    model = session.get("model")
    if not model:
        for e in events:
            if e.get("model"):
                model = e["model"]
                break
    model = model or "?"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column(style="bold cyan")
    table.add_column()

    table.add_row(
        "Projekt", project,
        "Model", model,
    )
    table.add_row(
        "Laufzeit", f"{duration_min:.0f} min",
        "Prompts", str(prompts),
    )
    table.add_row(
        "Tool-Calls", str(tool_calls),
        "Fehler", str(errors),
    )
    table.add_row(
        "Debug-Zyklen", str(summary["debug_cycles"]),
        "Human-Wait", f"{summary['human_wait_pct']:.0f}%",
    )

    return Panel(table, title=f"AKTIVE SESSION  {sid[:12]}...", border_style="bright_blue")


def build_tool_mix_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Build tool mix visualization panel."""
    # Use the most recent session's project — from events table
    row = db.execute(
        "SELECT project_path FROM events ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    project_path = row["project_path"] if row else None
    mix = analyzer.tool_mix(project_path)

    if mix["total_tool_calls"] == 0:
        return Panel("Keine Tool-Daten.", title="TOOL-MIX", border_style="dim")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=8)
    table.add_column(width=14)
    table.add_column(width=6, justify="right")

    tools = [
        ("Write", mix["write_pct"], "green"),
        ("Edit", mix["edit_pct"], "yellow"),
        ("Bash", mix["bash_pct"], "red"),
        ("Read", mix["read_pct"], "blue"),
        ("Explore", mix["explore_pct"], "magenta"),
        ("Other", mix["other_pct"], "dim"),
    ]

    for name, pct, color in tools:
        bar = _bar(pct, 100.0, 12)
        table.add_row(
            Text(name, style=color),
            Text(bar, style=color),
            f"{pct:.0f}%",
        )

    table.add_row("", "", "")
    table.add_row(
        Text("Total", style="bold"),
        "",
        str(mix["total_tool_calls"]),
    )

    content = table
    return Panel(content, title=f"TOOL-MIX  {mix['interpretation']}", border_style="bright_yellow")


def build_activity_panel(db: PulseDB) -> Panel:
    """Build recent activity feed panel."""
    events = db.execute(
        "SELECT timestamp, event_type, tool_name, tool_input_summary, tool_output_success "
        "FROM events ORDER BY timestamp DESC LIMIT 12"
    ).fetchall()

    if not events:
        return Panel("Keine Events.", title="LETZTE AKTIVITAET", border_style="dim")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=5)  # time
    table.add_column(width=2)  # icon
    table.add_column()  # description

    for e in reversed(list(events)):
        e = dict(e)
        ts = e["timestamp"]
        try:
            t = datetime.fromisoformat(ts)
            time_str = t.strftime("%H:%M")
        except (ValueError, TypeError):
            time_str = "??:??"

        if e["event_type"] == "UserPromptSubmit":
            icon = "▶"
            desc = "Neuer Prompt"
            style = "bold white"
        elif e["event_type"] == "Stop":
            icon = "⏸"
            desc = "Agent wartet"
            style = "dim"
        elif e["event_type"] == "SessionStart":
            icon = "🟢"
            desc = "Session gestartet"
            style = "green"
        elif e["event_type"] == "SessionEnd":
            icon = "🔴"
            desc = "Session beendet"
            style = "red"
        elif e["event_type"] in ("PreToolUse", "PostToolUse"):
            tool = e.get("tool_name") or "?"
            summary = e.get("tool_input_summary") or ""
            if len(summary) > 30:
                summary = summary[:27] + "..."

            if e["event_type"] == "PreToolUse":
                continue  # Only show PostToolUse to avoid duplicates
            success = e.get("tool_output_success")
            if success == 1 or success is True:
                icon = "✅"
                style = "green"
            elif success == 0 or success is False:
                icon = "❌"
                style = "red"
            else:
                icon = "·"
                style = "dim"
            desc = f"{tool} {summary}"
        else:
            icon = "·"
            desc = e["event_type"]
            style = "dim"

        table.add_row(
            Text(time_str, style="dim"),
            icon,
            Text(desc, style=style),
        )

    return Panel(table, title="LETZTE AKTIVITAET", border_style="bright_green")


def build_projects_panel(db: PulseDB, analyzer: Analyzer, planner: Planner) -> Panel:
    """Build projects overview panel with progress and forecasts."""
    projects = db.execute("SELECT * FROM projects ORDER BY status, name").fetchall()

    if not projects:
        return Panel("Keine Projekte registriert.", title="PROJEKTE", border_style="dim")

    table = Table(show_header=True, box=box.SIMPLE, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column("Projekt", width=16)
    table.add_column("Fortschritt", width=18)
    table.add_column("Prognose", width=22)

    for p in projects:
        p = dict(p)
        icon = _status_icon(p["status"])
        name = p["name"]
        if len(name) > 15:
            name = name[:13] + ".."

        # Progress
        done = p.get("completed_tasks") or 0
        total = p.get("total_tasks") or 0
        if total > 0:
            pct = done / total
            bar = _bar(pct * 100, 100, 8)
            progress = f"{bar} {done}/{total}"
        else:
            progress = "—"

        # Forecast
        if p["status"] == "paused":
            forecast_str = Text("pausiert", style="dim")
        elif p["status"] == "done":
            forecast_str = Text("fertig", style="green")
        else:
            forecast = planner.project_forecast(p["name"])
            if forecast and forecast["status"] == "on_track":
                buf = forecast.get("buffer_hours")
                if buf is not None:
                    forecast_str = Text(f"✅ on track ({buf:.1f}h Puffer)", style="green")
                else:
                    forecast_str = Text("✅ on track", style="green")
            elif forecast and forecast["status"] == "at_risk":
                forecast_str = Text(f"⚠️  at risk", style="bold red")
            elif forecast and forecast["status"] == "no_deadline":
                forecast_str = Text("kein Deadline", style="dim")
            else:
                forecast_str = Text("zu wenig Daten", style="dim")

        table.add_row(icon, name, progress, forecast_str)

    return Panel(table, title="PROJEKTE", border_style="bright_magenta")


def build_project_detail_panel(db: PulseDB, analyzer: Analyzer, project_name: str) -> Panel:
    """Build detailed view for a single project."""
    project = db.get_project(project_name)
    if not project:
        return Panel(f"Projekt '{project_name}' nicht gefunden.", border_style="red")

    tasks = db.get_tasks(project["id"])
    health = analyzer.project_health(project_name)

    table = Table(show_header=True, box=box.SIMPLE, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column("Task", width=22)
    table.add_column("Status", width=12)
    table.add_column("Dauer", width=8, justify="right")
    table.add_column("Debug", width=6, justify="right")

    for t in tasks:
        icon = _task_icon(t["status"])
        duration = f"{t['actual_minutes']:.0f} min" if t.get("actual_minutes") else "—"
        debug = str(t["debug_cycles"]) if t.get("debug_cycles") else "—"
        if t.get("debug_cycles") and t["debug_cycles"] >= 4:
            debug += " ⚠️"
        table.add_row(icon, t["name"], t["status"], duration, debug)

    # Health metrics
    if health:
        table.add_row("", "", "", "", "")
        table.add_row(
            "", Text("Avg Debug-Ratio", style="bold"),
            f"{health['avg_debug_ratio']:.1%}", "", "",
        )
        table.add_row(
            "", Text("Sessions gesamt", style="bold"),
            f"{health['total_session_hours']:.1f}h", "", "",
        )
        table.add_row(
            "", Text("Trend", style="bold"),
            health["trend"], "", "",
        )

    deadline = project.get("deadline") or "kein Deadline"
    return Panel(table, title=f"PROJEKT: {project_name}  —  {deadline}", border_style="bright_cyan")


def build_dashboard(db: PulseDB) -> Layout:
    """Build the full dashboard layout."""
    analyzer = Analyzer(db)
    planner = Planner(db, analyzer)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="top", size=10),
        Layout(name="middle", size=11),
        Layout(name="bottom", size=10),
    )

    # Header
    now = datetime.now().strftime("%H:%M")
    header = Text(f"  🫀 PULSE  ─────────────────────────────────────────  {now}  ", style="bold bright_blue on dark_blue")
    layout["header"].update(header)

    # Top: Session overview + Tool mix
    layout["top"].split_row(
        Layout(build_overview_panel(db, analyzer), name="session"),
        Layout(build_tool_mix_panel(db, analyzer), name="toolmix"),
    )

    # Middle: Activity feed
    layout["middle"].update(build_activity_panel(db))

    # Bottom: Projects
    layout["bottom"].update(build_projects_panel(db, analyzer, planner))

    return layout


def run_dashboard(db_path: str, refresh_interval: float = 2.0) -> None:
    """Run the live dashboard with auto-refresh."""
    console = Console()

    try:
        with Live(console=console, refresh_per_second=1.0 / refresh_interval, screen=True) as live:
            while True:
                db = PulseDB(db_path)
                layout = build_dashboard(db)
                live.update(layout)
                import time
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Pulse Dashboard beendet.[/dim]")


def print_snapshot(db_path: str, project_name: str | None = None) -> None:
    """Print a single snapshot of the dashboard (no live refresh)."""
    console = Console()
    db = PulseDB(db_path)
    analyzer = Analyzer(db)
    planner = Planner(db, analyzer)

    console.print()
    console.print(build_overview_panel(db, analyzer))
    console.print(build_tool_mix_panel(db, analyzer))
    console.print(build_activity_panel(db))
    console.print(build_projects_panel(db, analyzer, planner))

    if project_name:
        console.print(build_project_detail_panel(db, analyzer, project_name))
