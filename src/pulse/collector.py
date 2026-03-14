"""Pulse collector — Hook event handler that reads JSON from stdin and writes to SQLite.

Performance constraint: Must complete in < 100ms. No API calls, no heavy computation.
Only reads JSON, extracts fields, and does a single SQLite INSERT.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from pulse.db import PulseDB

from pulse.config import config as _cfg

_DEFAULT_DB_PATH = _cfg.db_path
_ERROR_INDICATORS = ("error", "Error", "FAILED", "Traceback", "Exception", "FATAL")


def collect(
    stdin_data: str | None = None,
    event_type: str | None = None,
    db: PulseDB | None = None,
) -> None:
    """Hook handler: read event JSON from stdin, write to DB.

    Args:
        stdin_data: JSON string. If None, reads from sys.stdin.
        event_type: The hook event type (for validation). Falls back to payload field.
        db: PulseDB instance. If None, creates one at the default path.
    """
    if stdin_data is None:
        stdin_data = sys.stdin.read()

    payload = json.loads(stdin_data)

    if db is None:
        db = PulseDB(_DEFAULT_DB_PATH)

    event_type = event_type or payload.get("hook_event_name", "Unknown")

    event = {
        "timestamp": datetime.now().isoformat(),
        "session_id": payload.get("session_id", "unknown"),
        "event_type": event_type,
        "project_path": payload.get("cwd"),
        "model": payload.get("model"),
        "tool_name": payload.get("tool_name"),
        "tool_input_summary": _summarize_input(payload.get("tool_input", {})),
        "tool_use_id": payload.get("tool_use_id"),
        "tool_output_success": _check_success(payload),
        "prompt_text": (payload.get("prompt", "") or "")[:500] or None,
        "raw_json": json.dumps(payload),
    }

    db.insert_event(event)

    # On SessionStart, also create/update the session record
    if event_type == "SessionStart":
        db.upsert_session(
            session_id=event["session_id"],
            project_path=event["project_path"],
            model=event["model"],
            started_at=event["timestamp"],
        )


def _summarize_input(tool_input: dict) -> str | None:
    """Create a short summary of tool input without leaking secrets.

    Only logs structural info (file paths, command names), never content.
    """
    if not tool_input:
        return None

    if "command" in tool_input:
        cmd = str(tool_input["command"])[:200]
        return f"bash: {cmd}"

    if "file_path" in tool_input:
        return f"file: {tool_input['file_path']}"

    if "pattern" in tool_input:
        return f"pattern: {tool_input['pattern']}"

    if "prompt" in tool_input:
        return f"prompt: {str(tool_input['prompt'])[:200]}"

    # Generic fallback: keys only, no values (to avoid leaking content)
    keys = list(tool_input.keys())[:5]
    return f"keys: {', '.join(keys)}"


def _check_success(payload: dict) -> bool | None:
    """Check if a PostToolUse was successful based on response content.

    Returns None for non-PostToolUse events.
    Returns True/False for PostToolUse based on error indicator heuristic.
    """
    if payload.get("hook_event_name") != "PostToolUse":
        return None

    response = payload.get("tool_response", {})
    output = str(response.get("content", "")) if isinstance(response, dict) else str(response)

    return not any(indicator in output for indicator in _ERROR_INDICATORS)
