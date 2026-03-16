# md-Sync Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Priority:** 1 (aus Aufklaerungsbriefing)

## Problem

Pulse hat zwei Wahrheiten: `.md`-Projekt-States (manuell gepflegt, reich an Kontext) und die SQLite-DB (automatisch via Hooks, arm an Projekt-Kontext). Die .md-Files enthalten Status, Todos, Entscheidungen — die DB weiss davon nichts. Pulse zeigt deshalb unvollstaendige Projektdaten.

## Ziel

Pulse liest `.md`-Projekt-States als Source of Truth und synchronisiert Projektdaten in die SQLite-DB. One-way: md → SQLite. Kein Rueckschreiben.

## Architektur

Neues Modul `src/pulse/sync.py`:

```
sync.py
├── sync_all(db)              # Scan + Sync aller .md-Files
├── sync_project(path, db)    # Einzelnes Projekt synchronisieren
├── scan_project_files()      # *.md aus orchestrator_dir lesen
├── parse_project_state(path) # Strukturierte Daten extrahieren
└── needs_sync(path, db)      # mtime-Vergleich mit last_synced
```

### Datenfluss

```
~/.claude/orchestrator/projects/*.md
        │
        ▼ parse_project_state()
    ParsedProject (dataclass)
        │
        ▼ sync_to_db()
    SQLite: projects + tasks Tabellen
```

## Parsing

### Eingabe-Formate

Die .md-Files folgen keinem starren Schema. Der Parser muss robust mit Variationen umgehen:

| Feld | Wo in .md | Extraktions-Regel |
|------|-----------|-------------------|
| name | Filename (ohne .md) | `Path.stem`, Underscores → Hyphens |
| status | `## Status` → `**Phase:**` Zeile, oder `**Status:**` Standalone-Zeile, oder Text nach `## Status:` im Heading | Mapping: "Feature-Complete" → done, "Phase X" → active, Default: active |
| phase | Wie status — Rohtext | Rohtext nach `**Phase:**` oder `**Status:**` oder Heading-Text |
| blocked | `## Status` → `**Blockiert:**` Zeile | "Ja" → True, sonst False |
| open_todos | `## Offene Todos` / `## Naechste Schritte` / `## Offene Punkte` | Alle `- [ ]` und `N.` Eintraege |
| done_todos | `## Erledigte Todos` / `## Erledigt` | Alle `- [x]` Eintraege, Zaehlung |
| notes | `## Problemdefinition` → `**Was:**` | Rohtext |

### Parser-Logik

```python
@dataclass
class ParsedProject:
    name: str               # Aus Filename
    source_path: str        # Absoluter Pfad zur .md-Datei
    phase: str              # Rohtext aus Status-Sektion
    status: str             # active / paused / done (abgeleitet)
    blocked: bool           # Aus Blockiert-Zeile
    open_todos: list[str]   # Offene Aufgaben
    done_todos: list[str]   # Erledigte Aufgaben
    total_tasks: int        # len(open) + len(done)
    completed_tasks: int    # len(done)
    notes: str | None       # Problemdefinition
    mtime: float            # File modification time
```

### Sektions-Erkennung

Der Parser arbeitet zeilenweise und erkennt Sektionen an `##`-Headings:

```python
SECTION_MAP = {
    "status": ["## Status"],
    "open_todos": ["## Offene Todos", "## Naechste Schritte", "## Offene Fragen", "## Offene Punkte"],
    "done_todos": ["## Erledigte Todos", "## Erledigt"],
    "notes": ["## Problemdefinition"],
}
```

Zusaetzlich: Fallback-Erkennung fuer Status ausserhalb einer Sektion:

```python
# Variante 1: "## Status: Text auf Heading-Zeile"
# Variante 2: "**Status:** Text" als Standalone-Zeile (kein ## Heading)
# Beide werden als Phase extrahiert wenn keine ## Status-Sektion gefunden wird.
```

Innerhalb einer Sektion werden Zeilen bis zum naechsten `##`-Heading gesammelt.

### Status-Ableitung

Aus der Phase-Zeile wird der DB-Status abgeleitet:

