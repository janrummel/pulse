"""Pulse dashboard — Rich TUI. Design follows theme.py principles."""

from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from pulse.analyzer import Analyzer
from pulse.db import PulseDB
from pulse.planner import Planner
from pulse import theme


# ── Hero Panel ─────────────────────────────────────────────────────

def build_hero_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Outcome-focused: what got done today."""
    recap = analyzer.daily_recap()

    tasks_done = len(recap["tasks_completed"])
    minutes = recap["total_minutes"]
    files = len(recap["files_touched"])
    debug = recap["debug_cycles"]
    think = recap["think_time_pct"]

    # Hero — largest visual weight
    if tasks_done > 0:
        hero = Text(f"  {tasks_done} Tasks erledigt", style="bold green")
    elif minutes > 0:
        hero = Text(f"  {theme.duration_human(minutes)} aktiv", style="bold yellow")
    else:
        hero = Text("  Noch keine Aktivitaet", style="dim")

    # Secondary metrics — compact, dim
    meta = Text("  ", style="dim")
    meta.append(f"{recap['sessions']} Sessions", style="dim")
    meta.append(f"   {files} Dateien", style="dim")
    meta.append(f"   {debug} Debug", style="red" if debug > 3 else "dim")
    meta.append(f"   {think:.0f}% Think", style="dim")

    parts = [hero, Text(""), meta]

    # Completed tasks — success style
    if recap["tasks_completed"]:
        parts.append(Text(""))
        for tc in recap["tasks_completed"][:4]:
            line = Text("  ✓ ", style="green")
            line.append(tc["task"], style="green")
            line.append(f"  {tc['project']}", style="dim")
            parts.append(line)

    return Panel(Group(*parts), title=f"Heute  {recap['date']}", border_style="green", padding=(0, 1))


# ── Session Panel ──────────────────────────────────────────────────

def build_session_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Current session — compact, secondary importance."""
    row = db.execute(
        "SELECT session_id, project_path, MAX(timestamp) as last_ts "
        "FROM events GROUP BY session_id ORDER BY last_ts DESC LIMIT 1"
    ).fetchone()

    if not row:
        return Panel(Text("  Keine aktive Session", style="dim"),
                     title="Session", border_style="dim", padding=(0, 1))

    sid = row["session_id"]
    summary = analyzer.session_summary(sid)
    project = theme.short_path(row["project_path"])

    lines = Text()
    lines.append(f"  {project}", style="bold")
    lines.append(f"   {summary['model'] or '?'}\n", style="dim")
    lines.append(f"  {theme.duration_human(summary['duration_minutes'])}", style="")
    lines.append(f"   {summary['tool_calls']} calls", style="dim")
    if summary["debug_cycles"] > 0:
        lines.append(f"   {summary['debug_cycles']} debug", style="red")
    lines.append(f"   {summary['human_wait_pct']:.0f}% think", style="dim")

    return Panel(lines, title=f"Session  {sid[:8]}", border_style="blue", padding=(0, 1))


# ── Tool Mix Panel ─────────────────────────────────────────────────

def build_tool_mix_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Tool distribution — only show what matters."""
    row = db.execute(
        "SELECT project_path FROM events ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    mix = analyzer.tool_mix(row["project_path"] if row else None)

    if mix["total_tool_calls"] == 0:
        return Panel(Text("  —", style="dim"), title="Tool-Mix", border_style="dim", padding=(0, 1))

    tools = [
        ("Write", mix["write_pct"], "green"),
        ("Edit", mix["edit_pct"], "yellow"),
        ("Bash", mix["bash_pct"], "red"),
        ("Read", mix["read_pct"], "blue"),
        ("Search", mix["explore_pct"], "magenta"),
    ]

    lines = Text()
    for name, pct, color in tools:
        if pct >= 3:  # Only show meaningful percentages
            lines.append(f"  {name:<6} ", style="dim")
            lines.append(theme.bar(pct, 100.0, 8), style=color)
            lines.append(f" {pct:.0f}%\n", style="dim")

    return Panel(lines, title=f"Tool-Mix  {mix['interpretation']}", border_style="yellow", padding=(0, 1))


# ── Activity Panel ─────────────────────────────────────────────────

def build_activity_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Grouped by prompt rounds — not raw events."""
    recap = analyzer.daily_recap()
    groups = recap["grouped_activity"]

    if not groups:
        return Panel(Text("  —", style="dim"), title="Aktivitaet", border_style="dim", padding=(0, 1))

    lines = Text()
    for g in groups[-6:]:
        try:
            t = datetime.fromisoformat(g["start"]).strftime("%H:%M")
        except (ValueError, TypeError):
            t = "?"

        prompt = (g.get("prompt") or "")[:40]
        calls = g["tool_calls"]
        errors = g["errors"]
        files = g.get("files", [])

        # Status: ! for errors, · for clean
        marker = "!" if errors > 0 else "·"
        style = "yellow" if errors > 0 else ""

        lines.append(f"  {t} ", style="dim")
        lines.append(f"{marker} ", style=style)
        lines.append(f"{prompt}", style=style)

        if calls > 0:
            lines.append(f"  {calls}", style="dim")
            if files:
                short = [Path(f).name for f in files[:2]]
                lines.append(f" → {', '.join(short)}", style="dim")
        lines.append("\n")

    return Panel(lines, title="Aktivitaet", border_style="cyan", padding=(0, 1))


# ── Portfolio Panel ────────────────────────────────────────────────

