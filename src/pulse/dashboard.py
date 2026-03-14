"""Pulse dashboard — Rich TUI for live session and project metrics.

Design principles (inspired by Apple HIG):
- Clarity: Every element earns its place. No decorative noise.
- Hierarchy: Most important info (outcomes) gets most visual weight.
- Progressive disclosure: Summary first, detail on demand.
- Color = meaning: green=good, yellow=attention, red=problem, dim=secondary.
- Consistency: Same patterns, spacing, alignment everywhere.
- Breathing room: Whitespace is a feature, not waste.
"""

from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.columns import Columns
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from pulse.analyzer import Analyzer
from pulse.db import PulseDB
from pulse.planner import Planner


# ── Visual primitives ──────────────────────────────────────────────

def _bar(value: float, max_val: float = 100.0, width: int = 10) -> str:
    filled = int(width * min(value, max_val) / max_val) if max_val > 0 else 0
    return "█" * filled + "░" * (width - filled)


def _short_path(path: str, max_len: int = 28) -> str:
    if not path:
        return "?"
    parts = Path(path).parts
    if len(str(path)) <= max_len:
        return path
    return parts[-1] if parts else path


def _status_dot(status: str) -> str:
    return {"active": "●", "paused": "○", "done": "✓"}.get(status, "·")


def _status_style(status: str) -> str:
    return {"active": "green", "paused": "yellow", "done": "dim"}.get(status, "")


# ── Hero Panel ─────────────────────────────────────────────────────

def build_hero_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """What matters: outcomes today."""
    recap = analyzer.daily_recap()

    tasks_done = len(recap["tasks_completed"])
    minutes = recap["total_minutes"]
    files = len(recap["files_touched"])
    debug = recap["debug_cycles"]
    think = recap["think_time_pct"]

    # Hero number
    if tasks_done > 0:
        hero = Text(f" {tasks_done}", style="bold green", end="")
        hero.append(" Tasks erledigt", style="green")
    elif minutes > 0:
        hero = Text(f" {minutes:.0f} min", style="bold yellow", end="")
        hero.append(" aktiv, 0 Tasks abgeschlossen", style="yellow")
    else:
        hero = Text(" —  Noch keine Aktivitaet", style="dim")

    # Metrics row
    metrics = Text()
    metrics.append(f"  {recap['sessions']} Sessions", style="dim")
    metrics.append(f"   {files} Dateien", style="dim")
    metrics.append(f"   {debug} Debug", style="red" if debug > 3 else "dim")
    metrics.append(f"   {think:.0f}% Think", style="dim")

    # Completed tasks
    parts = [hero, Text(""), metrics]
    if recap["tasks_completed"]:
        parts.append(Text(""))
        for tc in recap["tasks_completed"][:4]:
            parts.append(Text(f"  ✓ {tc['task']}  ", style="green", end=""))
            parts.append(Text(tc["project"], style="dim"))

    return Panel(
        Group(*parts),
        title=f"Heute  {recap['date']}",
        border_style="green",
        padding=(0, 1),
    )


# ── Session Panel ──────────────────────────────────────────────────

