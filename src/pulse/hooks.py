"""Pulse hooks — Install/uninstall Claude Code hook configuration.

Writes hook entries to Claude Code's settings.json so that every session
event is forwarded to `pulse collect`.
"""

import json
from pathlib import Path

_P1_EVENTS = ["SessionStart", "SessionEnd", "PreToolUse", "PostToolUse",
              "UserPromptSubmit", "Stop"]
_TOOL_EVENTS = {"PreToolUse", "PostToolUse"}
_DEFAULT_SETTINGS_PATH = str(Path.home() / ".claude" / "settings.json")


def generate_hook_config() -> dict:
    """Generate the hooks configuration dict for Claude Code settings."""
    config = {}
    for event in _P1_EVENTS:
        entry = {
            "hooks": [{
                "type": "command",
                "command": f"pulse collect --event {event}",
            }],
        }
        if event in _TOOL_EVENTS:
            entry["matcher"] = ""
        config[event] = [entry]
    return config


def install_hooks(settings_path: str | None = None) -> None:
    """Install Pulse hooks into Claude Code settings.json.

    - Preserves existing settings and hooks
    - Idempotent: running twice does not create duplicates
    """
    path = Path(settings_path or _DEFAULT_SETTINGS_PATH)

    if path.exists():
        settings = json.loads(path.read_text())
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    pulse_config = generate_hook_config()

    for event_name, pulse_entries in pulse_config.items():
        existing = hooks.get(event_name, [])

        # Remove any existing pulse hooks (for idempotency)
        existing = [
            h for h in existing
            if not _is_pulse_hook(h)
        ]

        # Add pulse hooks
        existing.extend(pulse_entries)
        hooks[event_name] = existing

    settings["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")


def uninstall_hooks(settings_path: str | None = None) -> None:
    """Remove Pulse hooks from Claude Code settings.json.

    Preserves all non-Pulse hooks.
    """
    path = Path(settings_path or _DEFAULT_SETTINGS_PATH)

    if not path.exists():
        return

    settings = json.loads(path.read_text())
    hooks = settings.get("hooks", {})

    for event_name in list(hooks.keys()):
        hooks[event_name] = [
            h for h in hooks[event_name]
            if not _is_pulse_hook(h)
        ]
        # Clean up empty lists
        if not hooks[event_name]:
            del hooks[event_name]

    settings["hooks"] = hooks
    path.write_text(json.dumps(settings, indent=2) + "\n")


def _is_pulse_hook(hook_entry: dict) -> bool:
    """Check if a hook entry belongs to Pulse."""
    for h in hook_entry.get("hooks", []):
        if "pulse collect" in h.get("command", ""):
            return True
    return False
