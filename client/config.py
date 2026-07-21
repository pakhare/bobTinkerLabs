"""
config.py – Load and expose application settings and API keys.
"""
import json
import os
from pathlib import Path

# Resolve config directory relative to this file's location
_BASE = Path(__file__).parent.parent
_SETTINGS_PATH = _BASE / "config" / "settings.json"
_KEYS_PATH = _BASE / "config" / "api_keys.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class _Settings:
    """Singleton wrapper around settings.json and api_keys.json."""

    def __init__(self):
        self._settings = _load_json(_SETTINGS_PATH)
        self._keys = _load_json(_KEYS_PATH)

    # ── monitoring ────────────────────────────────────────────────
    @property
    def poll_interval(self) -> int:
        return self._settings["monitoring"]["poll_interval_seconds"]

    @property
    def sync_interval(self) -> int:
        return self._settings["monitoring"]["sync_interval_minutes"] * 60

    @property
    def idle_threshold(self) -> int:
        return self._settings["monitoring"]["idle_threshold_seconds"]

    @property
    def excluded_apps(self) -> list:
        return self._settings["monitoring"]["excluded_apps"]

    # ── privacy ───────────────────────────────────────────────────
    @property
    def privacy(self) -> dict:
        return self._settings["privacy"]

    # ── ui ────────────────────────────────────────────────────────
    @property
    def theme(self) -> str:
        return self._settings["ui"]["theme"]

    @property
    def minimize_to_tray(self) -> bool:
        return self._settings["ui"]["minimize_to_tray"]

    @property
    def show_notifications(self) -> bool:
        return self._settings["ui"]["show_notifications"]

    # ── backend ───────────────────────────────────────────────────
    @property
    def max_retries(self) -> int:
        return self._settings["backend"]["max_retries"]

    # ── database ──────────────────────────────────────────────────
    @property
    def local_db_path(self) -> Path:
        return _BASE / self._settings["database"]["local_db_path"]

    @property
    def max_local_days(self) -> int:
        return self._settings["database"]["max_local_days"]

    # ── api keys (watsonx Orchestrate) ────────────────────────────
    @property
    def wxo_orchestration_id(self) -> str:
        return self._keys.get("wxo_orchestration_id", "")

    @property
    def wxo_host_url(self) -> str:
        return self._keys.get("wxo_host_url", "")

    @property
    def wxo_crn(self) -> str:
        return self._keys.get("wxo_crn", "")

    @property
    def wxo_agent_id(self) -> str:
        return self._keys.get("wxo_agent_id", "")

    @property
    def wxo_agent_environment_id(self) -> str:
        return self._keys.get("wxo_agent_environment_id", "")

    def reload(self):
        self._settings = _load_json(_SETTINGS_PATH)
        self._keys = _load_json(_KEYS_PATH)


# Module-level singleton – import this everywhere.
settings = _Settings()
