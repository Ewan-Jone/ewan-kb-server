"""ewan-kb-server — MCP + HTTP query server for ewankb knowledge bases."""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ewankb_server.config import load_server_config, get_server_settings, load_kb_registry
from ewankb_server.context import KBManager, _format_size

PID_FILE = Path.home() / ".ewankb" / "ewankb-server.pid"
_IS_WINDOWS = sys.platform == "win32"

_access_logger = logging.getLogger("ewankb-server.access")

manager: KBManager | None = None


def _get_manager() -> KBManager:
    if manager is None:
        raise RuntimeError("KBManager not initialized. Start the server first.")
    return manager


class AccessLogMiddleware:
    """ASGI middleware that logs end-to-end request timing (including network)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        t0 = time.perf_counter()
        response_status: int = 0
        body_size: int = 0

        async def send_wrapper(message: dict) -> None:
            nonlocal response_status, body_size
            if message["type"] == "http.response.start":
                response_status = message.get("status", 0)
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    body_size += len(body)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            path = scope.get("path", "/")
            method = scope.get("method", "?")
            _access_logger.info(
                "%s %s -> %s | total=%.1fms body=%s",
                method, path, response_status, elapsed_ms, _format_size(body_size),
            )


mcp = FastMCP(
    name="ewankb-server",
    instructions=(
        "Use query_graph to explore code relationships and semantic connections in the knowledge graph. "
        "Use query_kb to search documents by keyword (BM25). "
        "Use search_source to grep source files for exact text matches. "
        "Use read_source_file to read a specific source file's content with line numbers. "
        "Specify the 'kb' parameter to choose which knowledge base to query."
    ),
)
# AccessLogMiddleware will be added via app.add_middleware() in main()


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def query_graph(
    query_text: str,
    kb: str = "default",
    traversal: str = "bfs",
    max_nodes: int = 50,
) -> str:
    """Query the knowledge graph for code relationships and semantic connections.

    Args:
        query_text: Natural language query about the codebase
        kb: Name of the knowledge base to query (must match config)
        traversal: 'bfs' for overview of connected concepts, 'dfs' for tracing a single path
        max_nodes: Maximum number of nodes to visit (default: 50)

    Returns rendered subgraph as readable text.
    """
    mgr = _get_manager()
    ctx = mgr.get(kb)
    return ctx.query_graph(query_text, traversal=traversal, max_nodes=max_nodes)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def query_kb(
    query_text: str,
    kb: str = "default",
    max_results: int = 8,
    domain: str = "",
) -> str:
    """Search knowledge base documents using BM25 keyword ranking.

    Searches domains/, knowledgeBase/, and source/docs/ for relevant documents.

    Args:
        query_text: Search keywords or question
        kb: Name of the knowledge base to query (must match config)
        max_results: Maximum number of documents to return (default: 8)
        domain: Optional domain filter (e.g. "收付款管理")

    Returns formatted document excerpts with metadata.
    """
    mgr = _get_manager()
    ctx = mgr.get(kb)
    return ctx.query_kb(
        query_text,
        max_results=max_results,
        domain_filter=domain if domain else None,
    )


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
def list_kbs() -> str:
    """List all available knowledge bases with their status.

    Returns a summary of each loaded KB: directory, graph nodes/edges, document count.
    """
    mgr = _get_manager()
    kbs = mgr.list_kbs()
    lines = []
    for info in kbs:
        lines.append(
            f"- {info['project_name']}: {info['graph_nodes']} nodes, "
            f"{info['graph_edges']} edges, {info['bm25_docs']} docs "
            f"(dir: {info['kb_dir']})"
        )
    return "\n".join(lines)


# ── Source file tools ───────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True})
def search_source(
    query_text: str,
    kb: str = "default",
    glob: str = "*",
    max_results: int = 50,
) -> str:
    """Search source files within a knowledge base using text matching.

    Searches all files in the KB's source/ directory that match the glob pattern.
    Returns matching file paths, line numbers, and line content.

    Args:
        query_text: Text to search for (case-insensitive substring match).
        kb: Name of the knowledge base to search.
        glob: File glob pattern to filter files (e.g. "*.java", "*.py"). Default "*" matches all files.
        max_results: Maximum number of matching lines to return (default: 50).

    Returns formatted search results with file paths, line numbers, and snippets.
    """
    t0 = time.perf_counter()
    mgr = _get_manager()
    result = mgr.search_source(query_text, kb, glob_pattern=glob, max_results=max_results)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    result_bytes = len(result.encode("utf-8"))
    logging.getLogger("ewankb-server").info(
        "MCP search_source | kb=%s query=%r glob=%r max_results=%d time=%.1fms output=%s",
        kb, query_text, glob, max_results, elapsed_ms, _format_size(result_bytes),
    )
    return result


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True})
def read_source_file(
    kb: str,
    path: str,
    start_line: int = 1,
    end_line: int = 0,
) -> str:
    """Read a source file from a knowledge base.

    Args:
        kb: Name of the knowledge base.
        path: File path relative to the KB's source/ directory.
        start_line: 1-based line number to start reading from (default: 1).
        end_line: 1-based line number to end at (0 = read to end of file).

    Returns file content with line numbers.
    """
    t0 = time.perf_counter()
    mgr = _get_manager()
    result = mgr.read_source_file(kb, path, start_line=start_line, end_line=end_line)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    result_bytes = len(result.encode("utf-8"))
    logging.getLogger("ewankb-server").info(
        "MCP read_source_file | kb=%s path=%r L%d-%d time=%.1fms output=%s",
        kb, path, start_line, end_line, elapsed_ms, _format_size(result_bytes),
    )
    return result


# ── HTTP debug endpoints ────────────────────────────────────────────────────

@mcp.custom_route("/query/graph", methods=["GET"])
async def http_query_graph(request: Request) -> JSONResponse:
    """REST endpoint for graph query (debug only)."""
    query_text = request.query_params.get("text", "")
    kb = request.query_params.get("kb", "default")
    traversal = request.query_params.get("traversal", "bfs")
    try:
        max_nodes = int(request.query_params.get("max_nodes", "50"))
    except ValueError:
        return JSONResponse({"error": "max_nodes must be an integer"}, status_code=400)

    if not query_text:
        return JSONResponse({"error": "Missing 'text' parameter"}, status_code=400)

    try:
        mgr = _get_manager()
        ctx = mgr.get(kb)
        result = ctx.query_graph(query_text, traversal=traversal, max_nodes=max_nodes, verbose=True)
        result["kb"] = kb
        return JSONResponse(result)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/query/kb", methods=["GET"])
async def http_query_kb(request: Request) -> JSONResponse:
    """REST endpoint for KB query (debug only)."""
    query_text = request.query_params.get("text", "")
    kb = request.query_params.get("kb", "default")
    try:
        max_results = int(request.query_params.get("max_results", "8"))
    except ValueError:
        return JSONResponse({"error": "max_results must be an integer"}, status_code=400)
    domain = request.query_params.get("domain", "")

    if not query_text:
        return JSONResponse({"error": "Missing 'text' parameter"}, status_code=400)

    try:
        mgr = _get_manager()
        ctx = mgr.get(kb)
        result = ctx.query_kb(
            query_text,
            max_results=max_results,
            domain_filter=domain if domain else None,
        )
        return JSONResponse({"result": result, "kb": kb})
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/kbs", methods=["GET"])
async def http_list_kbs(request: Request) -> JSONResponse:
    """REST endpoint to list available KBs."""
    mgr = _get_manager()
    return JSONResponse({"kbs": mgr.list_kbs()})


@mcp.custom_route("/health", methods=["GET"])
async def http_health(request: Request) -> JSONResponse:
    """Health check endpoint."""
    mgr = _get_manager()
    return JSONResponse({"status": "ok", "kbs": len(mgr.contexts)})


@mcp.custom_route("/search/source", methods=["GET"])
async def http_search_source(request: Request) -> JSONResponse:
    """REST endpoint for source file search (debug only)."""
    query_text = request.query_params.get("text", "")
    kb = request.query_params.get("kb", "default")
    glob_pattern = request.query_params.get("glob", "*")
    try:
        max_results = int(request.query_params.get("max_results", "50"))
    except ValueError:
        return JSONResponse({"error": "max_results must be an integer"}, status_code=400)

    if not query_text:
        return JSONResponse({"error": "Missing 'text' parameter"}, status_code=400)

    try:
        mgr = _get_manager()
        result = mgr.search_source(query_text, kb, glob_pattern=glob_pattern, max_results=max_results)
        return JSONResponse({"result": result, "kb": kb})
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/read/source", methods=["GET"])
async def http_read_source_file(request: Request) -> JSONResponse:
    """REST endpoint to read a source file (debug only)."""
    kb = request.query_params.get("kb", "default")
    path = request.query_params.get("path", "")
    try:
        start_line = int(request.query_params.get("start_line", "1"))
    except ValueError:
        return JSONResponse({"error": "start_line must be an integer"}, status_code=400)
    try:
        end_line = int(request.query_params.get("end_line", "0"))
    except ValueError:
        return JSONResponse({"error": "end_line must be an integer"}, status_code=400)

    if not path:
        return JSONResponse({"error": "Missing 'path' parameter"}, status_code=400)

    try:
        mgr = _get_manager()
        result = mgr.read_source_file(kb, path, start_line=start_line, end_line=end_line)
        return JSONResponse({"result": result, "kb": kb})
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@mcp.custom_route("/_refresh", methods=["POST"])
async def http_refresh(request: Request) -> JSONResponse:
    """Internal endpoint: trigger full reload of registry + indexes."""
    mgr = _get_manager()
    try:
        mgr.refresh()
        return JSONResponse({"status": "ok", "message": "refresh completed"})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ── CLI entry point ─────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argument parser (shared by default mode and subcommands)."""
    parser = argparse.ArgumentParser(
        prog="ewankb-server",
        description="Query server for ewankb knowledge bases (MCP + HTTP).",
    )
    parser.add_argument(
        "--transport",
        default="sse",
        choices=["sse", "http"],
        help="Transport mode: 'sse' for MCP SSE (default), 'http' for Streamable HTTP MCP",
    )
    parser.add_argument("--port", type=int, default=22902, help="HTTP port (default: 22902)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP host (default: 0.0.0.0)")
    parser.add_argument("--config", type=str, default=None,
                        help="System config file path")
    parser.add_argument("--registry", type=str, default=None,
                        help="KB registry file path (default: ~/.ewankb/kb_registry.json)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: INFO)")
    parser.add_argument("--log-file", type=str, default=".ewan-kb-server.log",
                        help="Log file path (default: .ewan-kb-server.log)")
    parser.add_argument("--log-format", default="text", choices=["text", "json"],
                        help="Log format: 'text' for human-readable, 'json' for machine parsing (default: text)")
    parser.add_argument("--reload-interval", type=int, default=60,
                        help="KB registry auto-reload interval in seconds (default: 60, 0 to disable)")
    parser.add_argument("--index-reload-interval", type=int, default=600,
                        help="Graph/BM25 index auto-reload interval in seconds (default: 600, 0 to disable)")
    return parser