def build_session_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Current session — compact, secondary."""
    row = db.execute(
        "SELECT session_id, project_path, MAX(timestamp) as last_ts "
        "FROM events GROUP BY session_id ORDER BY last_ts DESC LIMIT 1"
    ).fetchone()

    if not row:
        return Panel(Text("  Keine aktive Session", style="dim"),
                     title="Session", border_style="dim", padding=(0, 1))

    sid = row["session_id"]
    summary = analyzer.session_summary(sid)
    project = _short_path(row["project_path"])

    lines = Text()
    lines.append(f"  {project}", style="bold")
    lines.append(f"   {summary['model'] or '?'}\n", style="dim")
    lines.append(f"  {summary['duration_minutes']:.0f} min", style="")
    lines.append(f"   {summary['tool_calls']} calls", style="dim")
    lines.append(f"   {summary['debug_cycles']} debug", style="red" if summary["debug_cycles"] > 2 else "dim")
    lines.append(f"   {summary['human_wait_pct']:.0f}% think", style="dim")

    return Panel(lines, title=f"Session  {sid[:8]}", border_style="blue", padding=(0, 1))


# ── Tool Mix Panel ─────────────────────────────────────────────────

def build_tool_mix_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Tool distribution — compact bars."""
    row = db.execute(
        "SELECT project_path FROM events ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    mix = analyzer.tool_mix(row["project_path"] if row else None)

    if mix["total_tool_calls"] == 0:
        return Panel(Text("  —", style="dim"), title="Tool-Mix", border_style="dim", padding=(0, 1))

    tools = [
        ("Wr", mix["write_pct"], "green"),
        ("Ed", mix["edit_pct"], "yellow"),
        ("Sh", mix["bash_pct"], "red"),
        ("Rd", mix["read_pct"], "blue"),
        ("Ex", mix["explore_pct"], "magenta"),
    ]

    lines = Text()
    for name, pct, color in tools:
        if pct >= 3:
            lines.append(f"  {name} ", style="dim")
            lines.append(_bar(pct, 100.0, 8), style=color)
            lines.append(f" {pct:.0f}%\n", style="dim")

    return Panel(lines, title=f"Tool-Mix  {mix['interpretation']}", border_style="yellow", padding=(0, 1))


# ── Activity Panel ─────────────────────────────────────────────────

def build_activity_panel(db: PulseDB, analyzer: Analyzer) -> Panel:
    """Grouped activity — prompt rounds, not raw events."""
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

        icon = "!" if errors > 0 else "·"
        style = "yellow" if errors > 0 else ""

        lines.append(f"  {t} ", style="dim")
        lines.append(f"{icon} ", style=style)
        lines.append(f"{prompt}", style=style)

        if calls > 0:
            lines.append(f"  {calls}", style="dim")
            if files:
                short = [Path(f).name for f in files[:2]]
                lines.append(f" → {', '.join(short)}", style="dim")
        lines.append("\n")

    return Panel(lines, title="Aktivitaet", border_style="cyan", padding=(0, 1))


# ── Portfolio Panel ────────────────────────────────────────────────

_CAT_LABELS = {
    "tools": "Tools",
    "learning": "Learning",
    "system": "System",
    "research": "Research",
    "content": "Content",
    "career": "Career",
}


def build_portfolio_panel(db: PulseDB) -> Panel:
    """Full project portfolio grouped by category."""
    projects = db.execute(
        "SELECT * FROM projects ORDER BY category, status DESC, name"
    ).fetchall()

    if not projects:
        return Panel(Text("  Keine Projekte", style="dim"),
                     title="Portfolio", border_style="dim", padding=(0, 1))

    # Group by category
    cats: dict[str, list] = {}
    for p in projects:
        p = dict(p)
        cat = p.get("category") or "tools"
        cats.setdefault(cat, []).append(p)

    lines = Text()
    active_count = 0

    for cat_key in ["tools", "learning", "system", "research", "content", "career"]:
        if cat_key not in cats:
            continue

        cat_projects = cats[cat_key]
        label = _CAT_LABELS.get(cat_key, cat_key)
        lines.append(f"\n  {label}\n", style="bold")

        for p in cat_projects:
            status = p["status"]
            dot = _status_dot(status)
            style = _status_style(status)
            name = p["name"]
            ptype = " ↻" if p.get("project_type") == "continuous" else ""

            if status == "active":
                active_count += 1

            # Progress
            done = p.get("completed_tasks") or 0
            total = p.get("total_tasks") or 0
            if total > 0 and status != "done":
                pct = done / total * 100
                progress = f" {_bar(pct, 100, 6)} {done}/{total}"
            elif status == "done":
                progress = ""
            else:
                progress = ""

            lines.append(f"  {dot} ", style=style)
            lines.append(f"{name}", style=style)
            lines.append(f"{ptype}", style="dim")
            lines.append(f"{progress}\n", style=style)

    done_count = len([p for p in projects if dict(p).get("status") == "done"])
    paused_count = len([p for p in projects if dict(p).get("status") == "paused"])

    lines.append(f"\n  {active_count} aktiv", style="green")
    lines.append(f"  {paused_count} pausiert", style="yellow")
    lines.append(f"  {done_count} fertig\n", style="dim")

    return Panel(lines, title="Portfolio", border_style="magenta", padding=(0, 0))


# ── Dashboard Layout ───────────────────────────────────────────────

def build_dashboard(db: PulseDB) -> Layout:
    """Full dashboard — HIG-inspired layout."""
    analyzer = Analyzer(db)

    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="body"),
    )

    # Header — minimal, just brand + time
    now = datetime.now().strftime("%H:%M")
    layout["header"].update(
        Text(f" 🫀 Pulse  ──────────────────────────────────────────────  {now} ",
             style="bold bright_blue on dark_blue")
    )

    # Body — two columns
    layout["body"].split_row(
        Layout(name="main", ratio=3),
        Layout(name="side", ratio=2),
    )

    # Main column: Hero → Activity
    layout["main"].split_column(
        Layout(build_hero_panel(db, analyzer), name="hero", size=9),
        Layout(build_session_panel(db, analyzer), name="session", size=4),
        Layout(build_activity_panel(db, analyzer), name="activity"),
    )

    # Side column: Tool Mix → Portfolio
    layout["side"].split_column(
        Layout(build_tool_mix_panel(db, analyzer), name="toolmix", size=9),
        Layout(build_portfolio_panel(db), name="portfolio"),
    )

    return layout


# ── Entry points ───────────────────────────────────────────────────

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
        console.print("\n[dim]Pulse beendet.[/dim]")


def print_snapshot(db_path: str, project_name: str | None = None) -> None:
    """Print a single dashboard snapshot."""
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
    """Detailed view for a single project."""
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
        icon = {"done": "✓", "in_progress": "›", "pending": " ", "blocked": "!"}.get(t["status"], " ")
        style = "dim" if t["status"] == "done" else "bold red" if t.get("debug_cycles", 0) >= 4 else ""
        duration = f"{t['actual_minutes']:.0f}m" if t.get("actual_minutes") else "—"
        debug = str(t["debug_cycles"]) if t.get("debug_cycles") else "—"
        table.add_row(icon, t["name"], t["status"], duration, debug, style=style)

    if health:
        table.add_row("", "", "", "", "")
        table.add_row("", "Debug-Ratio", f"{health['avg_debug_ratio']:.0%}", "", "")
        table.add_row("", "Sessions", f"{health['total_session_hours']:.1f}h", "", "")

    deadline = project.get("deadline") or ""
    title = f"{project_name}"
    if deadline:
        title += f"  ·  {deadline}"
    return Panel(table, title=title, border_style="cyan", padding=(0, 1))