def build_portfolio_panel(db: PulseDB) -> Panel:
    """All projects grouped by category."""
    projects = db.execute(
        "SELECT * FROM projects ORDER BY category, status DESC, name"
    ).fetchall()

    if not projects:
        return Panel(Text("  Keine Projekte", style="dim"),
                     title="Portfolio", border_style="dim", padding=(0, 1))

    cats: dict[str, list] = {}
    for p in projects:
        p = dict(p)
        cat = p.get("category") or "tools"
        cats.setdefault(cat, []).append(p)

    lines = Text()
    counts = {"active": 0, "paused": 0, "done": 0}

    for cat_key in ["tools", "learning", "system", "research", "content", "career"]:
        if cat_key not in cats:
            continue

        label = theme.CATEGORY_LABEL.get(cat_key, cat_key)
        lines.append(f"\n  {label}\n", style="bold cyan")

        for p in cats[cat_key]:
            status = p["status"]
            dot = theme.STATUS_DOT.get(status, "·")
            style = theme.STATUS_STYLE.get(status, "")
            counts[status] = counts.get(status, 0) + 1
            cont = " ↻" if p.get("project_type") == "continuous" else ""

            # Progress bar only for active projects with tasks
            done = p.get("completed_tasks") or 0
            total = p.get("total_tasks") or 0
            progress = ""
            if total > 0 and status != "done":
                progress = f" {theme.bar(done / total * 100, 100, 6)} {done}/{total}"

            lines.append(f"  {dot} ", style=style)
            lines.append(f"{p['name']}", style=style)
            lines.append(f"{cont}", style="dim")
            lines.append(f"{progress}\n", style=style)

    lines.append(f"\n  {counts.get('active', 0)} aktiv", style="green")
    lines.append(f"  {counts.get('paused', 0)} pausiert", style="yellow")
    lines.append(f"  {counts.get('done', 0)} fertig\n", style="dim")

    return Panel(lines, title="Portfolio", border_style="magenta", padding=(0, 0))


# ── Layout ─────────────────────────────────────────────────────────

def build_dashboard(db: PulseDB) -> Layout:
    """Two-column layout: main (outcomes) + side (context)."""
    analyzer = Analyzer(db)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="body"),
    )

    now = datetime.now().strftime("%H:%M")
    layout["header"].update(
        Text(f" 🫀 Pulse  ──────────────────────────────────────────────  {now} ",
             style="bold bright_blue on dark_blue")
    )

    layout["body"].split_row(
        Layout(name="main", ratio=3),
        Layout(name="side", ratio=2),
    )

    layout["main"].split_column(
        Layout(build_hero_panel(db, analyzer), name="hero", size=9),
        Layout(build_session_panel(db, analyzer), name="session", size=4),
        Layout(build_activity_panel(db, analyzer), name="activity"),
    )

    layout["side"].split_column(
        Layout(build_tool_mix_panel(db, analyzer), name="toolmix", size=9),
        Layout(build_portfolio_panel(db), name="portfolio"),
    )

    return layout


# ── Entry points ───────────────────────────────────────────────────

def run_dashboard(db_path: str, refresh_interval: float = 2.0) -> None:
    """Live dashboard with auto-refresh."""
    console = Console()
    try:
        with Live(console=console, refresh_per_second=1.0 / refresh_interval, screen=True) as live:
            while True:
                db = PulseDB(db_path)
                live.update(build_dashboard(db))
                import time
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Pulse beendet.[/dim]")


def print_snapshot(db_path: str, project_name: str | None = None) -> None:
    """Single dashboard snapshot."""
    console = Console()
    db = PulseDB(db_path)
    analyzer = Analyzer(db)

    console.print()
    console.print(build_hero_panel(db, analyzer))
    console.print(build_session_panel(db, analyzer))
    console.print(build_tool_mix_panel(db, analyzer))
    console.print(build_activity_panel(db, analyzer))
    console.print(build_portfolio_panel(db))

    if project_name:
        console.print(build_project_detail_panel(db, analyzer, project_name))


def build_project_detail_panel(db: PulseDB, analyzer: Analyzer, project_name: str) -> Panel:
    """Single project detail view."""
    project = db.get_project(project_name)
    if not project:
        return Panel(f"Projekt '{project_name}' nicht gefunden.", border_style="red")

    tasks = db.get_tasks(project["id"])
    health = analyzer.project_health(project_name)

    table = Table(show_header=True, box=box.SIMPLE, padding=(0, 1))
    table.add_column("", width=2)
    table.add_column("Task", width=22)
    table.add_column("Status", width=10)
    table.add_column("Dauer", width=8, justify="right")
    table.add_column("Debug", width=5, justify="right")

    for t in tasks:
        marker = theme.TASK_MARKER.get(t["status"], " ")
        style = theme.TASK_STYLE.get(t["status"], "")
        duration = theme.duration_human(t["actual_minutes"]) if t.get("actual_minutes") else "—"
        debug = str(t["debug_cycles"]) if t.get("debug_cycles") else "—"
        table.add_row(marker, t["name"], t["status"], duration, debug, style=style)

    if health:
        table.add_row("", "", "", "", "")
        table.add_row("", "Debug-Ratio", f"{health['avg_debug_ratio']:.0%}", "", "", style="dim")
        table.add_row("", "Sessions", f"{health['total_session_hours']:.1f}h", "", "", style="dim")

    title = project_name
    if project.get("deadline"):
        title += f"  ·  {project['deadline']}"
    return Panel(table, title=title, border_style="cyan", padding=(0, 1))
