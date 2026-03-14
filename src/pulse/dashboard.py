"""Pulse dashboard — Rich TUI for live session and project metrics.

Redesigned after Challenge review. Priorities:
1. Hero-KPI: Tasks done today (Outcome > Activity)
2. Think-Time statt Human-Wait (positiv framen)
3. Grouped Activity (Prompt-Runden statt einzelne Events)
4. Trend-Vergleiche bei Metriken
"""

from datetime import datetime
from pathlib import Path

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
    filled = int(width * min(value, max_val) / max_val) if max_val > 0 else 0
    return "█" * filled + "░" * (width - filled)


def _status_icon(status: str) -> str:
    return {"active": "🟢", "paused": "🟡", "done": "✅", "blocked": "🔴"}.get(status, "⚪")


def _task_icon(status: str) -> str:
    return {"done": "✅", "in_progress": "🔄", "pending": "⬜", "blocked": "🚫"}.get(status, "⬜")


def _short_path(path: str, max_len: int = 30) -> str:
    if not path or len(path) <= max_len:
        return path or "?"
    return "..." + path[-(max_len - 3):]


def build_hero_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Hero KPI panel — what matters: Outcomes, not activity."""
    recap = analyzer.daily_recap()

    tasks_done = len(recap["tasks_completed"])
    files = len(recap["files_touched"])
    sessions = recap["sessions"]
    minutes = recap["total_minutes"]
    debug = recap["debug_cycles"]
    think = recap["think_time_pct"]

    # Hero line
    if tasks_done > 0:
        hero = Text(f"  {tasks_done} Tasks erledigt heute", style="bold green")
    elif minutes > 0:
        hero = Text(f"  Aktiv seit {minutes:.0f} min — noch keine Tasks abgeschlossen", style="yellow")
    else:
        hero = Text("  Heute noch keine Aktivitaet", style="dim")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", width=14)
    table.add_column(width=12)
    table.add_column(style="bold cyan", width=14)
    table.add_column(width=12)

    table.add_row(
        "Sessions", str(sessions),
        "Dateien", str(files),
    )
    table.add_row(
        "Arbeitszeit", f"{minutes:.0f} min",
        "Debug-Zyklen", str(debug),
    )
    table.add_row(
        "Think-Time", f"{think:.0f}%",
        "Prompts", str(recap["prompts"]),
    )

    # Tasks completed list
    if recap["tasks_completed"]:
        table.add_row("", "", "", "")
        for tc in recap["tasks_completed"][:3]:
            table.add_row("", f"✅ {tc['task']}", "", tc["project"])

    content = Text()
    content.append_text(hero)

    from rich.console import Group
    panel_content = Group(hero, Text(""), table)

    return Panel(panel_content, title=f"HEUTE  {recap['date']}", border_style="bright_green")


def build_session_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Current session overview — compact."""
    row = db.execute(
        "SELECT session_id, project_path, MAX(timestamp) as last_ts "
        "FROM events GROUP BY session_id ORDER BY last_ts DESC LIMIT 1"
    ).fetchone()

    if not row:
        return Panel("Keine aktive Session.", title="SESSION", border_style="dim")

    sid = row["session_id"]
    summary = analyzer.session_summary(sid)
    project = _short_path(row["project_path"])

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold cyan", width=12)
    table.add_column(width=16)

    table.add_row("Projekt", project)
    table.add_row("Laufzeit", f"{summary['duration_minutes']:.0f} min")
    table.add_row("Tool-Calls", str(summary["tool_calls"]))
    table.add_row("Debug", str(summary["debug_cycles"]))
    table.add_row("Think-Time", f"{summary['human_wait_pct']:.0f}%")
    table.add_row("Model", summary["model"] or "?")

    return Panel(table, title=f"SESSION  {sid[:8]}...", border_style="bright_blue")


