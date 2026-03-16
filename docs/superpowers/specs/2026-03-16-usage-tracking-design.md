# Usage-Tracking Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Priority:** 2 (aus Aufklaerungsbriefing)

## Problem

Pulse trackt Session-Aktivitaet (Prompts, Tool-Calls, Dauer), aber nicht den Token-Verbrauch. Mit Claude Max gibt es keine direkten Kosten, aber Usage-Daten sind wertvoll fuer: Intensitaets-Trends, Context-Verbrauch pro Session, Model-Verteilung, Arbeitsrhythmus-Analyse.

## Ziel

Pulse importiert Usage-Daten aus Claude Codes `stats-cache.json` in die eigene DB und zeigt Token-Verbrauch, Intensitaet und Model-Mix ueber `pulse usage` und in `pulse recap`.

## Datenquellen

### 1. stats-cache.json (Lazy Import → DB)

Pfad: `~/.claude/stats-cache.json`

Relevante Felder:

```json
{
  "dailyActivity": [
    {
      "date": "2026-03-16",
      "messageCount": 142,
      "sessionCount": 8,
      "toolCallCount": 53
    }
  ],
  "dailyModelTokens": [
    {
      "date": "2026-03-16",
      "tokensByModel": {
        "claude-opus-4-6": 125000,
        "claude-haiku-4-5-20251001": 3200
      }
    }
  ],
  "modelUsage": {
    "claude-opus-4-6": {
      "inputTokens": 975029,
      "outputTokens": 138210,
      "cacheReadInputTokens": 1144196957,
      "cacheCreationInputTokens": 139016144
    }
  },
  "hourCounts": { "14": 234, "15": 189 }
}
```

Import-Strategie: Wie md-Sync — mtime-Check, nur importieren wenn File neuer als letzter Import. Taeglich aggregierte Daten in `daily_usage` Tabelle schreiben.

### 2. Transcript JSONL (On-Demand, kein DB-Import)

Pfad: Aus `transcript_path` in Hook-Events oder `~/.claude/projects/*/[session-id].jsonl`

Relevante Felder pro Assistant-Message:

```json
{
  "message": {
    "model": "claude-opus-4-6",
    "usage": {
      "input_tokens": 3,
      "output_tokens": 9,
      "cache_creation_input_tokens": 66709,
      "cache_read_input_tokens": 15902
    }
  }
}
```

Nur bei `pulse usage --session <id>` geparst. Dateien sind 1-7 MB gross — zu teuer fuer Batch-Import.

## DB-Schema

### Neue Tabelle: daily_usage

```sql
CREATE TABLE IF NOT EXISTS daily_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,
    message_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    tokens_by_model TEXT,
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- `date`: ISO-Datum (YYYY-MM-DD), UNIQUE
- `tokens_by_model`: JSON-String mit Token-Counts pro Model, z.B. `{"claude-opus-4-6": 125000, "claude-haiku-4-5-20251001": 3200}`
- `imported_at`: Timestamp des Imports

Kein Erweitern der bestehenden `sessions`-Tabelle — taeglich aggregierte Usage ist ein eigenes Concern.

### Neue Metadaten-Tabelle: usage_meta

```sql
CREATE TABLE IF NOT EXISTS usage_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

Speichert: `stats_cache_last_imported` (ISO-Timestamp des letzten Imports).

## Architektur

Neues Modul `src/pulse/usage.py`:

```
usage.py
├── import_stats_cache(db)        # stats-cache.json → daily_usage
├── needs_import(db)              # mtime-Check (File vs last_imported)
├── get_daily_usage(db, days=7)   # Letzte N Tage aus DB
├── get_usage_summary(db)         # Gesamtuebersicht (Total, Durchschnitte)
├── parse_session_usage(path)     # Transcript JSONL → Token-Summen (on-demand)
└── get_peak_hour(db)             # Stunde mit meisten Messages
```

### import_stats_cache(db)

```python
def import_stats_cache(db: PulseDB, stats_path: str | None = None) -> int:
    """Import daily stats from Claude Code stats-cache.json.

    Returns number of days imported/updated.
    """
```

