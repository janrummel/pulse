# Pulse — Architektur-Spec

**Projektname:** Pulse
**Tagline:** *Der Herzschlag deiner Claude-Code-Projekte.*
**Zweck:** Measurement- und Live-Planning-Agent für Claude Code Sessions. Beobachtet über Hooks was in deinen Projekten passiert, sammelt Metriken, zeigt dir wo du stehst, und sagt dir was du als nächstes tun solltest.

**Einordnung:** Pulse ist ein eigenständiges Tool das sich in das bestehende Orchestrator-Ökosystem einfügt — als Skill abrufbar, als Memory-Quelle nutzbar, als CLI unabhängig lauffähig.

**Stack:** Python 3.12+, SQLite (Datenspeicher), Rich (Terminal-Dashboard), Shell-Scripts (Hook-Handler)
**Scope:** Persönliches Tool, perspektivisch Open Source

---

## 1. Problemstellung

### Was heute passiert

Claude Code erstellt Zeitpläne als ob ein Mensch den Code schreibt. Ein typischer Plan:

```
vault.py + tests:     2 Stunden
scanner.py + patterns: 3 Stunden
proxy.py:              3 Stunden
```

Was tatsächlich passiert:

```
vault.py + tests:     8 Minuten (Claude Code schreibt es in 45 Sekunden, 
                                 Review + Test-Fix: 7 Min)
scanner.py + patterns: 12 Minuten (+ 1 Debug-Zyklus)
proxy.py:              47 Minuten (6 Debug-Zyklen — TLS-Integration)
```

Die realen Zeitfresser sind nicht Lines-of-Code, sondern:
- **Debug-Zyklen** — wie oft muss Claude seinen eigenen Output korrigieren?
- **Integration-Blocker** — externe Systeme die nicht sofort funktionieren
- **Human-Wait-Time** — wie lange wartet der Agent darauf, dass du entscheidest?
- **Context-Compaction** — wann wird der Context voll und geht Information verloren?

### Was niemand misst

Kein existierendes Tool trackt diese Agent-spezifischen Variablen systematisch.
Claude Squad, Agent Teams, Craft Agents — sie managen Sessions, aber sie messen nicht was *in* den Sessions passiert. Die Claude Code Hooks liefern die Rohdaten, aber niemand aggregiert sie zu nützlichen Metriken.

### Was Pulse löst

Pulse beantwortet drei Fragen:
1. **Was passiert gerade?** → Live-Dashboard mit aktiver Session
2. **Wie performt mein Setup?** → Metriken über Zeit aggregiert
3. **Schaffe ich mein Ziel?** → Prognose basierend auf realer Velocity

---

## 2. Architektur-Übersicht