```python
def _derive_status(phase: str, blocked: bool) -> str:
    phase_lower = phase.lower()
    if any(w in phase_lower for w in ["komplett", "complete", "fertig", "done", "abgeschlossen"]):
        return "done"
    if blocked or any(w in phase_lower for w in ["pausiert", "paused", "warte"]):
        return "paused"
    return "active"
```

### Todo-Extraktion

Todos werden aus zwei Formaten erkannt:

```
- [ ] **Bold:** Description   →  "Bold: Description"
- [ ] Plain text              →  "Plain text"
1. [ ] Numbered with checkbox →  "Numbered with checkbox"
1. Plain numbered             →  "Plain numbered"
- [x] Done item               →  (als erledigt gezaehlt)
```

## Datebank-Aenderungen

### Schema-Aenderung

Neue Spalten in `projects` — sowohl in `_SCHEMA` (fuer neue DBs) als auch in `_migrate()` (fuer bestehende DBs):

```sql
-- In _SCHEMA (CREATE TABLE projects):
md_source_path TEXT,
md_last_synced TEXT

-- In _migrate() (ALTER TABLE fuer bestehende DBs):
ALTER TABLE projects ADD COLUMN md_source_path TEXT;
ALTER TABLE projects ADD COLUMN md_last_synced TEXT;
```

- `md_source_path`: Absoluter Pfad zur .md-Datei (NULL = nicht via md-sync verwaltet)
- `md_last_synced`: ISO-Timestamp des letzten erfolgreichen Syncs (naive, lokal)

### Sync-Logik (Upsert)

```python
def sync_project(parsed: ParsedProject, db: PulseDB) -> None:
    existing = db.get_project(parsed.name)
    if existing is None:
        # Neues Projekt anlegen.
        # WICHTIG: path ist das Projekt-Verzeichnis, NICHT die .md-Datei.
        # Fuer neue Projekte die nur via .md entdeckt werden: path = orchestrator_dir
        # (User kann spaeter via `pulse add` den echten Pfad setzen).
        # md_source_path speichert den .md-Pfad separat.
        db.add_project(
            name=parsed.name,
            path=str(Path(parsed.source_path).parent),
            total_tasks=parsed.total_tasks,
            status=parsed.status,
            md_source_path=parsed.source_path,
            md_last_synced=_now_iso(),
        )
    else:
        # Bestehende Felder updaten (md gewinnt fuer Projekt-Metadaten).
        # path wird NICHT ueberschrieben — bleibt das Projekt-Verzeichnis.
        db.update_project(parsed.name,
            total_tasks=parsed.total_tasks,
            completed_tasks=parsed.completed_tasks,
            status=parsed.status,
            md_source_path=parsed.source_path,
            md_last_synced=_now_iso(),
        )
    # Tasks synchronisieren
    _sync_tasks(parsed, db)
```

**Wichtig:** `projects.path` ist das Arbeitsverzeichnis (z.B. `~/Projects/pulse/`), NICHT der Pfad zur .md-Datei. `md_source_path` speichert den .md-Pfad. Bei bestehenden Projekten wird `path` nie ueberschrieben.

### Task-Sync-Strategie

Tasks werden nach normalisiertem Namen gematcht:

```python
def _normalize_task_name(name: str) -> str:
    """Normalisiere Task-Name fuer Matching: lowercase, strip, Markdown entfernen."""
    return name.lower().strip().replace("**", "").replace("*", "")
```

1. Offene Todos aus .md → Tasks mit status=pending (anlegen wenn neu, updaten wenn existierend)
2. Erledigte Todos aus .md → Tasks mit status=done
3. Tasks in DB die nicht mehr in .md stehen → bleiben unveraendert (koennten aus Hooks stammen)
4. Umbenannte Todos in .md → neue Tasks (alte bleiben in DB, kein Rename-Tracking)

## Integration

### Lazy Sync bei CLI-Aufruf

In `cli.py` wird vor jedem Befehl der Projektdaten liest ein Sync ausgeloest:

