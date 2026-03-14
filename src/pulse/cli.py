"""Pulse CLI — Command-line interface for Pulse.

Commands:
    pulse collect --event <type>   Hook handler (called by Claude Code hooks)
    pulse install                  Install hooks into Claude Code settings
    pulse uninstall                Remove hooks from Claude Code settings
    pulse add <name> <path>        Register a project
    pulse status                   Show all projects (Rich)
    pulse project <name>           Show project details (Rich)
    pulse metrics [project]        Show metrics for a project
    pulse priority                 Show priority ranking
    pulse dashboard                Live TUI dashboard
    pulse task done <project> <task>  Mark a task as done
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from pulse.collector import collect
from pulse.db import PulseDB
from pulse.hooks import install_hooks, uninstall_hooks

_DEFAULT_DB_PATH = str(Path.home() / ".pulse" / "pulse.db")


def main(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(prog="pulse", description="Pulse — Claude Code session metrics")
    sub = parser.add_subparsers(dest="command")

    # collect
    p_collect = sub.add_parser("collect", help="Hook handler: collect events from stdin")
    p_collect.add_argument("--event", required=True, help="Hook event type")

    # install / uninstall
    sub.add_parser("install", help="Install hooks into Claude Code settings")
    sub.add_parser("uninstall", help="Remove hooks from Claude Code settings")

    # add
    p_add = sub.add_parser("add", help="Register a project")
    p_add.add_argument("name", help="Project name")
    p_add.add_argument("path", help="Project directory path")
    p_add.add_argument("--deadline", help="Deadline (ISO datetime)")
    p_add.add_argument("--tasks", type=int, help="Total number of tasks")
    p_add.add_argument("--status", default="active", choices=["active", "paused", "done"])
    p_add.add_argument("--category", default="tools",
                       choices=["tools", "learning", "system", "research", "content", "career"])
    p_add.add_argument("--type", dest="project_type", default="one-time",
                       choices=["one-time", "continuous"])

    # portfolio
    sub.add_parser("portfolio", help="Full project portfolio overview")

    # status
    sub.add_parser("status", help="Show all projects")

    # project
    p_project = sub.add_parser("project", help="Show project details")
    p_project.add_argument("name", help="Project name")

    # task
    p_task = sub.add_parser("task", help="Manage tasks")
    p_task_sub = p_task.add_subparsers(dest="task_action")
    p_task_done = p_task_sub.add_parser("done", help="Mark a task as done")
    p_task_done.add_argument("project", help="Project name")
    p_task_done.add_argument("task_name", help="Task name")

    # task add
    p_task_add = p_task_sub.add_parser("add", help="Add a task to a project")
    p_task_add.add_argument("project", help="Project name")
    p_task_add.add_argument("task_name", help="Task name")
    p_task_add.add_argument("--estimate", type=float, help="Estimated minutes")

    # recap
    p_recap = sub.add_parser("recap", help="Daily or weekly recap")
    p_recap.add_argument("--week", action="store_true", help="Show weekly recap")
    p_recap.add_argument("--date", help="Date for daily recap (YYYY-MM-DD)")

    # track
    p_track = sub.add_parser("track", help="Detect and apply task completions")
    p_track.add_argument("--session", help="Session ID (default: most recent)")
    p_track.add_argument("--apply", action="store_true", help="Auto-apply high-confidence signals")
    p_track.add_argument("--min-confidence", type=float, default=0.7, help="Min confidence for auto-apply")

    # feedback
    p_fb = sub.add_parser("feedback", help="Feedback erfassen oder anzeigen")
    p_fb.add_argument("text", nargs="?", help="Feedback-Text")
    p_fb.add_argument("--list", action="store_true", help="Alle Feedbacks anzeigen")

    # launch
    sub.add_parser("launch", help="Interactive project launcher")

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Live TUI dashboard")
    p_dash.add_argument("--db", help="DB path (default: ~/.pulse/pulse.db)")

    # metrics
    p_metrics = sub.add_parser("metrics", help="Show metrics snapshot")
    p_metrics.add_argument("project", nargs="?", help="Project name (optional)")

    # priority
    sub.add_parser("priority", help="Show priority ranking")

    args = parser.parse_args(argv)

    if args.command is None:
        # No subcommand → unified Pulse app
        from pulse.app import run_app
        run_app()
        return
    elif args.command == "collect":
        _cmd_collect(args)
    elif args.command == "install":
        _cmd_install()
    elif args.command == "uninstall":
        _cmd_uninstall()
    elif args.command == "add":
        _cmd_add(args)
    elif args.command == "portfolio":
        _cmd_portfolio()
    elif args.command == "status":
        _cmd_status()
    elif args.command == "project":
        _cmd_project(args)
    elif args.command == "task":
        _cmd_task(args)
    elif args.command == "recap":
        _cmd_recap(args)
    elif args.command == "track":
        _cmd_track(args)
    elif args.command == "feedback":
        _cmd_feedback(args)
    elif args.command == "launch":
        _cmd_launch()
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "metrics":
        _cmd_metrics(args)
    elif args.command == "priority":
        _cmd_priority()
    else:
        parser.print_help()


def _cmd_collect(args: argparse.Namespace) -> None:
    """Handle the collect command — read from stdin, write to DB."""
    collect(event_type=args.event)


def _cmd_install() -> None:
    """Install Pulse hooks into Claude Code settings."""
    install_hooks()
    print("  ✓ Hooks installiert")


def _cmd_uninstall() -> None:
    """Remove Pulse hooks from Claude Code settings."""
    uninstall_hooks()
    print("  ✓ Hooks entfernt")


def _cmd_add(args: argparse.Namespace) -> None:
    """Register a new project."""
    from pulse import theme

    db = PulseDB(_DEFAULT_DB_PATH)
    path = str(Path(args.path).expanduser().resolve())
    db.add_project(
        name=args.name,
        path=path,
        deadline=args.deadline,
        total_tasks=args.tasks,
        status=args.status,
        category=args.category,
        project_type=args.project_type,
    )
    dot = theme.STATUS_DOT.get(args.status, "·")
    cont = " ↻" if args.project_type == "continuous" else ""
    print(f"  {dot} {args.name}{cont}  → {path}")


def _cmd_portfolio() -> None:
    """Full portfolio overview grouped by category — uses theme.py."""
    from rich.console import Console
    from pulse import theme

    db = PulseDB(_DEFAULT_DB_PATH)
    console = Console()

    projects = db.execute("SELECT * FROM projects ORDER BY category, status DESC, name").fetchall()
    if not projects:
        console.print("  Keine Projekte registriert.")
        return

    cats: dict[str, list] = {}
    for p in projects:
        p = dict(p)
        cats.setdefault(p.get("category") or "tools", []).append(p)

    console.print()
    counts = {"active": 0, "paused": 0, "done": 0}

    for cat_key in ["tools", "learning", "system", "research", "content", "career"]:
        if cat_key not in cats:
            continue

        label = theme.CATEGORY_LABEL.get(cat_key, cat_key)
        console.print(f"  [bold cyan]{label}[/bold cyan]")

        for p in cats[cat_key]:
            status = p["status"]
            dot = theme.STATUS_DOT.get(status, "·")
            style = theme.STATUS_STYLE.get(status, "")
            cont = " ↻" if p.get("project_type") == "continuous" else ""
            counts[status] = counts.get(status, 0) + 1

            done = p.get("completed_tasks") or 0
            total = p.get("total_tasks") or 0
            progress = ""
            if total > 0 and status != "done":
                progress = f"  {theme.bar(done / total * 100, 100, 6)} {done}/{total}"

            console.print(f"  [{style}]{dot} {p['name']}{cont}{progress}[/{style}]")

        console.print()

    console.print(f"  [green]{counts.get('active', 0)} aktiv[/green]  "
                  f"[yellow]{counts.get('paused', 0)} pausiert[/yellow]  "
                  f"[dim]{counts.get('done', 0)} fertig[/dim]")
    console.print()


def _cmd_status() -> None:
    """Show status of all projects."""
    from pulse import theme

    db = PulseDB(_DEFAULT_DB_PATH)
    projects = db.execute("SELECT * FROM projects ORDER BY status, name").fetchall()

    if not projects:
        print("  Keine Projekte. Nutze 'pulse add <name> <path>'.")
        return

    print()
    for p in projects:
        p = dict(p)
        dot = theme.STATUS_DOT.get(p["status"], "·")
        tasks = ""
        if p.get("total_tasks"):
            done = p.get("completed_tasks") or 0
            tasks = f"  {done}/{p['total_tasks']}"
        print(f"  {dot} {p['name']:<20}{tasks}")
    print()


def _cmd_project(args: argparse.Namespace) -> None:
    """Show details for a specific project."""
    from pulse import theme

    db = PulseDB(_DEFAULT_DB_PATH)
    project = db.get_project(args.name)

    if not project:
        print(f"  Projekt '{args.name}' nicht gefunden.")
        sys.exit(1)

    dot = theme.STATUS_DOT.get(project["status"], "·")
    print(f"\n  {dot} {project['name']}")
    print(f"  {project['path']}")
    if project["deadline"]:
        print(f"  → {project['deadline']}")
    if project["total_tasks"]:
        done = project["completed_tasks"] or 0
        total = project["total_tasks"]
        print(f"  {theme.bar(done / total * 100 if total else 0, 100, 20)} {done}/{total}")

    # Tasks
    tasks = db.get_tasks(project["id"])
    if tasks:
        print()
        for t in tasks:
            marker = theme.TASK_MARKER.get(t["status"], " ")
            duration = f"  {theme.duration_human(t['actual_minutes'])}" if t.get("actual_minutes") else ""
            debug = f"  {t['debug_cycles']} debug" if t.get("debug_cycles") else ""
            print(f"  {marker} {t['name']}{duration}{debug}")

    # Recent sessions
    sessions = db.get_recent_sessions(project["path"], limit=3)
    if sessions:
        print()
        for s in sessions:
            ago = theme.time_ago(s["started_at"]) if s.get("started_at") else "?"
            duration = theme.duration_human(s["duration_seconds"] / 60) if s.get("duration_seconds") else ""
            print(f"  · {ago}  {duration}  {s['prompt_count']} prompts")

    print()


def _cmd_task(args: argparse.Namespace) -> None:
    """Handle task subcommands."""
    db = PulseDB(_DEFAULT_DB_PATH)

    if args.task_action == "done":
        project = db.get_project(args.project)
        if not project:
            print(f"Project '{args.project}' not found.")
            sys.exit(1)
        tasks = db.get_tasks(project["id"])
        matching = [t for t in tasks if t["name"] == args.task_name]
        if not matching:
            print(f"Task '{args.task_name}' not found in project '{args.project}'.")
            sys.exit(1)
        task = matching[0]
        db.update_task(task["id"], status="done", completed_at=datetime.now().isoformat())
        done_count = len([t for t in tasks if t["status"] == "done"]) + 1
        db.update_project(args.project, completed_tasks=done_count)
        print(f"  ✓ {args.task_name}")

    elif args.task_action == "add":
        project = db.get_project(args.project)
        if not project:
            print(f"Project '{args.project}' not found.")
            sys.exit(1)
        db.add_task(
            project_id=project["id"],
            name=args.task_name,
            estimated_minutes=args.estimate,
        )
        print(f"  + {args.task_name}")

    else:
        print("Usage: pulse task {done|add} <project> <task_name>")


def _cmd_recap(args: argparse.Namespace) -> None:
    """Show daily or weekly recap."""
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from pulse.analyzer import Analyzer

    db = PulseDB(_DEFAULT_DB_PATH)
    analyzer = Analyzer(db)
    console = Console()

    if args.week:
        recap = analyzer.weekly_recap()

        console.print()
        console.print(f"[bold]Wochen-Recap: {recap['period']}[/bold]")
        console.print()

        table = Table(show_header=True, box=rich_box.SIMPLE)
        table.add_column("Metrik", width=20)
        table.add_column("Wert", width=12, justify="right")
        table.add_column("Trend", width=18)

        table.add_row("Tasks erledigt", str(recap["total_tasks_completed"]), recap["trend_tasks"])
        table.add_row("Arbeitszeit", f"{recap['total_minutes']:.0f} min", recap["trend_minutes"])
        table.add_row("Sessions", str(recap["total_sessions"]), "")
        table.add_row("Debug-Zyklen", str(recap["total_debug_cycles"]), recap["trend_debug"])
        table.add_row("Dateien bearbeitet", str(recap["files_touched"]), "")

        console.print(table)

        # Daily breakdown
        console.print()
        day_table = Table(title="Tage", show_header=True, box=rich_box.SIMPLE)
        day_table.add_column("Tag", width=12)
        day_table.add_column("Tasks", width=6, justify="right")
        day_table.add_column("Zeit", width=8, justify="right")
        day_table.add_column("Debug", width=6, justify="right")

        for d in reversed(recap["days"]):
            tasks = len(d["tasks_completed"])
            style = "green" if tasks > 0 else "dim" if d["total_minutes"] == 0 else ""
            day_table.add_row(
                d["date"],
                str(tasks),
                f"{d['total_minutes']:.0f} min" if d["total_minutes"] > 0 else "—",
                str(d["debug_cycles"]) if d["debug_cycles"] > 0 else "—",
                style=style,
            )

        console.print(day_table)
    else:
        recap = analyzer.daily_recap(args.date)

        tasks_done = len(recap["tasks_completed"])
        console.print()

        if tasks_done > 0:
            console.print(f"[bold green]  {tasks_done} Tasks erledigt[/bold green]  am {recap['date']}")
        else:
            console.print(f"[bold]  Recap fuer {recap['date']}[/bold]")

        console.print()

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold cyan", width=16)
        table.add_column(width=12)

        table.add_row("Sessions", str(recap["sessions"]))
        table.add_row("Arbeitszeit", f"{recap['total_minutes']:.0f} min")
        table.add_row("Prompts", str(recap["prompts"]))
        table.add_row("Tool-Calls", str(recap["tool_calls"]))
        table.add_row("Debug-Zyklen", str(recap["debug_cycles"]))
        table.add_row("Think-Time", f"{recap['think_time_pct']:.0f}%")
        table.add_row("Dateien", str(len(recap["files_touched"])))

        console.print(table)

        if recap["tasks_completed"]:
            console.print()
            console.print("[bold]  Erledigte Tasks:[/bold]")
            for tc in recap["tasks_completed"]:
                console.print(f"    ✅ {tc['task']}  ({tc['project']})")

        if recap["grouped_activity"]:
            console.print()
            console.print("[bold]  Prompt-Runden:[/bold]")
            for g in recap["grouped_activity"][-6:]:
                try:
                    t = datetime.fromisoformat(g["start"]).strftime("%H:%M")
                except (ValueError, TypeError):
                    t = "?"
                prompt = (g.get("prompt") or "")[:50]
                calls = g["tool_calls"]
                errors = g["errors"]
                icon = "⚠️" if errors > 0 else "✅"
                console.print(f"    {t}  {icon}  {prompt}  [{calls} calls]")

    console.print()


def _cmd_track(args: argparse.Namespace) -> None:
    """Detect and optionally apply task completion signals."""
    from rich.console import Console
    from rich.table import Table

    from pulse.tracker import TaskTracker

    db = PulseDB(_DEFAULT_DB_PATH)
    tracker = TaskTracker(db)

    # Find session ID
    session_id = args.session
    if not session_id:
        row = db.execute(
            "SELECT session_id FROM events ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not row:
            print("Keine Events gefunden.")
            return
        session_id = row["session_id"]

    signals = tracker.detect_signals(session_id)

    if not signals:
        print("Keine Task-Completion-Signale erkannt.")
        return

    console = Console()
    table = Table(title=f"Task Signals  (Session: {session_id[:12]}...)")
    table.add_column("Task", width=20)
    table.add_column("Signal", width=20)
    table.add_column("Conf.", width=6, justify="right")
    table.add_column("Evidenz", width=40)

    for s in signals:
        conf_style = "bold green" if s.confidence >= 0.7 else "yellow" if s.confidence >= 0.5 else "dim"
        table.add_row(s.task_name, s.signal_type, f"{s.confidence:.1f}", s.evidence, style=conf_style)

    console.print()
    console.print(table)

    if args.apply:
        applied = tracker.apply_signals(signals, min_confidence=args.min_confidence)
        if applied:
            console.print(f"\n[green]{len(applied)} Task(s) als done markiert.[/green]")
            for a in applied:
                console.print(f"  ✅ {a.task_name} ({a.signal_type}, {a.confidence:.1f})")
        else:
            console.print(f"\n[dim]Keine Signale ueber Confidence {args.min_confidence}.[/dim]")
    else:
        console.print("\n[dim]Nutze --apply um Tasks automatisch als done zu markieren.[/dim]")
    console.print()


def _cmd_feedback(args: argparse.Namespace) -> None:
    """Capture or list feedback."""
    db = PulseDB(_DEFAULT_DB_PATH)

    # Ensure feedback table exists
    db.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            text TEXT NOT NULL
        )
    """)

    if args.list:
        rows = db.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
        if not rows:
            print("  Noch kein Feedback.")
            return
        print()
        for r in rows:
            r = dict(r)
            print(f"  · {r['created_at'][:10]}  {r['text']}")
        print(f"\n  {len(rows)} Eintraege.\n")
    elif args.text:
        db.execute("INSERT INTO feedback (text) VALUES (?)", (args.text,))
        db.execute("COMMIT")
        print("  ✓ Gespeichert")
    else:
        print("  pulse feedback \"text\"  |  pulse feedback --list")


