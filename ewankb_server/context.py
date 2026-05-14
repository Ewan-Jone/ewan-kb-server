"""KB context manager — manages multiple KBContext instances with auto-reload."""
from __future__ import annotations

import threading
import time
import logging
from pathlib import Path
from typing import Any

from ewankb.context import KBContext
from ewankb_server.config import load_kb_registry

logger = logging.getLogger("ewankb-server")


def _format_size(num_bytes: int) -> str:
    """Human-readable byte size."""
    if num_bytes < 1024:
        return f"{num_bytes}B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f}KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f}MB"


class KBManager:
    """Manages multiple KBContext instances, keyed by name.

    Supports background auto-reload of kb_registry.json and periodic
    graph/BM25 index refresh.
    """

    def __init__(self, reload_interval: int = 60, index_reload_interval: int = 600) -> None:
        self.contexts: dict[str, KBContext] = {}
        self._lock = threading.Lock()
        self._registry_path: Path | None = None
        self._reload_interval = reload_interval
        self._index_reload_interval = index_reload_interval
        self._reload_thread: threading.Thread | None = None
        self._index_reload_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def load_all(self, kb_entries: list[dict[str, Any]],
                 registry_path: Path | None = None) -> None:
        """Pre-load all configured KBs (graph + BM25 index).

        Args:
            kb_entries: List of {"name": str, "dir": str} dicts from config.
            registry_path: Path to kb_registry.json for auto-reload.
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
            self._load_one(name, kb_dir)

        self._stop_event.clear()

        # Start registry auto-reload thread
        if registry_path is not None and self._reload_interval > 0:
            self._registry_path = registry_path
            self._reload_thread = threading.Thread(
                target=self._reload_loop, daemon=True, name="kb-registry-reload"
            )
            self._reload_thread.start()
            logger.info("Registry auto-reload enabled: interval=%ds registry=%s",
                        self._reload_interval, registry_path)

        # Start index auto-reload thread
        if self._index_reload_interval > 0 and len(self.contexts) > 0:
            self._index_reload_thread = threading.Thread(
                target=self._index_reload_loop, daemon=True, name="kb-index-reload"
            )
            self._index_reload_thread.start()
            logger.info("Index auto-reload enabled: interval=%ds", self._index_reload_interval)

    def _load_one(self, name: str, kb_dir: Path) -> None:
        """Load a single KB and add to contexts (caller must hold lock)."""
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

    def _unload_one(self, name: str) -> None:
        """Remove a KB from contexts (caller must hold lock)."""
        if name in self.contexts:
            del self.contexts[name]
            print(f"Unloaded KB '{name}'", flush=True)

    def _reload_loop(self) -> None:
        """Background thread: periodically check kb_registry.json for changes."""
        while not self._stop_event.wait(timeout=self._reload_interval):
            try:
                entries = load_kb_registry(self._registry_path)
            except FileNotFoundError:
                logger.warning("Auto-reload: registry file not found, skipping")
                continue
            except Exception:
                logger.warning("Auto-reload: failed to read registry", exc_info=True)
                continue

            with self._lock:
                current_names = set(self.contexts.keys())
                new_names = {e["name"] for e in entries}

                added = new_names - current_names
                removed = current_names - new_names

                if not added and not removed:
                    continue

                if removed:
                    logger.info("Auto-reload: removing KBs %s", removed)
                    for name in removed:
                        self._unload_one(name)

                if added:
                    logger.info("Auto-reload: adding KBs %s", added)
                    for entry in entries:
                        if entry["name"] in added:
                            kb_dir = Path(entry.get("dir", ""))
                            if kb_dir.exists():
                                self._load_one(entry["name"], kb_dir)
                            else:
                                print(f"Warning: KB '{entry['name']}' dir not found: {kb_dir}, skipping",
                                      flush=True)

    def _index_reload_loop(self) -> None:
        """Background thread: periodically reload graph + BM25 for all KBs."""
        while not self._stop_event.wait(timeout=self._index_reload_interval):
            self.refresh_indexes()

    def refresh(self) -> None:
        """Full refresh: reload registry, then all graph/BM25 indexes.

        Called by SIGUSR1 signal handler or 'refresh' CLI command.
        """
        logger.info("Manual refresh triggered")
        # Reload registry
        if self._registry_path is not None:
            try:
                entries = load_kb_registry(self._registry_path)
            except Exception:
                logger.warning("Refresh: failed to read registry", exc_info=True)
            else:
                with self._lock:
                    current_names = set(self.contexts.keys())
                    new_names = {e["name"] for e in entries}
                    added = new_names - current_names
                    removed = current_names - new_names

                    if removed:
                        logger.info("Refresh: removing KBs %s", removed)
                        for name in removed:
                            self._unload_one(name)
                    if added:
                        logger.info("Refresh: adding KBs %s", added)
                        for entry in entries:
                            if entry["name"] in added:
                                kb_dir = Path(entry.get("dir", ""))
                                if kb_dir.exists():
                                    self._load_one(entry["name"], kb_dir)

        # Reload all graph/BM25 indexes
        self.refresh_indexes()

    def refresh_indexes(self) -> None:
        """Reload graph + BM25 for all currently loaded KBs."""
        with self._lock:
            names = list(self.contexts.keys())
            dirs = [Path(ctx.kb_dir) for ctx in self.contexts.values()]

        if not names:
            return

        for name, kb_dir in zip(names, dirs):
            try:
                new_ctx = KBContext(kb_dir)
                try:
                    new_ctx.load_graph()
                except FileNotFoundError:
                    pass
                try:
                    new_ctx.load_bm25()
                except Exception:
                    pass

                with self._lock:
                    self.contexts[name] = new_ctx

                info = new_ctx.info()
                logger.info(
                    "Index refreshed for '%s': %s nodes, %s edges, %s docs",
                    name, info["graph_nodes"], info["graph_edges"], info["bm25_docs"],
                )
            except Exception:
                logger.warning("Failed to refresh index for KB '%s'", name, exc_info=True)

    def shutdown(self) -> None:
        """Stop the auto-reload thread."""
        self._stop_event.set()

    def get(self, name: str) -> KBContext:
        """Get a KBContext by name. Raises KeyError if not found."""
        with self._lock:
            if name not in self.contexts:
                available = list(self.contexts.keys())
                raise KeyError(
                    f"KB '{name}' not found. Available: {available}"
                )
            return self.contexts[name]

    def list_kbs(self) -> list[dict[str, Any]]:
        """Return summary info for all loaded KBs."""
        with self._lock:
            return [ctx.info() for ctx in self.contexts.values()]

    # ── Source file search & read ────────────────────────────────────────────

    def _source_dir(self, kb_name: str) -> Path:
        """Resolve and validate the source directory for a KB."""
        ctx = self.get(kb_name)
        source_dir = Path(ctx.kb_dir) / "source"
        if not source_dir.exists():
            raise FileNotFoundError(f"Source directory not found for KB '{kb_name}': {source_dir}")
        return source_dir

    def search_source(
        self,
        query_text: str,
        kb_name: str,
        glob_pattern: str = "*",
        max_results: int = 50,
    ) -> str:
        """Grep source files within a knowledge base's source/ directory.

        Args:
            query_text: Text or regex to search for (case-insensitive substring match).
            kb_name: Knowledge base name.
            glob_pattern: File glob to filter files (e.g. "*.java", "*.py").
            max_results: Maximum number of matching lines to return.

        Returns formatted results: file path, line number, and matching line.
        """
        t0 = time.perf_counter()
        source_dir = self._source_dir(kb_name)
        query_lower = query_text.lower()

        files = sorted(source_dir.rglob(glob_pattern))
        file_count = len(files)

        results: list[tuple[str, int, str]] = []
        files_matched = 0
        for fp in files:
            if not fp.is_file():
                continue
            if len(results) >= max_results:
                break
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            file_had_match = False
            for lineno, line in enumerate(content.splitlines(), start=1):
                if query_lower in line.lower():
                    results.append((str(fp.relative_to(source_dir)), lineno, line.strip()))
                    file_had_match = True
                    if len(results) >= max_results:
                        break
            if file_had_match:
                files_matched += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000

        header = (
            f"search_source(kb='{kb_name}', query='{query_text}', glob='{glob_pattern}')\n"
            f"  Scanned {file_count} file(s), matched {len(results)} line(s) across {files_matched} file(s)\n"
        )

        if not results:
            body = "(no matches found)"
        else:
            lines = []
            for path, lineno, text in results:
                snippet = text[:200] + ("..." if len(text) > 200 else "")
                lines.append(f"  {path}:{lineno}: {snippet}")
            body = "\n".join(lines)

        output = header + body
        output_bytes = len(output.encode("utf-8"))

        logger.info(
            "search_source | kb=%s query=%r glob=%r files=%d matches=%d matched_files=%d "
            "time=%.1fms output=%s max_results=%d",
            kb_name, query_text, glob_pattern, file_count, len(results), files_matched,
            elapsed_ms, _format_size(output_bytes), max_results,
        )

        return output

    def read_source_file(
        self,
        kb_name: str,
        relative_path: str,
        start_line: int = 1,
        end_line: int = 0,
    ) -> str:
        """Read a source file from a knowledge base.

        Args:
            kb_name: Knowledge base name.
            relative_path: File path relative to the KB's source/ directory.
            start_line: 1-based line number to start reading from.
            end_line: 1-based line number to end at (0 = EOF).

        Returns file content with line numbers.
        """
        t0 = time.perf_counter()
        source_dir = self._source_dir(kb_name)

        # Security: prevent path traversal
        requested_path = (source_dir / relative_path).resolve()
        if not str(requested_path).startswith(str(source_dir.resolve())):
            raise ValueError(f"Path traversal denied: '{relative_path}'")

        if not requested_path.exists():
            raise FileNotFoundError(f"File not found: '{relative_path}' in KB '{kb_name}'")
        if not requested_path.is_file():
            raise ValueError(f"Not a file: '{relative_path}' in KB '{kb_name}'")

        file_size = requested_path.stat().st_size
        content = requested_path.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()

        total_lines = len(all_lines)
        if end_line == 0:
            end_line = total_lines
        end_line = min(end_line, total_lines)
        start_line = max(1, min(start_line, total_lines))

        selected = all_lines[start_line - 1:end_line]

        output_lines = []
        for i, line_text in enumerate(selected, start=start_line):
            output_lines.append(f"{i:6d}| {line_text}")
        output = "\n".join(output_lines)
        output_bytes = len(output.encode("utf-8"))

        elapsed_ms = (time.perf_counter() - t0) * 1000
        shown = len(selected)

        logger.info(
            "read_source_file | kb=%s path=%r lines=%d-%d/%d shown=%d "
            "file=%s time=%.1fms output=%s",
            kb_name, relative_path, start_line, end_line, total_lines, shown,
            _format_size(file_size), elapsed_ms, _format_size(output_bytes),
        )

        return (
            f"read_source_file(kb='{kb_name}', path='{relative_path}', "
            f"L{start_line}-{end_line} / {total_lines} total)\n"
            f"  File size: {_format_size(file_size)}, Showing: {shown} line(s)\n\n"
            f"{output}"
        )