```python
def _ensure_synced(db: PulseDB) -> None:
    """Sync .md project states if any have changed."""
    from pulse.sync import sync_all
    sync_all(db)
```

Aufrufe: `status`, `project`, `portfolio`, `priority`, `dashboard`, `launch`, `metrics`.

Nicht bei: `collect` (Hook-Handler, Performance-kritisch), `install`/`uninstall`.

### mtime-Check (Performance)

```python
def needs_sync(path: Path, db: PulseDB) -> bool:
    """True wenn .md neuer als letzter Sync."""
    project_name = path.stem.replace("_", "-")
    project = db.get_project(project_name)
    if project is None:
        return True  # Neues Projekt
    last_synced = project.get("md_last_synced")
    if last_synced is None:
        return True  # Noch nie gesynct
    # Beide als naive datetime vergleichen (keine String-Vergleiche)
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime)
    synced_at = datetime.fromisoformat(last_synced)
    return file_mtime > synced_at
```

### Bestehenden Code ersetzen

`launcher.py` (Zeilen 27-63) und `app.py` (Zeilen 33-61) verwenden aktuell jeweils eigene Kopien von `_load_project_context()` und `_extract_next_steps()`. Beide werden durch `sync.py`-Aufrufe ersetzt:

```python
# Vorher (launcher.py:27-63 und app.py:33-61):
context = _load_project_context(project_name)

# Nachher (beide Dateien):
from pulse.sync import get_next_step
context = get_next_step(db, project_name)  # Liest aus DB nach Sync
```

### Dediziertes CLI-Kommando

```
pulse sync [--force]
```

- Ohne `--force`: Nur geaenderte .md-Files
- Mit `--force`: Alle .md-Files neu parsen
- Output: "Synced 3/27 projects (2 new, 1 updated)"

### Skip-Liste

Bestimmte .md-Files werden uebersprungen:

```python
SKIP_FILES = {"_template.md"}
```

## Fehlerbehandlung

- Datei nicht lesbar → Warning auf stderr, weiter mit naechster Datei
- Parse-Fehler in einer Sektion → Sektion leer lassen, Warning auf stderr
- DB-Fehler → Exception hochreichen (kritisch)
- Leere .md-Datei → Projekt mit Defaults anlegen

Logging via `print(..., file=sys.stderr)` — kein logging-Modul noetig fuer ein CLI-Tool.

## Testing

### Unit Tests (`test_sync.py`)

1. `test_parse_pulse_format` — Pulse.md mit Offene Todos + Erledigte Todos
2. `test_parse_template_format` — Template mit Naechste Schritte
3. `test_parse_curve2charger_format` — Komplexes Projekt ohne Checkboxen
4. `test_parse_minimal` — Nur Heading, keine Sektionen
5. `test_derive_status_active` — Phase ohne Completion-Keywords
6. `test_derive_status_done` — Phase mit "komplett"/"complete"
7. `test_derive_status_paused` — blocked=True
8. `test_needs_sync_new_project` — Projekt nicht in DB
9. `test_needs_sync_unchanged` — mtime aelter als last_synced
10. `test_needs_sync_changed` — mtime neuer als last_synced
11. `test_sync_creates_project` — Neues Projekt in DB angelegt
12. `test_sync_updates_project` — Bestehendes Projekt aktualisiert
13. `test_sync_tasks` — Todos als Tasks synchronisiert
14. `test_skip_template` — _template.md wird uebersprungen
15. `test_parse_status_on_heading` — `## Status: In Arbeit` Format
16. `test_parse_standalone_status` — `**Status:** Done` ohne ## Sektion
17. `test_sync_preserves_path` — Bestehendes Projekt: path wird nicht ueberschrieben
18. `test_sync_all_performance` — 30 Files parsen unter 50ms (nur Parsing, ohne DB)

### Fixtures

Realistische .md-Inhalte als Strings, basierend auf echten Projekt-States.

## Nicht im Scope

- Rueckschreiben von DB → .md
- Echtzeit-Watcher (fsevents/inotify)
- Markdown-Parser-Library (stdlib reicht)
- Bidirektionale Konfliktloesung