```
┌───────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE SESSIONS                        │
│                                                               │
│  Projekt A          Projekt B          Projekt C              │
│  (watchdog/)        (kfactory/)        (orchestrator/)        │
│       │                  │                   │                │
│       └──── Hooks ───────┴──── Hooks ────────┘                │
│              │                                                │
└──────────────┼────────────────────────────────────────────────┘
               │
               ▼
┌───────────────────────────────────────────────────────────────┐
│                         PULSE                                  │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │  Collector   │  │   Analyzer    │  │     Planner          │ │
│  │             │  │              │  │                      │ │
│  │ Hook-Events │  │ Velocity     │  │ Deadline-Prognose    │ │
│  │ → SQLite    │  │ Debug-Ratio  │  │ Priority-Ranking     │ │
│  │             │  │ Tool-Mix     │  │ Scope-Empfehlungen   │ │
│  └─────────────┘  └──────────────┘  └──────────────────────┘ │
│         │                │                    │               │
│         ▼                ▼                    ▼               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    SQLite DB                            │  │
│  │  events · sessions · projects · metrics · plans         │  │
│  └────────────────────────────────────────────────────────┘  │
│         │                                                    │
│         ▼                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Dashboard   │  │  Orchestrator │  │  Obsidian Export │   │
│  │  (Rich TUI)  │  │  Skill        │  │  (Markdown)      │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Phasen-Struktur

### Phase 1 — Collector (Daten sammeln)
**Ziel:** Hook-Events von Claude Code Sessions in eine SQLite-DB schreiben.
**Ergebnis:** Du hast Rohdaten über alles was in deinen Sessions passiert.
**Eigenständig nutzlich:** Ja — du kannst SQL-Queries auf deine Session-Daten machen.

### Phase 2 — Analyzer (Metriken berechnen)
**Ziel:** Aus den Rohdaten aggregierte Metriken berechnen.
**Ergebnis:** Velocity, Debug-Ratio, Tool-Mix, Human-Wait-Time pro Projekt.
**Eigenständig nützlich:** Ja — du verstehst wie dein AI-Coding tatsächlich funktioniert.

### Phase 3 — Dashboard (Sichtbar machen)
**Ziel:** Terminal-Dashboard das die Metriken live zeigt.
**Ergebnis:** Du siehst in Echtzeit was passiert und wie du performst.
**Eigenständig nützlich:** Ja — visuelles Feedback während du arbeitest.

### Phase 4 — Planner (Prognose + Empfehlungen)
**Ziel:** Basierend auf historischen Daten Deadlines prognostizieren und Prioritäten empfehlen.
**Ergebnis:** "Bei aktueller Velocity schaffst du 14/18 Tasks bis Freitag."
**Eigenständig nützlich:** Ja — datenbasierte Projektplanung statt Bauchgefühl.

### Phase 5 — Multi-Projekt + Orchestrator-Integration
**Ziel:** Cross-Projekt-Überblick, automatisches Session-Management, Obsidian-Export.
**Ergebnis:** Pulse als Teil deines persönlichen Betriebssystems.

Jede Phase baut auf der vorherigen auf. Jede Phase ist eigenständig nutzbar.

---

## 4. Phase 1 — Collector (Detail-Spec)

### 4.1 Claude Code Hooks

Pulse nutzt das offizielle Hook-System. Die Hook-Handler sind Shell-Scripts die JSON von stdin lesen und an Pulse weiterleiten.

**Genutzte Hook-Events:**

| Event | Was wir daraus lernen | Priorität |
|---|---|---|
| `SessionStart` | Session-Beginn, Modell, Projekt-Pfad | P1 |
| `SessionEnd` | Session-Dauer, Gesamtstatistik | P1 |
| `PreToolUse` | Welches Tool wird aufgerufen, mit welchem Input | P1 |
| `PostToolUse` | Tool-Ergebnis, Dauer, Erfolg/Fehler | P1 |
| `UserPromptSubmit` | Neuer Prompt = neue "Runde", Human-Intervention | P1 |
| `Stop` | Agent ist fertig, wartet auf nächsten Prompt | P1 |
| `SubagentStart` | Delegation an Subagent | P2 |
| `SubagentStop` | Subagent fertig | P2 |
| `PreCompact` | Context wird komprimiert — Warnsignal | P2 |
| `Notification` | Agent will Aufmerksamkeit | P3 |

### 4.2 Hook-Installation

```bash
# pulse install — schreibt Hooks in Claude Code Settings
# Generiert für jedes Event einen Hook-Eintrag:

{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event SessionStart"
      }]
    }],
    "PreToolUse": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event PreToolUse"
      }]
    }],
    "PostToolUse": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event PostToolUse"
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event UserPromptSubmit"
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event Stop"
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "command": "pulse collect --event SessionEnd"
      }]
    }]
  }
}
```

**Kritische Anforderung:** Hook-Handler müssen schnell sein (< 100ms). Sie dürfen Claude Code nicht blockieren. Daher: JSON von stdin lesen, in SQLite schreiben, sofort exit. Keine API-Calls, keine Berechnungen im Hook selbst.

### 4.3 Collector-Logik

```python
# pulse collect --event <event_type>
# Liest JSON von stdin, schreibt in SQLite

import sys
import json
import sqlite3
from datetime import datetime