def _setup_logging(args: argparse.Namespace) -> None:
    """Configure logging from parsed args."""
    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, args.log_level))
    handlers.append(console_handler)

    if args.log_file:
        log_dir = Path(args.log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            args.log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(getattr(logging, args.log_level))
        handlers.append(file_handler)

    if args.log_format == "json":
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                import datetime as _dt
                payload = {
                    "ts": _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                    "func": record.funcName,
                }
                return json.dumps(payload, ensure_ascii=False)
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    for h in handlers:
        h.setFormatter(fmt)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        handlers=handlers,
        force=True,
    )
    logging.getLogger("ewankb-server").info(
        "Logging initialized | level=%s file=%s format=%s",
        args.log_level, args.log_file or "(none)", args.log_format,
    )


def _resolve_registry_path(registry_arg: str | None) -> Path | None:
    """Resolve the actual registry path from CLI arg, env var, or default."""
    import os as _os
    if registry_arg is not None:
        return Path(registry_arg)
    if _os.environ.get("EWANKB_SERVER_KBS"):
        return Path(_os.environ["EWANKB_SERVER_KBS"])
    return Path.home() / ".ewankb" / "kb_registry.json"


def _run_server(args: argparse.Namespace) -> None:
    """Run the server in the current process (foreground)."""
    global manager
    config = load_server_config(args.config)
    settings = get_server_settings(config)
    kb_entries = load_kb_registry(args.registry)

    manager = KBManager(
        reload_interval=args.reload_interval,
        index_reload_interval=args.index_reload_interval,
    )
    print(f"Loading {len(kb_entries)} knowledge base(s)...", flush=True)
    registry_path = _resolve_registry_path(args.registry)
    manager.load_all(kb_entries, registry_path=registry_path)
    print(f"Ready. {len(manager.contexts)} KB(s) loaded.", flush=True)

    # Register SIGUSR1 handler for manual refresh (Unix only)
    if not _IS_WINDOWS:
        def _on_refresh(signum, frame):
            manager.refresh()
        signal.signal(signal.SIGUSR1, _on_refresh)

    port = settings.get("port", args.port)
    host = settings.get("host", args.host)

    transport = "sse" if args.transport == "sse" else "streamable-http"
    label = "SSE" if args.transport == "sse" else "Streamable HTTP"

    app = mcp.http_app(transport=transport)
    app.add_middleware(AccessLogMiddleware)
    logging.getLogger("ewankb-server").info("Access log middleware enabled")

    print(f"Starting MCP {label} server on {host}:{port}", flush=True)
    import uvicorn
    uvicorn.run(app, host=host, port=port)


