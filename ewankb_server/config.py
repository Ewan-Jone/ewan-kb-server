"""Server configuration — loads KB registry from ~/.ewankb/kb_registry.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_server_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load server config from an explicit path or env var.

    No default path — if neither is provided, returns empty dict
    (server uses CLI argument defaults or built-in values).

    Search order:
      1. Explicit config_path argument (--config CLI)
      2. EWANKB_SERVER_CONFIG env var
    """
    if config_path is not None:
        path = Path(config_path)
    elif os.environ.get("EWANKB_SERVER_CONFIG"):
        path = Path(os.environ["EWANKB_SERVER_CONFIG"])
    else:
        return {}
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_kb_registry(registry_path: Path | None = None) -> list[dict[str, Any]]:
    """Load KB registry from ~/.ewankb/kb_registry.json.

    Registry format (shared with ewankb-hub):
        {"<name>": {"dir": "...", "name": "...", "description": "..."}}

    Search order:
      1. Explicit registry_path argument (--kbs CLI)
      2. EWANKB_SERVER_KBS env var
      3. ~/.ewankb/kb_registry.json

    Raises FileNotFoundError if no registry file found.
    """
    if registry_path is not None:
        path = Path(registry_path)
    elif os.environ.get("EWANKB_SERVER_KBS"):
        path = Path(os.environ["EWANKB_SERVER_KBS"])
    else:
        path = Path.home() / ".ewankb" / "kb_registry.json"

    if not path.exists():
        raise FileNotFoundError(
            f"KB registry file not found: {path}\n"
            f"Create ~/.ewankb/kb_registry.json to register knowledge bases, or\n"
            f"specify a custom path via --registry CLI arg or EWANKB_SERVER_KBS env var"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    global_dir = Path.home() / ".ewankb"
    entries = []
    for key, entry in data.items():
        if key.startswith("_"):
            continue
        if not isinstance(entry, dict):
            continue
        dir_name = entry.get("dir", key)
        kb_dir = Path(dir_name)
        if not kb_dir.is_absolute():
            kb_dir = global_dir / dir_name
        entries.append({
            "name": key,
            "dir": str(kb_dir),
            "display_name": entry.get("name", ""),
            "description": entry.get("description", ""),
        })
    return entries


def get_server_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extract server-level settings from config."""
    return config.get("server", {})