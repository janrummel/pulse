"""Tests for pulse.sync — .md project state parser and sync logic."""

from pathlib import Path

import pytest

from pulse.sync import ParsedProject, parse_project_state


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
