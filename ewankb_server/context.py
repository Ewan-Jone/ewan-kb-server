"""KB context manager — manages multiple KBContext instances."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ewankb.context import KBContext


class KBManager:
    """Manages multiple KBContext instances, keyed by name."""

    def __init__(self) -> None:
        self.contexts: dict[str, KBContext] = {}

    def load_all(self, kb_entries: list[dict[str, Any]]) -> None:
        """Pre-load all configured KBs (graph + BM25 index).

        Args:
            kb_entries: List of {"name": str, "dir": str} dicts from config.
        """
        for entry in kb_entries:
            name = entry["name"]
            kb_dir = Path(entry.get("dir", ""))
            if not kb_dir or not str(kb_dir).strip():
                print(f"Warning: KB '{name}' has empty 'dir', skipping", flush=True)
                continue
            if not kb_dir.exists():
                print(f"Warning: KB directory '{kb_dir}' not found, skipping '{name}'", flush=True)
                continue
            print(f"Loading KB '{name}' from {kb_dir}...", flush=True)
            ctx = KBContext(kb_dir)
            try:
                ctx.load_graph()
            except FileNotFoundError:
                print(f"  Warning: graph.json not found in '{kb_dir}', "
                      f"KB '{name}' will not support graph queries", flush=True)
            try:
                ctx.load_bm25()
            except Exception as e:
                print(f"  Warning: BM25 index not available for '{name}' ({e}), "
                      f"KB queries will return empty results", flush=True)
            self.contexts[name] = ctx
            info = ctx.info()
            print(f"  Loaded: {info['graph_nodes']} nodes, {info['graph_edges']} edges, "
                  f"{info['bm25_docs']} docs", flush=True)

    def get(self, name: str) -> KBContext:
        """Get a KBContext by name. Raises KeyError if not found."""
        if name not in self.contexts:
            available = list(self.contexts.keys())
            raise KeyError(
                f"KB '{name}' not found. Available: {available}"
            )
        return self.contexts[name]

    def list_kbs(self) -> list[dict[str, Any]]:
        """Return summary info for all loaded KBs."""
        return [ctx.info() for ctx in self.contexts.values()]