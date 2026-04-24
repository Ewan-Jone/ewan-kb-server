"""Server configuration — loads config.toml from ~/.config/ewankb-server/."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def config_dir() -> Path:
    """Return the config directory path."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "ewankb-server"


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load server configuration from TOML file.

    Search order:
      1. Explicit config_path argument
      2. EWANKB_SERVER_CONFIG env var
      3. ~/.config/ewankb-server/config.toml
    """
    if config_path is None:
        env_path = os.environ.get("EWANKB_SERVER_CONFIG", "")
        if env_path:
            config_path = Path(env_path)
        else:
            config_path = config_dir() / "config.toml"

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"Create one with: cp config.example.toml {config_path}"
        )

    with open(config_path, "rb") as f:
        return tomllib.load(f)


def get_server_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extract server-level settings from config."""
    return config.get("server", {})


def get_kb_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract KB entries from config, returning list of {name, dir} dicts."""
    kbs = config.get("kbs", {})
    entries = []
    for key, val in kbs.items():
        entries.append({
            "name": val.get("name", key),
            "dir": val.get("dir", ""),
        })
    return entries