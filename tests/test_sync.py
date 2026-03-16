"""Tests for pulse.sync — .md project state parser and sync logic."""

import time
from datetime import datetime
from pathlib import Path

import pytest

from pulse.db import PulseDB
from pulse.sync import (
    ParsedProject,
    get_next_step,
    needs_sync,
    parse_project_state,
    scan_project_files,
    sync_all,
    sync_project,
)


# -- Fixtures: realistic .md content from real project files --

PULSE_MD = """\
# Pulse — Measurement & Live-Planning Agent fuer Claude Code

## Problemdefinition
- **Was:** CLI-Tool das ueber Claude Code Hooks Session-Metriken sammelt.

## Status
- **Phase:** MVP aktiv — Hooks live, Dashboard laeuft
- **Fortschritt:** 114 Tests, 15 Commits
- **Blockiert:** Nein

## Offene Todos
1. [ ] **md-Sync:** Pulse liest .md-Projekt-States als Source of Truth
2. [ ] **Kosten/Token-Tracking:** Session-Kosten erfassen
3. [ ] export.py (Obsidian-Export)

## Erledigte Todos
- [x] Repo + Projektstruktur
- [x] db.py + 26 Tests
- [x] collector.py + 23 Tests
"""

CURVE2CHARGER_MD = """\
# Projekt-State: Curve2Charger DE

## Status
- **Phase:** Feature-Complete + Export-Paket (16.03.2026)
- **Fortschritt:** 10 Seiten + 800 Vehicle-Details
- **Blockiert:** Nein

## Offene Punkte
- Keine offenen Punkte.
"""

TEMPLATE_MD = """\
# Projekt-State: [Projektname]

## Status
- **Phase:** [Aktuelle Phase / Meilenstein]
- **Blockiert:** [Ja/Nein]

## Naechste Schritte
1. Erster Schritt
2. Zweiter Schritt
3. Dritter Schritt
"""

MINIMAL_MD = """\
# Mein Projekt

Nur ein Heading, keine Sektionen.
"""

STATUS_ON_HEADING_MD = """\
# Versicherungen

## Status: In Arbeit — Bestandsaufnahme komplett, Analyse folgt

Hier kommt der Inhalt.
"""

STANDALONE_STATUS_MD = """\
# AI Fluency

**Status:** Phase 1 MVP — Done + Visual Redesign

## Offene Todos
- [ ] Phase 2 planen
"""

BLOCKED_MD = """\
# Blocked Project

## Status
- **Phase:** Warte auf Review
- **Blockiert:** Ja — Review ausstehend

## Offene Todos
- [ ] Review abwarten
"""


def test_parse_pulse_format(tmp_path):
    """Parse pulse.md with Offene Todos + Erledigte Todos."""
    p = tmp_path / "pulse.md"
    p.write_text(PULSE_MD)
    result = parse_project_state(p)

    assert result.name == "pulse"
    assert result.status == "active"
    assert result.phase == "MVP aktiv — Hooks live, Dashboard laeuft"
    assert result.blocked is False
    assert len(result.open_todos) == 3
    assert "md-Sync: Pulse liest .md-Projekt-States als Source of Truth" in result.open_todos[0]
    assert len(result.done_todos) == 3
    assert result.total_tasks == 6
    assert result.completed_tasks == 3
    assert result.notes == "CLI-Tool das ueber Claude Code Hooks Session-Metriken sammelt."


def test_parse_curve2charger_format(tmp_path):
    """Parse complex project with Feature-Complete status."""
    p = tmp_path / "curve2charger.md"
    p.write_text(CURVE2CHARGER_MD)
    result = parse_project_state(p)

    assert result.name == "curve2charger"
    assert result.status == "done"  # "Feature-Complete" contains "complete"
    assert "Feature-Complete" in result.phase
    assert result.blocked is False
    assert len(result.open_todos) == 0  # "Keine offenen Punkte." is not a todo


def test_parse_template_format(tmp_path):
    """Parse template with Naechste Schritte section."""
    p = tmp_path / "test-project.md"
    p.write_text(TEMPLATE_MD)
    result = parse_project_state(p)

    assert result.name == "test-project"
    assert len(result.open_todos) == 3
    assert result.open_todos[0] == "Erster Schritt"


def test_parse_minimal(tmp_path):
    """Parse .md with just a heading, no sections."""
    p = tmp_path / "minimal.md"
    p.write_text(MINIMAL_MD)
    result = parse_project_state(p)

    assert result.name == "minimal"
    assert result.status == "active"  # default
    assert result.phase == ""
    assert result.open_todos == []
    assert result.done_todos == []


def test_parse_status_on_heading(tmp_path):
    """Parse '## Status: Text' format where status is on the heading line."""
    p = tmp_path / "versicherungen.md"
    p.write_text(STATUS_ON_HEADING_MD)
    result = parse_project_state(p)

    assert result.status == "active"
    assert "In Arbeit" in result.phase


def test_parse_standalone_status(tmp_path):
    """Parse '**Status:** Text' as standalone bold line without ## heading."""
    p = tmp_path / "ai-fluency.md"
    p.write_text(STANDALONE_STATUS_MD)
    result = parse_project_state(p)

    assert result.status == "done"  # "Done" in the status text
    assert "Phase 1 MVP" in result.phase
    assert len(result.open_todos) == 1


