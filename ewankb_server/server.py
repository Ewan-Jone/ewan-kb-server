"""ewan-kb-server — MCP + HTTP query server for ewankb knowledge bases."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ewankb_server.config import load_config, get_server_settings, get_kb_entries
from ewankb_server.context import KBManager


manager: KBManager | None = None


def _get_manager() -> KBManager:
    if manager is None:
        raise RuntimeError("KBManager not initialized. Start the server first.")
    return manager


mcp = FastMCP(
    name="ewankb-server",
    instructions=(
        "Use query_graph to explore code relationships and semantic connections in the knowledge graph. "
        "Use query_kb to search documents by keyword (BM25). "
        "Specify the 'kb' parameter to choose which knowledge base to query."
    ),
)


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
        result = ctx.query_graph(query_text, traversal=traversal, max_nodes=max_nodes)
        return JSONResponse({"result": result, "kb": kb})
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


# ── CLI entry point ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ewankb-server",
        description="Query server for ewankb knowledge bases (MCP + HTTP).",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "http"],
        help="Transport mode: 'stdio' for MCP (default), 'http' for HTTP debug server",
    )
    parser.add_argument("--port", type=int, default=3000, help="HTTP port (default: 3000)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    args = parser.parse_args()

    # Load config and initialize KBs
    global manager
    config = load_config(args.config)
    settings = get_server_settings(config)
    kb_entries = get_kb_entries(config)

    manager = KBManager()
    print(f"Loading {len(kb_entries)} knowledge base(s)...", flush=True)
    manager.load_all(kb_entries)
    print(f"Ready. {len(manager.contexts)} KB(s) loaded.", flush=True)

    # Override port/host from config if not specified via CLI flags
    port = settings.get("port", args.port)
    host = settings.get("host", args.host)

    if args.transport == "http":
        print(f"Starting HTTP server on {host}:{port}", flush=True)
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()