def _cmd_launch() -> None:
    """Launch the interactive project launcher."""
    from pulse.launcher import run_launcher
    run_launcher()


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Launch the live TUI dashboard."""
    from pulse.dashboard import run_dashboard
    db_path = args.db or _DEFAULT_DB_PATH
    run_dashboard(db_path)


def _cmd_metrics(args: argparse.Namespace) -> None:
    """Show metrics snapshot."""
    from pulse.dashboard import print_snapshot
    print_snapshot(_DEFAULT_DB_PATH, project_name=args.project)


def _cmd_priority() -> None:
    """Show priority ranking."""
    from rich.console import Console
    from rich.table import Table

    from pulse.analyzer import Analyzer
    from pulse.planner import Planner

    db = PulseDB(_DEFAULT_DB_PATH)
    analyzer = Analyzer(db)
    planner = Planner(db, analyzer)

    ranking = planner.priority_ranking()
    if not ranking:
        print("Keine Projekte registriert.")
        return

    console = Console()
    table = Table(title="Priority Ranking", show_lines=False)
    table.add_column("#", width=3)
    table.add_column("Projekt", width=20)
    table.add_column("Urgency", width=8, justify="right")
    table.add_column("Grund", width=45)

    for i, entry in enumerate(ranking, 1):
        urgency = entry["urgency"]
        if urgency >= 0.8:
            style = "bold red"
        elif urgency >= 0.5:
            style = "yellow"
        else:
            style = "dim"

        table.add_row(
            str(i),
            entry["project"]["name"],
            f"{urgency:.1f}",
            entry["reason"],
            style=style,
        )

    console.print()
    console.print(table)
    console.print()