def test_derive_status_active(tmp_path):
    """Phase without completion keywords → active."""
    p = tmp_path / "active.md"
    p.write_text("# Active\n\n## Status\n- **Phase:** In Arbeit\n- **Blockiert:** Nein\n")
    result = parse_project_state(p)
    assert result.status == "active"


def test_derive_status_done(tmp_path):
    """Phase with 'komplett' → done."""
    p = tmp_path / "done.md"
    p.write_text("# Done\n\n## Status\n- **Phase:** Projekt komplett\n- **Blockiert:** Nein\n")
    result = parse_project_state(p)
    assert result.status == "done"


def test_derive_status_paused(tmp_path):
    """blocked=True → paused."""
    p = tmp_path / "blocked.md"
    p.write_text(BLOCKED_MD)
    result = parse_project_state(p)
    assert result.status == "paused"
    assert result.blocked is True


def test_parse_underscore_filename(tmp_path):
    """Underscores in filename are converted to hyphens."""
    p = tmp_path / "my_project.md"
    p.write_text("# My Project\n")
    result = parse_project_state(p)
    assert result.name == "my-project"


# --- Sync logic tests ---


@pytest.fixture
def db(tmp_path):
    """Create a fresh PulseDB in a temp directory."""
    db_path = tmp_path / "test_pulse.db"
    return PulseDB(str(db_path))


def test_needs_sync_new_project(tmp_path, db):
    """New .md file not in DB → needs sync."""
    p = tmp_path / "new-project.md"
    p.write_text("# New Project\n")
    assert needs_sync(p, db) is True


def test_needs_sync_unchanged(tmp_path, db):
    """File mtime older than last_synced → no sync needed."""
    p = tmp_path / "synced.md"
    p.write_text("# Synced\n")

    db.add_project(name="synced", path=str(tmp_path))
    future = datetime(2099, 1, 1).isoformat()
    db.update_project("synced", md_source_path=str(p), md_last_synced=future)

    assert needs_sync(p, db) is False


def test_needs_sync_changed(tmp_path, db):
    """File mtime newer than last_synced → needs sync."""
    p = tmp_path / "changed.md"
    p.write_text("# Changed\n")

    db.add_project(name="changed", path=str(tmp_path))
    past = datetime(2020, 1, 1).isoformat()
    db.update_project("changed", md_source_path=str(p), md_last_synced=past)

    assert needs_sync(p, db) is True


def test_sync_creates_project(tmp_path, db):
    """Syncing a new .md file creates a project in DB."""
    p = tmp_path / "new-proj.md"
    p.write_text(PULSE_MD)
    parsed = parse_project_state(p)

    sync_project(parsed, db)

    project = db.get_project("new-proj")
    assert project is not None
    assert project["status"] == "active"
    assert project["total_tasks"] == 6
    assert project["completed_tasks"] == 3
    assert project["md_source_path"] is not None


def test_sync_updates_project(tmp_path, db):
    """Syncing an existing project updates its fields."""
    db.add_project(name="pulse", path="/Users/jan/Projects/pulse")

    p = tmp_path / "pulse.md"
    p.write_text(PULSE_MD)
    parsed = parse_project_state(p)

    sync_project(parsed, db)

    project = db.get_project("pulse")
    assert project["total_tasks"] == 6
    assert project["completed_tasks"] == 3
    assert project["status"] == "active"
    assert project["md_last_synced"] is not None


def test_sync_preserves_path(tmp_path, db):
    """Syncing does NOT overwrite the existing project path."""
    original_path = "/Users/jan/Projects/pulse"
    db.add_project(name="pulse", path=original_path)

    p = tmp_path / "pulse.md"
    p.write_text(PULSE_MD)
    parsed = parse_project_state(p)

    sync_project(parsed, db)

    project = db.get_project("pulse")
    assert project["path"] == original_path


def test_sync_tasks(tmp_path, db):
    """Todos from .md are synced as tasks."""
    p = tmp_path / "task-project.md"
    p.write_text(PULSE_MD)
    parsed = parse_project_state(p)

    sync_project(parsed, db)

    project = db.get_project("task-project")
    tasks = db.get_tasks(project["id"])
    pending = [t for t in tasks if t["status"] == "pending"]
    done = [t for t in tasks if t["status"] == "done"]
    assert len(pending) == 3
    assert len(done) == 3


def test_skip_template(tmp_path):
    """_template.md is skipped when scanning."""
    (tmp_path / "_template.md").write_text("# Template\n")
    (tmp_path / "real-project.md").write_text("# Real\n")
    files = scan_project_files(str(tmp_path))
    names = [f.name for f in files]
    assert "_template.md" not in names
    assert "real-project.md" in names


def test_get_next_step(tmp_path, db):
    """get_next_step returns first open todo after sync."""
    p = tmp_path / "pulse.md"
    p.write_text(PULSE_MD)
    parsed = parse_project_state(p)
    sync_project(parsed, db)

    step = get_next_step(db, "pulse")
    assert "md-Sync" in step


def test_sync_all_performance(tmp_path):
    """Parsing 30 files completes under 50ms."""
    for i in range(30):
        (tmp_path / f"project-{i}.md").write_text(PULSE_MD)

    start = time.monotonic()
    for p in tmp_path.glob("*.md"):
        parse_project_state(p)
    elapsed = time.monotonic() - start

    assert elapsed < 0.05, f"Parsing 30 files took {elapsed:.3f}s (limit: 0.05s)"
