"""Pulse CLI — Command-line interface for Pulse.

Commands:
    pulse collect --event <type>   Hook handler (called by Claude Code hooks)
    pulse install                  Install hooks into Claude Code settings
    pulse uninstall                Remove hooks from Claude Code settings
    pulse add <name> <path>        Register a project
    pulse status                   Show all projects
    pulse project <name>           Show project details
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

    args = parser.parse_args(argv)

    if args.command == "collect":
        _cmd_collect(args)
    elif args.command == "install":
        _cmd_install()
    elif args.command == "uninstall":
        _cmd_uninstall()
    elif args.command == "add":
        _cmd_add(args)
    elif args.command == "status":
        _cmd_status()
    elif args.command == "project":
        _cmd_project(args)
    elif args.command == "task":
        _cmd_task(args)
    else:
        parser.print_help()


def _cmd_collect(args: argparse.Namespace) -> None:
    """Handle the collect command — read from stdin, write to DB."""
    collect(event_type=args.event)


def _cmd_install() -> None:
    """Install Pulse hooks into Claude Code settings."""
    install_hooks()
    print("Pulse hooks installed in Claude Code settings.")


def _cmd_uninstall() -> None:
    """Remove Pulse hooks from Claude Code settings."""
    uninstall_hooks()
    print("Pulse hooks removed from Claude Code settings.")


def _cmd_add(args: argparse.Namespace) -> None:
    """Register a new project."""
    db = PulseDB(_DEFAULT_DB_PATH)
    path = str(Path(args.path).expanduser().resolve())
    db.add_project(
        name=args.name,
        path=path,
        deadline=args.deadline,
        total_tasks=args.tasks,
        status=args.status,
    )
    print(f"Project '{args.name}' registered at {path}")
    if args.deadline:
        print(f"  Deadline: {args.deadline}")
    if args.tasks:
        print(f"  Tasks: {args.tasks}")


def _cmd_status() -> None:
    """Show status of all projects."""
    db = PulseDB(_DEFAULT_DB_PATH)
    projects = db.execute("SELECT * FROM projects ORDER BY status, name").fetchall()

    if not projects:
        print("No projects registered. Use 'pulse add <name> <path>' to register one.")
        return

    status_icons = {"active": "🟢", "paused": "🟡", "done": "✅"}

    for p in projects:
        p = dict(p)
        icon = status_icons.get(p["status"], "⚪")
        tasks = ""
        if p["total_tasks"]:
            tasks = f"  {p['completed_tasks'] or 0}/{p['total_tasks']} tasks"
        deadline = ""
        if p["deadline"]:
            deadline = f"  deadline: {p['deadline']}"
        print(f"  {icon} {p['name']:<20}{tasks}{deadline}")


def _cmd_project(args: argparse.Namespace) -> None:
    """Show details for a specific project."""
    db = PulseDB(_DEFAULT_DB_PATH)
    project = db.get_project(args.name)

    if not project:
        print(f"Project '{args.name}' not found.")
        sys.exit(1)

    print(f"\n  Project: {project['name']}")
    print(f"  Path:    {project['path']}")
    print(f"  Status:  {project['status']}")
    if project["deadline"]:
        print(f"  Deadline: {project['deadline']}")
    if project["total_tasks"]:
        done = project["completed_tasks"] or 0
        total = project["total_tasks"]
        pct = (done / total * 100) if total > 0 else 0
        bar_len = 30
        filled = int(bar_len * done / total) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"  Progress: {bar} {done}/{total} ({pct:.0f}%)")

    # Show tasks
    pid = project["id"]
    tasks = db.get_tasks(pid)
    if tasks:
        print(f"\n  Tasks:")
        status_icons = {"pending": "⬜", "in_progress": "🔄", "done": "✅", "blocked": "🚫"}
        for t in tasks:
            icon = status_icons.get(t["status"], "⬜")
            duration = ""
            if t["actual_minutes"]:
                duration = f"  {t['actual_minutes']:.0f} min"
            debug = ""
            if t["debug_cycles"]:
                debug = f"  {t['debug_cycles']} debug"
            print(f"    {icon} {t['name']}{duration}{debug}")

    # Show recent sessions
    sessions = db.get_recent_sessions(project["path"], limit=3)
    if sessions:
        print(f"\n  Recent sessions:")
        for s in sessions:
            duration = ""
            if s["duration_seconds"]:
                mins = s["duration_seconds"] / 60
                duration = f"  {mins:.0f} min"
            print(f"    {s['started_at'] or '?'}{duration}  prompts: {s['prompt_count']}")

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
        # Update project completed count
        done_count = len([t for t in tasks if t["status"] == "done"]) + 1
        db.update_project(args.project, completed_tasks=done_count)
        print(f"Task '{args.task_name}' marked as done.")

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
        print(f"Task '{args.task_name}' added to project '{args.project}'.")

    else:
        print("Usage: pulse task {done|add} <project> <task_name>")