def _cmd_start(args: argparse.Namespace) -> None:
    """Start the server as a background daemon."""
    if PID_FILE.exists():
        pid = _read_pid()
        if pid is not None and _is_running(pid):
            print(f"Server is already running (PID: {pid})")
            sys.exit(1)
        PID_FILE.unlink(missing_ok=True)

    # Build args for the child process (strip any subcommand so child runs in foreground)
    _SUBCOMMANDS = {"start", "stop", "restart", "refresh"}
    child_argv = [sys.executable, "-m", "ewankb_server.server"]
    for arg in sys.argv[1:]:
        if arg in _SUBCOMMANDS:
            continue
        child_argv.append(arg)

    # Ensure .ewankb directory exists
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Spawn detached child process
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if _IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kwargs["start_new_session"] = True

    child = subprocess.Popen(child_argv, **popen_kwargs)

    PID_FILE.write_text(json.dumps({"pid": child.pid, "port": args.port, "host": args.host}))
    print(f"Server started (PID: {child.pid}, port: {args.port})")


def _read_pid_info() -> dict[str, Any] | None:
    """Read PID info from PID file. Returns None if file missing or corrupt."""
    try:
        info = json.loads(PID_FILE.read_text().strip())
        if isinstance(info, dict) and "pid" in info:
            return info
        # Legacy format: plain PID
        return {"pid": int(PID_FILE.read_text().strip())}
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None


