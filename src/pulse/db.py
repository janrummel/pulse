"""Pulse database layer — SQLite schema, event storage, project/task/session management."""

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    project_path TEXT,
    model TEXT,
    tool_name TEXT,
    tool_input_summary TEXT,
    tool_use_id TEXT,
    tool_output_success BOOLEAN,
    prompt_text TEXT,
    raw_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_path);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

CREATE TABLE IF NOT EXISTS sessions (
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

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    deadline TEXT,
    total_tasks INTEGER,
    completed_tasks INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    estimated_minutes REAL,
    actual_minutes REAL,
    debug_cycles INTEGER DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    notes TEXT
);
"""


class PulseDB:
    """SQLite database for Pulse event collection and project tracking."""

    def __init__(self, db_path: str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute raw SQL. Use for queries not covered by helper methods."""
        return self._conn.execute(sql, params)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # --- Events ---

    def insert_event(self, event: dict) -> int:
        """Insert a hook event and return its row id."""
        cursor = self._conn.execute(
            """INSERT INTO events
            (timestamp, session_id, event_type, project_path, model,
             tool_name, tool_input_summary, tool_use_id, tool_output_success,
             prompt_text, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event["timestamp"],
                event["session_id"],
                event["event_type"],
                event.get("project_path"),
                event.get("model"),
                event.get("tool_name"),
                event.get("tool_input_summary"),
                event.get("tool_use_id"),
                event.get("tool_output_success"),
                event.get("prompt_text"),
                event.get("raw_json"),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_events_by_session(self, session_id: str) -> list[dict]:
        """Get all events for a session, ordered by timestamp."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_type(self, session_id: str, event_type: str) -> list[dict]:
        """Get events of a specific type within a session."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE session_id=? AND event_type=? ORDER BY timestamp",
            (session_id, event_type),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_by_project(self, project_path: str) -> list[dict]:
        """Get all events for a project path, ordered by timestamp."""
        rows = self._conn.execute(
            "SELECT * FROM events WHERE project_path=? ORDER BY timestamp",
            (project_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_session_ids(self) -> list[str]:
        """Get all distinct session IDs."""
        rows = self._conn.execute(
            "SELECT session_id, MIN(timestamp) as first_ts FROM events GROUP BY session_id ORDER BY first_ts",
        ).fetchall()
        return [r[0] for r in rows]

    # --- Sessions ---

    def upsert_session(
        self,
        session_id: str,
        project_path: str | None = None,
        model: str | None = None,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_seconds: float | None = None,
        prompt_count: int | None = None,
        tool_call_count: int | None = None,
        tool_error_count: int | None = None,
        files_created: int | None = None,
        files_edited: int | None = None,
    ) -> None:
        """Insert or update a session record."""
        existing = self.get_session(session_id)
        if existing is None:
            self._conn.execute(
                """INSERT INTO sessions
                (session_id, project_path, model, started_at, ended_at,
                 duration_seconds, prompt_count, tool_call_count, tool_error_count,
                 files_created, files_edited)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    project_path,
                    model,
                    started_at,
                    ended_at,
                    duration_seconds,
                    prompt_count or 0,
                    tool_call_count or 0,
                    tool_error_count or 0,
                    files_created or 0,
                    files_edited or 0,
                ),
            )
        else:
            updates = []
            params = []
            for field, value in [
                ("project_path", project_path),
                ("model", model),
                ("started_at", started_at),
                ("ended_at", ended_at),
                ("duration_seconds", duration_seconds),
                ("prompt_count", prompt_count),
                ("tool_call_count", tool_call_count),
                ("tool_error_count", tool_error_count),
                ("files_created", files_created),
                ("files_edited", files_edited),
            ]:
                if value is not None:
                    updates.append(f"{field}=?")
                    params.append(value)
            if updates:
                params.append(session_id)
                self._conn.execute(
                    f"UPDATE sessions SET {', '.join(updates)} WHERE session_id=?",
                    tuple(params),
                )
        self._conn.commit()

    def get_session(self, session_id: str) -> dict | None:
        """Get a session by ID."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_recent_sessions(
        self, project_path: str, limit: int = 5
    ) -> list[dict]:
        """Get the most recent sessions for a project."""
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE project_path=? ORDER BY started_at DESC LIMIT ?",
            (project_path, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Projects ---

    def add_project(
        self,
        name: str,
        path: str,
        deadline: str | None = None,
        total_tasks: int | None = None,
        status: str = "active",
        notes: str | None = None,
    ) -> int:
        """Register a project and return its row id."""
        cursor = self._conn.execute(
            """INSERT INTO projects (name, path, deadline, total_tasks, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (name, path, deadline, total_tasks, status, notes),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_project(self, name: str) -> dict | None:
        """Get a project by name."""
        row = self._conn.execute(
            "SELECT * FROM projects WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_projects(self) -> list[dict]:
        """Get all active projects."""
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE status='active' ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_project(self, name: str, **kwargs) -> None:
        """Update project fields by name."""
        if not kwargs:
            return
        updates = ", ".join(f"{k}=?" for k in kwargs)
        params = list(kwargs.values()) + [name]
        self._conn.execute(
            f"UPDATE projects SET {updates} WHERE name=?", tuple(params)
        )
        self._conn.commit()

    # --- Tasks ---

    def add_task(
        self,
        project_id: int,
        name: str,
        estimated_minutes: float | None = None,
        notes: str | None = None,
    ) -> int:
        """Add a task to a project and return its row id."""
        cursor = self._conn.execute(
            """INSERT INTO tasks (project_id, name, estimated_minutes, notes)
            VALUES (?, ?, ?, ?)""",
            (project_id, name, estimated_minutes, notes),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_tasks(self, project_id: int) -> list[dict]:
        """Get all tasks for a project."""
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY id", (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_task(self, task_id: int, **kwargs) -> None:
        """Update task fields by id."""
        if not kwargs:
            return
        updates = ", ".join(f"{k}=?" for k in kwargs)
        params = list(kwargs.values()) + [task_id]
        self._conn.execute(
            f"UPDATE tasks SET {updates} WHERE id=?", tuple(params)
        )
        self._conn.commit()
