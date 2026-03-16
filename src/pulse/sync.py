"""Pulse sync — one-way sync from .md project states to SQLite.

Reads structured markdown files from the orchestrator projects directory,
parses project metadata and todos, and upserts into the Pulse database.
"""

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pulse.config import config as _cfg
from pulse.db import PulseDB

_ORCHESTRATOR_DIR = Path(_cfg.orchestrator_dir)

SKIP_FILES = {"_template.md"}

SECTION_MAP = {
    "status": ["## Status"],
    "open_todos": [
        "## Offene Todos",
        "## Naechste Schritte",
        "## Offene Fragen",
        "## Offene Punkte",
    ],
    "done_todos": ["## Erledigte Todos", "## Erledigt"],
    "notes": ["## Problemdefinition"],
}


@dataclass
class ParsedProject:
    """Structured data extracted from a .md project state file."""

    name: str
    source_path: str
    phase: str = ""
    status: str = "active"
    blocked: bool = False
    open_todos: list[str] = field(default_factory=list)
    done_todos: list[str] = field(default_factory=list)
    total_tasks: int = 0
    completed_tasks: int = 0
    notes: str | None = None
    mtime: float = 0.0


def parse_project_state(path: Path) -> ParsedProject:
    """Parse a .md project state file into a ParsedProject."""
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    name = path.stem.replace("_", "-")
    mtime = path.stat().st_mtime

    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    phase_from_heading = ""

    for line in lines:
        matched = False
        if line.startswith("## "):
            for section_key, headings in SECTION_MAP.items():
                for heading in headings:
                    if line.startswith(heading):
                        rest = line[len(heading):].strip()
                        if rest.startswith(":"):
                            rest = rest[1:].strip()
                        if section_key == "status" and rest:
                            phase_from_heading = rest
                        current_section = section_key
                        sections.setdefault(section_key, [])
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                current_section = None
            continue

        if current_section is not None:
            sections.setdefault(current_section, []).append(line)

    # Extract phase from status section
    phase = ""
    blocked = False
    status_lines = sections.get("status", [])
    for sl in status_lines:
        if "**Phase:**" in sl:
            phase = sl.split("**Phase:**")[-1].strip()
        elif "**Blockiert:**" in sl:
            blocked_text = sl.split("**Blockiert:**")[-1].strip().lower()
            blocked = blocked_text.startswith("ja")

    # Fallback: phase from heading text ("## Status: In Arbeit")
    if not phase and phase_from_heading:
        phase = phase_from_heading

    # Fallback: standalone "**Status:** Text" line (not inside a ## section)
    if not phase:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("**Status:**") and not line.startswith("##"):
                phase = stripped.split("**Status:**")[-1].strip()
                break

    # Extract todos
    open_todos = _extract_todos(sections.get("open_todos", []), checked=False)
    done_todos = _extract_todos(sections.get("done_todos", []), checked=True)

    # Extract notes from Problemdefinition
    notes = None
    for nl in sections.get("notes", []):
        if "**Was:**" in nl:
            notes = nl.split("**Was:**")[-1].strip()
            break

    status = _derive_status(phase, blocked)

    return ParsedProject(
        name=name,
        source_path=str(path.resolve()),
        phase=phase,
        status=status,
        blocked=blocked,
        open_todos=open_todos,
        done_todos=done_todos,
        total_tasks=len(open_todos) + len(done_todos),
        completed_tasks=len(done_todos),
        notes=notes,
        mtime=mtime,
    )


def _derive_status(phase: str, blocked: bool) -> str:
    """Derive project status from phase text and blocked flag."""
    phase_lower = phase.lower()

    # Active indicators take priority — e.g. "In Arbeit — Bestandsaufnahme komplett"
    # should remain active even if "komplett" appears as a sub-phrase.
    if any(w in phase_lower for w in ["in arbeit", "aktiv", "laufend", "in progress"]):
        if blocked:
            return "paused"
        return "active"

    if any(w in phase_lower for w in ["komplett", "complete", "fertig", "done", "abgeschlossen"]):
        return "done"
    if blocked or any(w in phase_lower for w in ["pausiert", "paused", "warte"]):
        return "paused"
    return "active"