def _read_pid() -> int | None:
    """Read PID from PID file. Returns None if file missing or corrupt."""
    info = _read_pid_info()
    return info["pid"] if info else None


def _is_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_process(pid: int, force: bool = False) -> None:
    """Kill a process. Uses SIGTERM (or taskkill on Windows)."""
    if _IS_WINDOWS:
        flag = "/F" if force else ""
        subprocess.run(["taskkill", "/PID", str(pid), flag] if flag else ["taskkill", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)


def _cmd_stop() -> None:
    """Stop a running background server."""
    pid = _read_pid()
    if pid is None:
        print("No PID file found. Server is not running.")
        sys.exit(1)

    if not _is_running(pid):
        print(f"PID {pid} is not running. Removing stale PID file.")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    _kill_process(pid)
    print(f"Stopping server (PID: {pid})...", end=" ", flush=True)

    for _ in range(50):  # 5 seconds with 0.1s intervals
        time.sleep(0.1)
        if not _is_running(pid):
            print("stopped")
            PID_FILE.unlink(missing_ok=True)
            return

    # Force kill if still alive
    print("timeout, force killing...", end=" ", flush=True)
    _kill_process(pid, force=True)
    time.sleep(0.5)
    print("stopped")
    PID_FILE.unlink(missing_ok=True)


def _cmd_restart(args: argparse.Namespace) -> None:
    """Restart the server (stop if running, then start)."""
    if PID_FILE.exists():
        pid = _read_pid()
        if pid is not None and _is_running(pid):
            _cmd_stop()
    _cmd_start(args)


def _cmd_refresh() -> None:
    """Send a refresh request to the running server via HTTP."""
    info = _read_pid_info()
    if info is None:
        print("No PID file found. Server is not running.")
        sys.exit(1)

    pid = info["pid"]
    if not _is_running(pid):
        print(f"PID {pid} is not running. Removing stale PID file.")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    port = info.get("port", 22902)
    host = info.get("host", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"

    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://{host}:{port}/_refresh", method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            print(f"Refresh response: {body}")
    except Exception as e:
        print(f"Failed to refresh server: {e}")
        sys.exit(1)


def main() -> None:
    parser = _build_arg_parser()
    sub = parser.add_subparsers(dest="command")

    start_parser = sub.add_parser("start", help="Start server in background")
    # Re-add all server options for the start subcommand
    start_parser.add_argument("--transport", default="sse", choices=["sse", "http"])
    start_parser.add_argument("--port", type=int, default=22902)
    start_parser.add_argument("--host", default="0.0.0.0")
    start_parser.add_argument("--config", type=str, default=None)
    start_parser.add_argument("--registry", type=str, default=None)
    start_parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    start_parser.add_argument("--log-file", type=str, default=".ewan-kb-server.log")
    start_parser.add_argument("--log-format", default="text", choices=["text", "json"])
    start_parser.add_argument("--reload-interval", type=int, default=60)
    start_parser.add_argument("--index-reload-interval", type=int, default=600)

    sub.add_parser("stop", help="Stop background server")
    sub.add_parser("refresh", help="Trigger full reload (registry + graph/BM25) on running server")

    restart_parser = sub.add_parser("restart", help="Restart server")
    restart_parser.add_argument("--transport", default="sse", choices=["sse", "http"])
    restart_parser.add_argument("--port", type=int, default=22902)
    restart_parser.add_argument("--host", default="0.0.0.0")
    restart_parser.add_argument("--config", type=str, default=None)
    restart_parser.add_argument("--registry", type=str, default=None)
    restart_parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    restart_parser.add_argument("--log-file", type=str, default=".ewan-kb-server.log")
    restart_parser.add_argument("--log-format", default="text", choices=["text", "json"])
    restart_parser.add_argument("--reload-interval", type=int, default=60)
    restart_parser.add_argument("--index-reload-interval", type=int, default=600)

    args = parser.parse_args()

    if args.command == "start":
        _setup_logging(args)
        _cmd_start(args)
    elif args.command == "stop":
        _cmd_stop()
    elif args.command == "refresh":
        _cmd_refresh()
    elif args.command == "restart":
        _setup_logging(args)
        _cmd_restart(args)
    else:
        # Default: foreground mode (backward compatible)
        _setup_logging(args)
        _run_server(args)


if __name__ == "__main__":
    main()