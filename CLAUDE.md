# CLAUDE.md — Pulse

## Projekt
Pulse ist ein Measurement- und Live-Planning-Tool fuer Claude Code Sessions.
Es beobachtet ueber Hooks was in Sessions passiert, sammelt Metriken in SQLite,
und zeigt Fortschritt, Velocity und Deadline-Prognosen.

## Tech-Stack
- Python 3.12+
- SQLite (Datenspeicher, WAL-Mode)
- Rich (Terminal-Dashboard)
- PyYAML (Config)
- pytest (Tests)

## Architektur
Kern: collector.py (Hook → SQLite), analyzer.py (Metriken),
planner.py (Prognose), dashboard.py (Rich TUI), cli.py (Interface).

## Hook-Payload (verifiziert 2026-03-14)
Alle Events haben: session_id, transcript_path, cwd, permission_mode, hook_event_name.
- model: NUR in SessionStart
- tool_name, tool_input, tool_use_id: in PreToolUse/PostToolUse
- tool_response (NICHT tool_output): in PostToolUse
- prompt: in UserPromptSubmit

## Coding-Regeln
- Keine unnötigen Dependencies (stdlib + rich + pyyaml + pytest)
- Hook-Handler MUESSEN < 100ms laufen — kein Blocking von Claude Code
- SQLite ist die einzige Datenquelle — kein State ausserhalb der DB
- Type-Hints ueberall, Docstrings fuer public Functions
- Tests mit realistischen Event-Fixtures

## Build-Reihenfolge
1. db.py (Schema + Basis-Queries) + tests
2. collector.py (Hook-Handler → DB) + tests
3. hooks.py (Installation in Claude Code settings.json)
4. seed-demo-data.py (Demo-Daten)
5. analyzer.py (Metriken-Berechnung) + tests
6. planner.py (Prognose) + tests
7. cli.py (add, status, project, priority, task)
8. dashboard.py (Rich TUI)
9. export.py (Obsidian-Export)
10. config.py
11. Integration-Tests