def _extract_todos(lines: list[str], checked: bool) -> list[str]:
    """Extract todo items from section lines."""
    todos: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if checked:
            if stripped.startswith("- [x]") or stripped.startswith("- [X]"):
                text = stripped[5:].strip()
                text = _clean_todo_text(text)
                if text:
                    todos.append(text)
        else:
            if stripped.startswith("- [ ]"):
                text = stripped[5:].strip()
                text = _clean_todo_text(text)
                if text:
                    todos.append(text)
            elif re.match(r"^\d+\.\s*\[?\s*\]?\s*", stripped):
                text = re.sub(r"^\d+\.\s*\[?\s*\]?\s*", "", stripped).strip()
                text = _clean_todo_text(text)
                if text:
                    todos.append(text)

    return todos


def _clean_todo_text(text: str) -> str:
    """Clean markdown formatting from todo text."""
    text = text.replace("**", "")
    return text.strip()


def _normalize_task_name(name: str) -> str:
    """Normalize task name for matching: lowercase, strip, remove markdown."""
    return name.lower().strip().replace("**", "").replace("*", "")


def _now_iso() -> str:
    """Current local time as naive ISO string."""
    return datetime.now().isoformat()


def scan_project_files(orchestrator_dir: str | None = None) -> list[Path]:
    """Find all .md project files, excluding skip list."""
    directory = Path(orchestrator_dir) if orchestrator_dir else _ORCHESTRATOR_DIR
    if not directory.exists():
        return []
    return [
        f for f in sorted(directory.glob("*.md"))
        if f.name not in SKIP_FILES
    ]


def needs_sync(path: Path, db: PulseDB) -> bool:
    """True if .md file is newer than the last sync timestamp."""
    project_name = path.stem.replace("_", "-")
    project = db.get_project(project_name)
    if project is None:
        return True
    last_synced = project.get("md_last_synced")
    if last_synced is None:
        return True
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
    synced_at = datetime.fromisoformat(last_synced)
    return file_mtime > synced_at


def sync_project(parsed: ParsedProject, db: PulseDB) -> str:
    """Sync a parsed project state into the database. Returns 'created' or 'updated'."""
    existing = db.get_project(parsed.name)

    if existing is None:
        db.add_project(
            name=parsed.name,
            path=str(Path(parsed.source_path).parent),
            total_tasks=parsed.total_tasks,
            completed_tasks=parsed.completed_tasks,
            status=parsed.status,
            notes=parsed.notes,
            md_source_path=parsed.source_path,
            md_last_synced=_now_iso(),
        )
        result = "created"
    else:
        db.update_project(
            parsed.name,
            total_tasks=parsed.total_tasks,
            completed_tasks=parsed.completed_tasks,
            status=parsed.status,
            md_source_path=parsed.source_path,
            md_last_synced=_now_iso(),
        )
        result = "updated"

    project = db.get_project(parsed.name)
    if project:
        _sync_tasks(parsed, project["id"], db)

    return result


def _sync_tasks(parsed: ParsedProject, project_id: int, db: PulseDB) -> None:
    """Sync open and done todos as tasks."""
    existing_tasks = db.get_tasks(project_id)
    existing_map = {_normalize_task_name(t["name"]): t for t in existing_tasks}

    for todo in parsed.open_todos:
        key = _normalize_task_name(todo)
        if key not in existing_map:
            db.add_task(project_id=project_id, name=todo)

    for todo in parsed.done_todos:
        key = _normalize_task_name(todo)
        if key in existing_map:
            task = existing_map[key]
            if task["status"] != "done":
                db.update_task(task["id"], status="done", completed_at=_now_iso())
        else:
            task_id = db.add_task(project_id=project_id, name=todo)
            db.update_task(task_id, status="done", completed_at=_now_iso())


def sync_all(db: PulseDB, force: bool = False, orchestrator_dir: str | None = None) -> dict:
    """Sync all .md project files into the database.

    Returns: {"total": N, "synced": N, "created": N, "updated": N, "errors": N}
    """
    files = scan_project_files(orchestrator_dir)
    stats = {"total": len(files), "synced": 0, "created": 0, "updated": 0, "errors": 0}

    for path in files:
        if not force and not needs_sync(path, db):
            continue
        try:
            parsed = parse_project_state(path)
            result = sync_project(parsed, db)
            stats["synced"] += 1
            stats[result] += 1
        except Exception as e:
            print(f"Warning: Failed to sync {path.name}: {e}", file=sys.stderr)
            stats["errors"] += 1

    return stats


def get_next_step(db: PulseDB, project_name: str) -> str:
    """Get the first open todo for a project from the database."""
    project = db.get_project(project_name)
    if not project:
        return "Kein naechster Schritt definiert."

    tasks = db.get_tasks(project["id"])
    pending = [t for t in tasks if t["status"] == "pending"]
    if pending:
        return pending[0]["name"]
    return "Kein naechster Schritt definiert."