def build_tool_mix_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Tool mix visualization."""
    row = db.execute(
        "SELECT project_path FROM events ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    project_path = row["project_path"] if row else None
    mix = analyzer.tool_mix(project_path)

    if mix["total_tool_calls"] == 0:
        return Panel("Keine Tool-Daten.", title="TOOL-MIX", border_style="dim")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=7)
    table.add_column(width=12)
    table.add_column(width=5, justify="right")

    tools = [
        ("Write", mix["write_pct"], "green"),
        ("Edit", mix["edit_pct"], "yellow"),
        ("Bash", mix["bash_pct"], "red"),
        ("Read", mix["read_pct"], "blue"),
        ("Expl.", mix["explore_pct"], "magenta"),
    ]

    for name, pct, color in tools:
        if pct > 0:
            table.add_row(
                Text(name, style=color),
                Text(_bar(pct, 100.0, 10), style=color),
                f"{pct:.0f}%",
            )

    return Panel(table, title=f"TOOL-MIX  {mix['interpretation']}", border_style="bright_yellow")


def build_grouped_activity_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Grouped activity feed — prompt rounds instead of raw events."""
    recap = analyzer.daily_recap()
    groups = recap["grouped_activity"]

    if not groups:
        return Panel("Keine Aktivitaet heute.", title="AKTIVITAET", border_style="dim")

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=5)   # time
    table.add_column(width=2)   # icon
    table.add_column()          # description

    # Show last 8 groups
    for g in groups[-8:]:
        try:
            start = datetime.fromisoformat(g["start"]).strftime("%H:%M")
        except (ValueError, TypeError):
            start = "??:??"

        prompt = g.get("prompt", "")
        if len(prompt) > 45:
            prompt = prompt[:42] + "..."

        calls = g["tool_calls"]
        errors = g["errors"]
        files = g.get("files", [])

        # Status icon
        if errors > 0:
            icon = "⚠️"
            style = "yellow"
        else:
            icon = "✅"
            style = "green"

        # Description
        file_str = ""
        if files:
            short_files = [Path(f).name for f in files[:3]]
            file_str = f" → {', '.join(short_files)}"
            if len(files) > 3:
                file_str += f" +{len(files)-3}"

        desc = f"{prompt}"
        if calls > 0:
            desc += f"  [{calls} calls{file_str}]"
            if errors > 0:
                desc += f" {errors}❌"

        table.add_row(
            Text(start, style="dim"),
            icon,
            Text(desc, style=style),
        )

    return Panel(table, title="AKTIVITAET  (Prompt-Runden)", border_style="bright_green")


def build_projects_panel(db: PulseDB, analyzer: Analyzer, planner: Planner) -> Panel:
    """Projects overview with forecasts."""
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

        done = p.get("completed_tasks") or 0
        total = p.get("total_tasks") or 0
        if total > 0:
            pct = done / total
            bar = _bar(pct * 100, 100, 8)
            progress = f"{bar} {done}/{total}"
        else:
            progress = "—"

        if p["status"] == "paused":
            forecast_str = Text("pausiert", style="dim")
        elif p["status"] == "done":
            forecast_str = Text("fertig", style="green")
        else:
            forecast = planner.project_forecast(p["name"])
            if forecast and forecast["status"] == "on_track":
                buf = forecast.get("buffer_hours")
                if buf is not None:
                    forecast_str = Text(f"✅ on track ({buf:.1f}h)", style="green")
                else:
                    forecast_str = Text("✅ on track", style="green")
            elif forecast and forecast["status"] == "at_risk":
                forecast_str = Text("⚠️  at risk", style="bold red")
            elif forecast and forecast["status"] == "no_deadline":
                forecast_str = Text("kein Deadline", style="dim")
            else:
                forecast_str = Text("zu wenig Daten", style="dim")

        table.add_row(icon, name, progress, forecast_str)

    return Panel(table, title="PROJEKTE", border_style="bright_magenta")


def build_dashboard(db: PulseDB) -> Layout:
    """Build the full dashboard layout."""
    analyzer = Analyzer(db)
    planner = Planner(db, analyzer)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="top", size=12),
        Layout(name="middle", size=12),
        Layout(name="bottom", size=10),
    )

    # Header
    now = datetime.now().strftime("%H:%M")
    header = Text(f"  🫀 PULSE  ─────────────────────────────────────────  {now}  ", style="bold bright_blue on dark_blue")
    layout["header"].update(header)

    # Top: Hero KPI (left) + Session + Tool Mix (right)
    layout["top"].split_row(
        Layout(build_hero_panel(db, analyzer), name="hero", ratio=3),
        Layout(name="right", ratio=2),
    )
    layout["top"]["right"].split_column(
        Layout(build_session_panel(db, analyzer), name="session"),
        Layout(build_tool_mix_panel(db, analyzer), name="toolmix"),
    )

    # Middle: Grouped Activity
    layout["middle"].update(build_grouped_activity_panel(db, analyzer))

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
    console.print(build_hero_panel(db, analyzer))
    console.print(build_session_panel(db, analyzer))
    console.print(build_tool_mix_panel(db, analyzer))
    console.print(build_grouped_activity_panel(db, analyzer))
    console.print(build_projects_panel(db, analyzer, planner))

    if project_name:
        from pulse.analyzer import Analyzer as A
        console.print(build_project_detail_panel(db, analyzer, project_name))


def build_project_detail_panel(db: PulseDB, analyzer: Analyzer, project_name: str) -> Panel:
    """Detailed view for a single project."""
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

    if health:
        table.add_row("", "", "", "", "")
        table.add_row("", Text("Debug-Ratio", style="bold"), f"{health['avg_debug_ratio']:.1%}", "", "")
        table.add_row("", Text("Sessions", style="bold"), f"{health['total_session_hours']:.1f}h", "", "")
        table.add_row("", Text("Trend", style="bold"), health["trend"], "", "")

    deadline = project.get("deadline") or "kein Deadline"
    return Panel(table, title=f"PROJEKT: {project_name}  —  {deadline}", border_style="bright_cyan")
