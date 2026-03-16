"""Pulse configuration — single source for all paths and settings.

Loads from ~/.pulse/config.yaml if it exists, otherwise uses defaults.
All hardcoded paths go through this module.
"""

from pathlib import Path

import yaml

_CONFIG_DIR = Path.home() / ".pulse"
_CONFIG_PATH = _CONFIG_DIR / "config.yaml"

_DEFAULTS = {
    "db_path": str(_CONFIG_DIR / "pulse.db"),
    "claude_settings_path": str(Path.home() / ".claude" / "settings.json"),
    "orchestrator_dir": str(Path.home() / ".claude" / "orchestrator" / "projects"),
    "stats_cache_path": str(Path.home() / ".claude" / "stats-cache.json"),
    "language": "de",
    "dashboard": {
        "refresh_interval": 3.0,
    },
}


class PulseConfig:
    """Configuration loaded from YAML with defaults."""

    def __init__(self, config_path: str | None = None) -> None:
        self._path = Path(config_path) if config_path else _CONFIG_PATH
        self._data = dict(_DEFAULTS)

        if self._path.exists():
            with open(self._path) as f:
                user = yaml.safe_load(f) or {}
            self._merge(self._data, user)

    @property
    def db_path(self) -> str:
        return str(Path(self._data["db_path"]).expanduser())

    @property
    def claude_settings_path(self) -> str:
        return str(Path(self._data["claude_settings_path"]).expanduser())

    @property
    def orchestrator_dir(self) -> str:
        return str(Path(self._data["orchestrator_dir"]).expanduser())

    @property
    def language(self) -> str:
        return self._data["language"]

    @property
    def dashboard_refresh(self) -> float:
        return self._data.get("dashboard", {}).get("refresh_interval", 3.0)

    @property
    def stats_cache_path(self) -> str:
        return str(Path(self._data["stats_cache_path"]).expanduser())

    def save_defaults(self) -> None:
        """Write default config to disk if no config exists."""
        if self._path.exists():
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, allow_unicode=True)

    @staticmethod
    def _merge(base: dict, override: dict) -> None:
        """Recursively merge override into base."""
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                PulseConfig._merge(base[k], v)
            else:
                base[k] = v


# Module-level singleton — import and use directly
config = PulseConfig()