Liest `dailyActivity` und `dailyModelTokens` Arrays. Fuer jeden Tag: Upsert in `daily_usage`. Matched ueber `date`.

### parse_session_usage(transcript_path)

```python
@dataclass
class SessionUsage:
    session_id: str
    model: str
    duration_minutes: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read: int
    total_cache_creation: int
    message_count: int
    prompts_per_minute: float

def parse_session_usage(transcript_path: str) -> SessionUsage:
    """Parse a transcript JSONL file for token usage stats."""
```

Liest die JSONL-Datei zeilenweise. Summiert `usage`-Felder aller Assistant-Messages. Berechnet Duration aus erstem/letztem Timestamp.

## CLI

### pulse usage (Hauptansicht)

```
pulse usage [--days N] [--session <id>]
```

**Default (ohne Argumente):** Letzte 7 Tage.

```
  Usage (letzte 7 Tage)

  Tag         Messages  Sessions  Tokens
  2026-03-16       142        8    125k
  2026-03-15        89        5     92k
  2026-03-14       203       12    187k
  ...

  Model-Mix: Opus 78%  Sonnet 19%  Haiku 3%
  Peak: 14:00-15:00
  Durchschnitt: 18 msg/session
```

**Mit --session:** Transcript parsen, Session-Detail zeigen.

```
  Session abc123 (45 min)

  Input:   82k tokens
  Output:  12k tokens
  Cache:   340k read / 67k created
  Model:   claude-opus-4-6
  Rate:    3.2 prompts/min
```

### pulse recap (Erweiterung)

Bestehender Recap-Output wird um eine Zeile erweitert:

```
  Token-Verbrauch  125k tokens (Opus 78%, Sonnet 22%)
```

Nur wenn Usage-Daten fuer den Tag vorhanden sind.

## Integration

### Lazy Import

Analog zu `_ensure_synced(db)`:

```python
def _ensure_usage_imported(db: PulseDB) -> None:
    """Import stats-cache.json if changed since last import."""
    from pulse.usage import import_stats_cache, needs_import
    if needs_import(db):
        import_stats_cache(db)
```

Aufrufe: `_cmd_usage`, `_cmd_recap`.

### stats-cache.json Pfad

In `config.py` als Default:

```python
"stats_cache_path": str(Path.home() / ".claude" / "stats-cache.json"),
```

## Fehlerbehandlung

- stats-cache.json nicht vorhanden → Warning, leere Usage-Anzeige
- stats-cache.json ungueltiges Format → Warning auf stderr, skip
- Transcript-Datei nicht gefunden → Fehlermeldung mit Pfad
- Leere daily_usage → "Noch keine Usage-Daten importiert."

## Testing

### Unit Tests (test_usage.py)

1. `test_import_stats_cache` — Importiert Fixture-Daten, prueft daily_usage Eintraege
2. `test_import_upsert` — Doppelter Import ueberschreibt korrekt
3. `test_needs_import_no_file` — Kein stats-cache → False (kein Crash)
4. `test_needs_import_fresh` — File aelter als letzter Import → False
5. `test_needs_import_stale` — File neuer als letzter Import → True
6. `test_get_daily_usage` — Gibt letzte N Tage zurueck
7. `test_get_usage_summary` — Berechnet Totals und Durchschnitte
8. `test_parse_session_usage` — Parst Transcript-JSONL korrekt
9. `test_parse_session_usage_empty` — Leere Datei → Defaults
10. `test_get_peak_hour` — Findet Stunde mit meisten Messages
11. `test_tokens_by_model_json` — JSON-String wird korrekt gelesen/geschrieben

### Fixtures

Realistische stats-cache.json und Transcript-JSONL als Strings/dicts.

## Nicht im Scope

- Kosten in EUR/USD (Max-Abo = keine direkten Kosten)
- Echtzeit-Tracking waehrend Sessions
- API-Kosten anderer Dienste (WhisperAI etc.)
- Transcript-Batch-Import in DB
- Dashboard/TUI-Widget (spaeter)
- Model-Routing Analyse