def collect():
    """Hook-Handler: Liest Event von stdin, schreibt in DB."""
    event_data = json.loads(sys.stdin.read())
    
    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": event_data.get("session_id"),
        "event_type": event_data.get("hook_event_name"),
        "project_path": event_data.get("cwd"),
        "model": event_data.get("model"),
        "tool_name": event_data.get("tool_name"),
        "tool_input_summary": _summarize_input(event_data.get("tool_input", {})),
        "tool_output_success": _check_success(event_data),
        "prompt_text": event_data.get("prompt", "")[:500],  # Truncated
        "raw_json": json.dumps(event_data),
    }
    
    db = sqlite3.connect(_db_path())
    db.execute("""
        INSERT INTO events 
        (timestamp, session_id, event_type, project_path, model,
         tool_name, tool_input_summary, tool_output_success, prompt_text, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, tuple(event.values()))
    db.commit()
    db.close()

def _summarize_input(tool_input: dict) -> str:
    """Kurze Zusammenfassung des Tool-Inputs (keine Secrets loggen)."""
    if "command" in tool_input:
        # Bash-Command: nur den Befehl, nicht die Ausgabe
        cmd = tool_input["command"][:200]
        return f"bash: {cmd}"
    if "file_path" in tool_input:
        return f"file: {tool_input['file_path']}"
    return json.dumps(tool_input)[:200]

def _check_success(event_data: dict) -> bool | None:
    """Prüft ob ein PostToolUse erfolgreich war."""
    if event_data.get("hook_event_name") != "PostToolUse":
        return None
    # Heuristik: Fehler erkennen
    output = str(event_data.get("tool_output", ""))
    error_indicators = ["error", "Error", "FAILED", "traceback", "Exception"]
    return not any(ind in output for ind in error_indicators)
```

### 4.4 SQLite Schema

```sql
-- Kern-Tabelle: Alle Events
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    project_path TEXT,
    model TEXT,
    tool_name TEXT,
    tool_input_summary TEXT,
    tool_output_success BOOLEAN,
    prompt_text TEXT,
    raw_json TEXT
);

CREATE INDEX idx_events_session ON events(session_id);
CREATE INDEX idx_events_project ON events(project_path);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp);

-- Abgeleitete Tabelle: Sessions (wird beim SessionEnd gefüllt)
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    project_path TEXT,
    model TEXT,
    started_at TEXT,
    ended_at TEXT,
    duration_seconds REAL,
    prompt_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    tool_error_count INTEGER DEFAULT 0,
    files_created INTEGER DEFAULT 0,
    files_edited INTEGER DEFAULT 0
);

-- Registrierte Projekte (manuell via pulse add)
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    deadline TEXT,                -- ISO-Datum oder NULL
    total_tasks INTEGER,
    completed_tasks INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active', -- active | paused | done
    created_at TEXT NOT NULL,
    notes TEXT                   -- Freitext für Kontext
);

-- Task-Tracking pro Projekt (optional, manuell oder aus CLAUDE.md)
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- pending | in_progress | done | blocked
    estimated_minutes REAL,        -- Schätzung (optional)
    actual_minutes REAL,           -- Gemessen (nach Abschluss)
    debug_cycles INTEGER DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    notes TEXT
);
```

### 4.5 DB-Speicherort

```
~/.pulse/
├── pulse.db              # SQLite-Datenbank
├── config.yaml           # Konfiguration
└── exports/              # Obsidian/Markdown-Exports
```

Nicht im Projektverzeichnis, sondern global — Pulse beobachtet alle Projekte.

---

## 5. Phase 2 — Analyzer (Detail-Spec)

### 5.1 Berechnete Metriken

```python
class Analyzer:
    """Berechnet Metriken aus den gesammelten Events."""

    def velocity(self, project_path: str, window_hours: int = 24) -> dict:
        """Tasks pro Stunde, basierend auf abgeschlossenen Tasks."""
        # Zählt: Wie viele Tasks wurden im Zeitfenster als 'done' markiert?
        # Berechnet: tasks / aktive_stunden (ohne Human-Wait-Time)
        return {
            "tasks_per_hour": float,
            "trend": "rising" | "falling" | "stable",
            "confidence": float,  # Wie viele Datenpunkte fließen ein
        }

    def debug_ratio(self, session_id: str = None) -> dict:
        """Anteil der Tool-Calls die Korrekturen sind."""
        # Heuristik: Ein PostToolUse mit Fehler, gefolgt von einem
        # PreToolUse auf die gleiche Datei = Debug-Zyklus
        return {
            "ratio": float,           # 0.0 - 1.0
            "total_tool_calls": int,
            "debug_cycles": int,
            "worst_file": str,         # Datei mit meisten Debug-Zyklen
        }

    def tool_mix(self, project_path: str = None) -> dict:
        """Verteilung der Tool-Nutzung."""
        # Write = Fortschritt, Edit = Anpassung, Bash = Test/Debug,
        # Read = Recherche, Glob/Grep = Exploration
        return {
            "write_pct": float,    # Neue Dateien erstellen
            "edit_pct": float,     # Existierende Dateien ändern
            "bash_pct": float,     # Shell-Commands (Tests, Builds)
            "read_pct": float,     # Dateien lesen
            "explore_pct": float,  # Glob, Grep, Suche
            "interpretation": str, # z.B. "Viel Bash = Debug-Phase"
        }

    def human_wait_time(self, session_id: str = None) -> dict:
        """Wie lange wartet der Agent auf den Menschen?"""
        # Gemessen: Zeit zwischen Stop-Event und nächstem UserPromptSubmit
        return {
            "total_wait_seconds": float,
            "avg_wait_seconds": float,
            "wait_pct": float,          # Anteil an Gesamt-Session-Zeit
            "longest_wait_seconds": float,
        }

    def session_summary(self, session_id: str) -> dict:
        """Zusammenfassung einer einzelnen Session."""
        return {
            "duration_minutes": float,
            "prompts": int,
            "tool_calls": int,
            "debug_cycles": int,
            "files_touched": list[str],
            "velocity": float,
            "debug_ratio": float,
            "human_wait_pct": float,
            "model": str,
            "cost_estimate": float | None,  # Wenn Token-Daten verfügbar
        }

    def project_health(self, project_name: str) -> dict:
        """Gesamtstatus eines Projekts."""
        return {
            "tasks_done": int,
            "tasks_total": int,
            "avg_velocity": float,
            "avg_debug_ratio": float,
            "total_session_hours": float,
            "last_session": str,          # Zeitpunkt
            "trend": str,                 # "accelerating" | "slowing" | "stalled"
        }
```

### 5.2 Debug-Zyklus-Erkennung

Die wichtigste Heuristik — was zählt als Debug-Zyklus:

```python
def _detect_debug_cycles(self, events: list[Event]) -> list[DebugCycle]:
    """
    Ein Debug-Zyklus ist:
    1. PostToolUse mit Fehler (tool_output_success = False)
    2. Gefolgt von PreToolUse auf die gleiche Datei/Resource
    
    ODER:
    1. Bash-Command das einen Fehler produziert (exit code != 0)
    2. Gefolgt von Edit auf eine Datei die im Error erwähnt wird
    
    ODER:
    1. Edit auf eine Datei
    2. Gefolgt von Bash (Test)
    3. Gefolgt von Edit auf die gleiche Datei (Fix)
    """
    cycles = []
    for i, event in enumerate(events):
        if event.tool_output_success is False:
            # Schau ob der nächste Tool-Call die gleiche Resource betrifft
            next_events = events[i+1:i+4]  # Nächste 3 Events
            for ne in next_events:
                if ne.event_type == "PreToolUse" and _same_resource(event, ne):
                    cycles.append(DebugCycle(
                        trigger_event=event,
                        fix_event=ne,
                        file=_extract_file(event),
                    ))
                    break
    return cycles
```

---

## 6. Phase 3 — Dashboard (Detail-Spec)

### 6.1 Terminal-Dashboard (Rich TUI)

```
┌─ 🫀 PULSE ──────────────────────────────────── 14:23 CET ────┐
│                                                                │
│  AKTIVE SESSION: watchdog/                    Model: opus      │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│  Laufzeit: 23 min  │  Prompts: 7  │  Tool-Calls: 34           │
│  Debug-Zyklen: 3   │  Human-Wait: 18%  │  Files: 6            │
│                                                                │
│  TOOL-MIX                    LETZTE AKTIVITÄT                  │
│  Write  ████████░░  42%      14:22  ✅ Write scanner.py        │
│  Edit   ███░░░░░░░  15%      14:21  ✅ Bash pytest             │
│  Bash   █████░░░░░  28%      14:20  ❌ Bash pytest (FAIL)      │
│  Read   ██░░░░░░░░   8%      14:19  ✅ Edit scanner.py         │
│  Other  █░░░░░░░░░   7%      14:18  ✅ Write test_scanner.py   │
│                                                                │
│  PROJEKTE                                                      │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│  🟢 watchdog        5/12 tasks  ▸ aktiv jetzt                  │
│  🟡 knowledge-fac.  pipeline    ▸ vor 1 Tag                    │
│  ⚪ orchestrator    paused      ▸ vor 3 Tagen                  │
│                                                                │
└──────────────── [p] projekte  [s] session  [q] quit ──────────┘
```

### 6.2 Detail-Ansichten

**[s] Session-Deep-Dive:**
```
┌─ SESSION: watchdog/  abc123 ───────────── seit 23 min ────────┐
│                                                                │
│  TIMELINE                                                      │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │
│  14:00 ▶ "Lies die Spec und baue vault.py"                     │
│  14:01   Write vault.py ✅ (0.8 min)                           │
│  14:02   Write test_vault.py ✅ (1.2 min)                      │
│  14:03   Bash pytest ✅                                        │
│  14:04 ▶ "Jetzt scanner.py mit den Patterns"                   │
│  14:05   Read docs/SPEC.md ✅                                  │
│  14:05   Write scanner.py ✅ (2.1 min)                         │
│  14:07   Write patterns/api_keys.py ✅ (0.9 min)               │
│  14:08   Bash pytest ❌ (2 tests failed)       ← Debug #1     │
│  14:09   Edit scanner.py ✅                     ← Fix          │
│  14:10   Bash pytest ✅                                        │
│  14:11   ⏸ Human-Wait (3.2 min)                                │
│  14:14 ▶ "Weiter mit proxy.py"                                 │
│  ...                                                           │
│                                                                │
│  METRIKEN DIESER SESSION                                       │
│  Velocity: 2.3 tasks/h │ Debug-Ratio: 0.12 │ Wait: 18%       │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**[p] Projekt-Deep-Dive:**
```
┌─ PROJEKT: watchdog ────────────── Deadline: Mi 19.3. 08:59 ──┐
│                                                                │
│  FORTSCHRITT                                                   │
│  ████████████████░░░░░░░░░░░░░░  5/12 Tasks (42%)             │
│  Zeit verbraucht: 34%  │  Prognose: ✅ machbar (1.5h Puffer)  │
│                                                                │
│  TASKS                     STATUS    DAUER   DEBUG             │
│  ✅ vault.py               done      3 min   0                 │
│  ✅ scanner.py + patterns   done      12 min  1                │
│  ✅ proxy.py               done      47 min  6  ⚠️             │
│  ✅ rehydrator.py          done      4 min   0                 │
│  ✅ anomaly.py             done      12 min  2                 │
│  🔄 alerter.py             active    ...     ...               │
│  ⬜ agent.py               pending                             │
│  ⬜ dashboard.py           pending                             │
│  ⬜ config.py              pending                             │
│  ⬜ cli.py                 pending                             │
│  ⬜ tests                  pending                             │
│  ⬜ demo.sh                pending                             │
│                                                                │
│  VELOCITY ÜBER ZEIT                                            │
│  Session 1: 1.8/h │ Session 2: 2.1/h │ Session 3: 2.5/h  ↑  │
│                                                                │
│  💡 proxy.py hatte 6 Debug-Zyklen (Ø 1.5). TLS-Integration    │
│     war der Blocker. Restliche Tasks sind weniger riskant.     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## 7. Phase 4 — Planner (Detail-Spec)

### 7.1 Deadline-Prognose

```python
class Planner:
    """Berechnet Prognosen basierend auf historischen Metriken."""

    def project_forecast(self, project_name: str) -> Forecast:
        """Prognostiziert ob ein Projekt seine Deadline schafft."""
        project = self.db.get_project(project_name)
        metrics = self.analyzer.project_health(project_name)
        
        remaining_tasks = project.total_tasks - project.completed_tasks
        
        if metrics["avg_velocity"] == 0:
            return Forecast(status="insufficient_data")
        
        # Geschätzte verbleibende Stunden
        # Berücksichtigt: Velocity PLUS typische Debug-Zyklen
        hours_per_task = 1.0 / metrics["avg_velocity"]
        debug_overhead = 1.0 + metrics["avg_debug_ratio"]
        estimated_hours = remaining_tasks * hours_per_task * debug_overhead
        
        # Verfügbare Stunden bis Deadline
        available_hours = self._hours_until(project.deadline)
        
        # Puffer
        buffer_hours = available_hours - estimated_hours
        
        return Forecast(
            remaining_tasks=remaining_tasks,
            estimated_hours=round(estimated_hours, 1),
            available_hours=round(available_hours, 1),
            buffer_hours=round(buffer_hours, 1),
            status="on_track" if buffer_hours > 0 else "at_risk",
            confidence=self._confidence(metrics),
            recommendation=self._recommend(buffer_hours, remaining_tasks),
        )

    def _recommend(self, buffer: float, remaining: int) -> str:
        if buffer > remaining * 0.5:
            return "Komfortabler Puffer. Weiter wie bisher."
        elif buffer > 0:
            return "Knapp. Fokus auf kritische Tasks, Nice-to-haves streichen."
        elif buffer > -2:
            return "Hinter Plan. Scope reduzieren — welche Tasks können entfallen?"
        else:
            return "Deutlich hinter Plan. Deadline verschieben oder Scope drastisch kürzen."

    def priority_ranking(self) -> list[ProjectPriority]:
        """Empfiehlt welches Projekt als nächstes Aufmerksamkeit braucht."""
        priorities = []
        for project in self.db.get_active_projects():
            forecast = self.project_forecast(project.name)
            urgency = self._calculate_urgency(project, forecast)
            priorities.append(ProjectPriority(
                project=project,
                forecast=forecast,
                urgency=urgency,
                reason=self._urgency_reason(project, forecast),
            ))
        return sorted(priorities, key=lambda p: p.urgency, reverse=True)

    def _calculate_urgency(self, project, forecast) -> float:
        """Urgency-Score: 0.0 (entspannt) bis 1.0 (kritisch)."""
        if not project.deadline:
            return 0.3  # Kein Deadline = niedrige Urgency
        
        if forecast.status == "at_risk":
            return 0.9
        
        # Je weniger Puffer, desto höher die Urgency
        if forecast.buffer_hours < 2:
            return 0.8
        elif forecast.buffer_hours < 5:
            return 0.6
        else:
            return 0.4
```

---

## 8. Phase 5 — Orchestrator-Integration

### 8.1 Pulse als Orchestrator-Skill

```markdown
# orchestrator/skills/pulse/SKILL.md
---
name: pulse
description: Projektfortschritt und Metriken abfragen. Zeigt Velocity, Debug-Ratio, 
  Deadline-Prognosen und empfiehlt nächste Schritte.
---

# Pulse — Projekt-Metriken

## Wann nutzen
- "Wie stehe ich beim Projekt?"
- "Schaffe ich die Deadline?"
- "Was soll ich als nächstes machen?"
- "Zeig mir die Metriken"

## Workflow
1. Führe `pulse status` aus um den aktuellen Stand zu sehen
2. Für ein spezifisches Projekt: `pulse project <name>`
3. Für Prioritäts-Empfehlung: `pulse priority`
4. Für Detail-Metriken: `pulse metrics <project>`

## Output-Format
Pulse liefert strukturierte Daten. Fasse sie für den Nutzer zusammen:
- Fortschritt als Prozentzahl und Task-Liste
- Prognose als klare Aussage (schaffe ich es / schaffe ich es nicht)
- Empfehlung als konkreten nächsten Schritt
```

### 8.2 Obsidian-Export

```python
def export_to_obsidian(self, project_name: str, vault_path: str):
    """Exportiert Projekt-Status als Obsidian-Note."""
    health = self.analyzer.project_health(project_name)
    forecast = self.planner.project_forecast(project_name)
    sessions = self.db.get_recent_sessions(project_name, limit=5)
    
    note = f"""---
    tags: [pulse, project-status, {project_name}]
    date: {datetime.now().strftime('%Y-%m-%d')}
    ---
    
    # {project_name} — Pulse Status
    
    ## Fortschritt
    - Tasks: {health['tasks_done']}/{health['tasks_total']}
    - Velocity: {health['avg_velocity']:.1f} tasks/h
    - Debug-Ratio: {health['avg_debug_ratio']:.0%}
    - Trend: {health['trend']}
    
    ## Prognose
    - Status: {forecast.status}
    - Geschätzte verbleibende Zeit: {forecast.estimated_hours}h
    - Puffer: {forecast.buffer_hours}h
    - Empfehlung: {forecast.recommendation}
    
    ## Letzte Sessions
    {''.join(self._format_session(s) for s in sessions)}
    """
    
    path = Path(vault_path) / "pulse" / f"{project_name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note)
```

### 8.3 Memory-Integration

Pulse schreibt Session-Summaries in das Orchestrator Memory-System:

```
memory/
├── projects/
│   ├── watchdog.md          ← Manuell gepflegt
│   └── watchdog-pulse.md    ← Von Pulse generiert/aktualisiert
```

---

## 9. Projekt-Struktur

```
pulse/
├── CLAUDE.md                    # Instruktionen für Claude Code
├── README.md
├── pyproject.toml
├── config.example.yaml
│
├── src/
│   └── pulse/
│       ├── __init__.py
│       ├── cli.py               # CLI: start, status, project, priority, install
│       ├── collector.py         # Hook-Event-Handler → SQLite
│       ├── analyzer.py          # Metriken-Berechnung
│       ├── planner.py           # Prognose + Empfehlungen
│       ├── dashboard.py         # Rich TUI
│       ├── db.py                # SQLite Schema + Queries
│       ├── config.py            # YAML-Config
│       ├── export.py            # Obsidian + Markdown Export
│       └── hooks.py             # Hook-Installation in Claude Code Settings
│
├── skill/
│   └── SKILL.md                 # Orchestrator-Skill-Definition
│
├── tests/
│   ├── test_collector.py
│   ├── test_analyzer.py
│   ├── test_planner.py
│   └── fixtures/
│       ├── sample_events.json   # Realistische Event-Daten für Tests
│       └── sample_sessions.db   # Pre-filled SQLite für Analyzer-Tests
│
└── scripts/
    ├── install.sh               # Setup
    └── seed-demo-data.py        # Füllt DB mit Demo-Daten (für Screenshots/Video)
```

---

## 10. CLI-Interface

```bash
# Hooks in Claude Code installieren
pulse install
# → Hooks installiert in ~/.claude/settings.json
# → Pulse sammelt ab jetzt Daten aus allen Claude Code Sessions

# Projekt registrieren
pulse add watchdog ~/projects/watchdog --deadline "2026-03-19 08:59" --tasks 12
pulse add knowledge-factory ~/projects/kfactory
pulse add orchestrator ~/projects/orchestrator --status paused

# Status aller Projekte
pulse status
# → Zeigt alle Projekte mit Fortschritt, letzter Session, Trend

# Detail-Status eines Projekts
pulse project watchdog
# → Tasks, Velocity, Debug-Ratio, Prognose

# Prioritäts-Empfehlung
pulse priority
# → "1. watchdog (Deadline in 2 Tagen, on track)
# →  2. knowledge-factory (Pipeline-Refresh überfällig)
# →  3. orchestrator (paused, keine Aktion nötig)"

# Live-Dashboard starten
pulse dashboard
# → Rich TUI mit Live-Updates

# Metriken einer Session
pulse session <session_id>
# → Timeline, Tool-Mix, Debug-Zyklen

# Task als erledigt markieren
pulse task done watchdog alerter.py
# → Task updated, Velocity neu berechnet

# Export nach Obsidian
pulse export watchdog --vault ~/Obsidian/Projects/
# → Schreibt pulse/watchdog.md in den Vault

# Demo-Daten generieren (für Tests und Screenshots)
pulse seed-demo
# → Füllt DB mit realistischen Beispieldaten
```

---

## 11. CLAUDE.md

```markdown
# CLAUDE.md — Pulse

## Projekt
Pulse ist ein Measurement- und Live-Planning-Tool für Claude Code Sessions.
Es beobachtet über Hooks was in Sessions passiert, sammelt Metriken in SQLite,
und zeigt Fortschritt, Velocity und Deadline-Prognosen.

## Tech-Stack
- Python 3.12+
- SQLite (Datenspeicher)
- Rich (Terminal-Dashboard)
- PyYAML (Config)
- pytest (Tests)

## Architektur
Lies `docs/SPEC.md` für die vollständige Architektur.
Kern: collector.py (Hook → SQLite), analyzer.py (Metriken), 
planner.py (Prognose), dashboard.py (Rich TUI), cli.py (Interface).

## Coding-Regeln
- Keine unnötigen Dependencies (stdlib + rich + pyyaml + pytest)
- Hook-Handler MÜSSEN < 100ms laufen — kein Blocking von Claude Code
- SQLite ist die einzige Datenquelle — kein State außerhalb der DB
- Type-Hints überall, Docstrings für public Functions
- Tests mit realistischen Event-Fixtures

## Build-Reihenfolge
1. db.py (Schema + Basis-Queries) + tests
2. collector.py (Hook-Handler → DB) + tests
3. hooks.py (Installation in Claude Code settings.json)
4. analyzer.py (Metriken-Berechnung) + tests
5. planner.py (Prognose) + tests
6. cli.py (add, status, project, priority, task)
7. dashboard.py (Rich TUI)
8. export.py (Obsidian-Export)
9. config.py
10. Integration-Tests
11. seed-demo-data.py

## Kontext
Pulse ist Teil des Claude Orchestrator Ökosystems.
Es integriert sich als Skill (skill/SKILL.md) und als Memory-Quelle
(memory/projects/<name>-pulse.md).
```

---

## 12. Konfiguration

```yaml
# ~/.pulse/config.yaml

# Datenbank
db:
  path: "~/.pulse/pulse.db"

# Dashboard
dashboard:
  refresh_interval: 2      # Sekunden
  show_raw_events: false   # Rohe Events im Dashboard anzeigen

# Export
export:
  obsidian_vault: "~/Obsidian/Projects/"
  auto_export: false         # Bei jedem Session-Ende exportieren?

# Projekte werden via CLI registriert, nicht in der Config
```

---

## 13. Risiken & Mitigationen

| Risiko | Wahrscheinlichkeit | Mitigation |
|---|---|---|
| Hook-Handler zu langsam (> 100ms) | Niedrig | Nur SQLite-Insert, keine Berechnung |
| Claude Code Hook-Format ändert sich | Mittel | JSON-Schema flexibel parsen, raw_json speichern |
| Nicht genug Daten für Prognose | Hoch (am Anfang) | Planner braucht min. 3 Sessions, vorher "insufficient data" anzeigen |
| SQLite-Locking bei parallelen Sessions | Niedrig | WAL-Mode aktivieren |
| Token/Cost-Daten nicht in Hooks | Hoch | Feature-Request existiert, vorerst ohne Cost-Tracking |
| Debug-Zyklus-Heuristik hat False Positives | Mittel | Konservativ zählen, nur eindeutige Patterns |

---

## 14. Erfolgskriterien

### Phase 1 (Collector)
- [ ] Hook-Installation funktioniert (`pulse install`)
- [ ] Events werden in SQLite geschrieben
- [ ] Hook-Handler < 100ms Ausführungszeit
- [ ] Projekt-Registrierung funktioniert (`pulse add`)
- [ ] `pulse status` zeigt registrierte Projekte
- [ ] ≥ 10 Tests für Collector + DB

### Phase 2 (Analyzer)
- [ ] Velocity-Berechnung funktioniert
- [ ] Debug-Zyklen werden korrekt erkannt
- [ ] Tool-Mix wird berechnet
- [ ] Human-Wait-Time wird gemessen
- [ ] Session-Summary ist aussagekräftig
- [ ] ≥ 10 Tests für Analyzer

### Phase 3 (Dashboard)
- [ ] Live-Dashboard zeigt aktive Session
- [ ] Projekt-Liste mit Status
- [ ] Session-Timeline mit Events
- [ ] Dashboard blockiert nicht (async refresh)

### Phase 4 (Planner)
- [ ] Deadline-Prognose funktioniert
- [ ] Priority-Ranking über Projekte
- [ ] Empfehlungen sind nützlich und nicht generisch
- [ ] Graceful Degradation bei wenig Daten

### Phase 5 (Integration)
- [ ] Orchestrator-Skill funktioniert
- [ ] Obsidian-Export generiert valide Notes
- [ ] Memory-Integration aktualisiert project-pulse.md
