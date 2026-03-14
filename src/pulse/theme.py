"""Pulse Design System — inspired by Apple HIG.

Principles:
1. CLARITY    Content is king. Every element earns its place.
2. HIERARCHY  Most important info gets most visual weight.
3. PURPOSE    Color = meaning, never decoration.
4. CONSISTENCY Same patterns, spacing, vocabulary everywhere.
5. BREATHING  Whitespace is a feature. Dense ≠ useful.
6. FEEDBACK   Acknowledge actions. Show results.

Typography Hierarchy (terminal):
  TITLE     bold          Panel titles, hero numbers
  LABEL     bold cyan     Field names, section headers
  VALUE     default       Data values
  SECONDARY dim           Timestamps, IDs, metadata
  SUCCESS   green         Positive outcomes, completed items
  WARNING   yellow        Attention needed, in-progress
  DANGER    red           Errors, critical issues

Status Vocabulary (consistent everywhere):
  ● active    (green)
  ○ paused    (yellow)
  ✓ done      (dim)
  ! attention (red)
  · neutral   (dim)
  → next step (cyan)
  ↻ continuous

Spacing:
  2-space indent for all content within panels
  1 blank line between sections
  No trailing decorative lines
"""

# ── Status markers ─────────────────────────────────────────────────

STATUS_DOT = {"active": "●", "paused": "○", "done": "✓", "blocked": "!"}
STATUS_STYLE = {"active": "green", "paused": "yellow", "done": "dim", "blocked": "red"}

TASK_MARKER = {"done": "✓", "in_progress": "›", "pending": " ", "blocked": "!"}
TASK_STYLE = {"done": "dim", "in_progress": "yellow", "pending": "", "blocked": "red"}

# ── Category labels ────────────────────────────────────────────────

CATEGORY_LABEL = {
    "tools": "Tools",
    "learning": "Learning",
    "system": "System",
    "research": "Research",
    "content": "Content",
    "career": "Career",
}

# ── Formatting helpers ─────────────────────────────────────────────

def bar(value: float, max_val: float = 100.0, width: int = 10) -> str:
    """Progress bar: ████░░░░░░"""
    filled = int(width * min(value, max_val) / max_val) if max_val > 0 else 0
    return "█" * filled + "░" * (width - filled)


def short_path(path: str, max_len: int = 28) -> str:
    """Shorten a path to its last component if too long."""
    if not path:
        return "?"
    from pathlib import Path as P
    if len(path) <= max_len:
        return path
    parts = P(path).parts
    return parts[-1] if parts else path


def duration_human(minutes: float) -> str:
    """Format minutes as human-readable duration."""
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes:.0f} min"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.0f}d"


def time_ago(iso_timestamp: str) -> str:
    """Format an ISO timestamp as relative time."""
    from datetime import datetime
    try:
        ts = datetime.fromisoformat(iso_timestamp)
        now = datetime.now()
        diff = now - ts
        if diff.days == 0:
            hours = diff.seconds // 3600
            if hours == 0:
                mins = diff.seconds // 60
                return f"vor {mins} min" if mins > 0 else "jetzt"
            return f"vor {hours}h"
        elif diff.days == 1:
            return "gestern"
        else:
            return f"vor {diff.days}d"
    except (ValueError, TypeError):
        return "?"
