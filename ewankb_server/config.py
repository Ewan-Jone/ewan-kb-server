"""Server configuration — loads system config and KB registry from separate JSON files."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    """Return the config directory path."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "ewankb-server"


def _resolve_path(config_path: Path | None = None, env_var: str = "", default_name: str = "") -> Path:
    """Resolve a config file path: explicit arg > env var > default location."""
    if config_path is not None:
        return Path(config_path) if isinstance(config_path, str) else config_path
    env_path = os.environ.get(env_var, "")
    if env_path:
        return Path(env_path)
    return config_dir() / default_name


def load_server_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load system-level configuration (port, host, etc.).

    Search order:
      1. Explicit config_path argument
      2. EWANKB_SERVER_CONFIG env var
      3. ~/.config/ewankb-server/config.json

    Returns empty dict if file not found (server has sensible defaults).
    """
    path = _resolve_path(config_path, "EWANKB_SERVER_CONFIG", "config.json")
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_kb_registry(kbs_path: Path | None = None) -> list[dict[str, Any]]:
    """Load KB registry from a separate JSON file.

    Search order:
      1. Explicit kbs_path argument
      2. EWANKB_SERVER_KBS env var
      3. ~/.config/ewankb-server/kbs.json

    Raises FileNotFoundError if KB registry file not found.
    """
    path = _resolve_path(kbs_path, "EWANKB_SERVER_KBS", "kbs.json")
    if not path.exists():
        raise FileNotFoundError(
            f"KB registry file not found: {path}\n"
            f"Create one with: cp kbs.example.json {path}\n"
            f"Or specify path via --kbs CLI arg or EWANKB_SERVER_KBS env var"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = []
    for entry in data.get("kbs", []):
        entries.append({
            "name": entry.get("name", ""),
            "dir": entry.get("dir", ""),
        })
    return entries


def get_server_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extract server-level settings from config."""
    return config.get("server", {})