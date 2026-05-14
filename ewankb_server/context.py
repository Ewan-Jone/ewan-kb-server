"""KB context manager — manages multiple KBContext instances."""
from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Any

from ewankb.context import KBContext

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