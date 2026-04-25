"""
E2E test for ewan-kb-server using the ewankb mall fixture.

Builds a KB from the mall fixture, then tests KBManager loading
and MCP tool functions (query_graph, query_kb, list_kbs).

Usage: pytest tests/test_mall_server_e2e.py -v

Prerequisites:
  - ewankb installed (pip install -e ../ewan-kb)
  - ewan-kb-server installed (pip install -e .)
  - A pre-built KB at /tmp/ewankb_test_mall (run ewan-kb E2E test first,
    or this script will build one using the fixture)
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Resolve project roots
EWANKB_ROOT = Path(__file__).resolve().parent.parent.parent / "ewan-kb"
SERVER_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = EWANKB_ROOT / "tests" / "fixtures" / "商城项目"
KB_OUTPUT_DIR = Path("/tmp/ewankb_test_mall")


def _reset_config_caches():
    """Reset config_loader singleton caches so EWANKB_DIR is re-read."""
    import tools.config_loader as cfg
    cfg._global_cfg = None
    cfg._project_cfg = None
    cfg._llm_cfg = None


def _build_kb_if_needed():
    """Build a KB from the mall fixture if one doesn't already exist.

    Returns True if a new KB was built, False if using an existing one.
    """
    if KB_OUTPUT_DIR.exists():
        graph_file = KB_OUTPUT_DIR / "graph" / "graph.json"
        bm25_file = KB_OUTPUT_DIR / "knowledgeBase" / "_state" / "bm25_index.pkl"
        if graph_file.exists() and bm25_file.exists():
            print(f"Using existing KB at {KB_OUTPUT_DIR}", flush=True)
            return False

    print(f"Building KB at {KB_OUTPUT_DIR}...", flush=True)

    # Clean and create directory structure
    if KB_OUTPUT_DIR.exists():
        shutil.rmtree(KB_OUTPUT_DIR)
    KB_OUTPUT_DIR.mkdir(parents=True)

    (KB_OUTPUT_DIR / "source").mkdir()
    (KB_OUTPUT_DIR / "source" / "repos").mkdir()
    (KB_OUTPUT_DIR / "source" / "docs").mkdir()
    (KB_OUTPUT_DIR / "domains").mkdir()
    (KB_OUTPUT_DIR / "domains" / "_meta").mkdir()
    (KB_OUTPUT_DIR / "knowledgeBase").mkdir()
    (KB_OUTPUT_DIR / "graph").mkdir()
    (KB_OUTPUT_DIR / "graph" / ".cache").mkdir()

    # Copy fixture source
    shutil.copytree(
        FIXTURE_DIR / "source" / "repos",
        KB_OUTPUT_DIR / "source" / "repos",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        FIXTURE_DIR / "source" / "docs",
        KB_OUTPUT_DIR / "source" / "docs",
        dirs_exist_ok=True,
    )

    # Copy template knowledgeBase
    template_dir = EWANKB_ROOT / "ewankb" / "templates" / "knowledgeBase"
    shutil.copytree(template_dir, KB_OUTPUT_DIR / "knowledgeBase", dirs_exist_ok=True)

    # Set EWANKB_DIR and create configs
    os.environ["EWANKB_DIR"] = str(KB_OUTPUT_DIR)
    _reset_config_caches()

    # Add ewankb root to sys.path so tools/ is importable
    sys.path.insert(0, str(EWANKB_ROOT))

    from tools.config_loader import create_project_config, get_global_config

    gcfg = get_global_config()
    create_project_config(KB_OUTPUT_DIR, "商城项目业务知识库")

    # Resolve API key and LLM config from environment or Claude Code settings
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    model = os.environ.get("ANTHROPIC_MODEL", "")

    if not api_key:
        cc_settings = Path.home() / ".claude" / "settings.json"
        if cc_settings.exists():
            with open(cc_settings) as f:
                env_data = json.load(f).get("env", {})
            api_key = env_data.get("ANTHROPIC_AUTH_TOKEN", "")
            base_url = env_data.get("ANTHROPIC_BASE_URL", base_url)
            model = env_data.get("ANTHROPIC_DEFAULT_SONNET_MODEL", model or "claude-haiku-4-5-20251001")

    if not api_key:
        cfg_dir = Path.home() / ".config" / "ewankb"
        cfg_file = cfg_dir / "ewankb.toml"
        if cfg_file.exists():
            import tomllib
            with open(cfg_file, "rb") as f:
                data = tomllib.load(f)
            api_key = data.get("api", {}).get("api_key", "")

    if not api_key:
        raise RuntimeError(
            "No API key found. Set ANTHROPIC_API_KEY or configure ~/.claude/settings.json"
        )

    llm_cfg = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "api_protocol": "anthropic",
    }
    with open(KB_OUTPUT_DIR / "llm_config.json", "w", encoding="utf-8") as f:
        json.dump(llm_cfg, f, indent=2, ensure_ascii=False)

    (KB_OUTPUT_DIR / ".gitignore").write_text(
        "graph/.cache/\nknowledgeBase/_state/\n.env\nllm_config.json\n"
    )

    # Run ewankb build pipeline
    os.environ["EWANKB_DIR"] = str(KB_OUTPUT_DIR)
    _reset_config_caches()
    os.chdir(KB_OUTPUT_DIR)

    from tools.discover.discover_domains import discover
    discover(KB_OUTPUT_DIR, use_ai=True)

    _reset_config_caches()
    from ewankb.__main__ import cmd_knowledgebase
    cmd_knowledgebase(skip_discover=True)

    _reset_config_caches()
    from tools.build_graph.graph_builder import build_graph
    build_graph(
        source_dir=KB_OUTPUT_DIR / "source",
        domains_dir=KB_OUTPUT_DIR / "domains",
        graph_dir=KB_OUTPUT_DIR / "graph",
    )

    print(f"KB built at {KB_OUTPUT_DIR}", flush=True)
    return True


def test_server_with_mall_kb():
    """Test ewan-kb-server with the mall fixture KB."""
    _build_kb_if_needed()

    # ── Test KBManager ──
    from ewankb_server.context import KBManager
    import ewankb_server.server as server_mod

    manager = KBManager()
    kb_entries = [{"name": "mall", "dir": str(KB_OUTPUT_DIR)}]
    manager.load_all(kb_entries)

    # Set global manager so MCP tool functions can access it
    server_mod.manager = manager

    assert "mall" in manager.contexts, "KB 'mall' not loaded"

    ctx = manager.get("mall")
    info = ctx.info()
    assert info["graph_loaded"] is True, "Graph not loaded"
    assert info["graph_nodes"] > 0, f"Graph has 0 nodes"
    assert info["bm25_loaded"] is True, "BM25 not loaded"
    assert info["bm25_docs"] > 0, f"BM25 has 0 docs"
    print(f"KBManager: {info['graph_nodes']} nodes, {info['graph_edges']} edges, {info['bm25_docs']} docs", flush=True)

    # ── Test list_kbs ──
    from ewankb_server.server import list_kbs

    result = list_kbs()
    assert len(result) > 0, "list_kbs returned empty"
    assert "nodes" in result, "list_kbs output missing 'nodes'"
    print(f"list_kbs: {result}", flush=True)

    # ── Test query_graph ──
    from ewankb_server.server import query_graph

    # Graph has AST code nodes (English identifiers), so use English query
    graph_result = query_graph("OrderService", kb="mall", traversal="bfs", max_nodes=50)
    assert len(graph_result) > 0, "query_graph returned empty result"
    assert len(graph_result) > 100 or "Order" in graph_result or "Service" in graph_result, \
        f"query_graph result doesn't contain relevant content: {graph_result[:200]}"
    print(f"query_graph 'OrderService': {len(graph_result)} chars", flush=True)

    # ── Test query_graph with verbose JSON ──
    ctx2 = manager.get("mall")
    json_result = ctx2.query_graph("PaymentService", traversal="bfs", max_nodes=30, verbose=True)
    assert "matched_start_nodes" in json_result, "verbose query missing matched_start_nodes"
    assert len(json_result.get("matched_start_nodes", [])) > 0 or len(json_result.get("nodes", [])) > 0, \
        "No matching nodes found for 'PaymentService'"
    print(f"query_graph verbose: {len(json_result['matched_start_nodes'])} matched, {len(json_result['nodes'])} visited", flush=True)

    # ── Test query_kb ──
    from ewankb_server.server import query_kb

    kb_result = query_kb("库存校验规则", kb="mall", max_results=5)
    assert len(kb_result) > 50, f"query_kb returned too short result ({len(kb_result)} chars)"
    assert "库存" in kb_result or "规则" in kb_result, \
        f"query_kb result doesn't contain relevant keywords"
    print(f"query_kb '库存校验规则': {len(kb_result)} chars", flush=True)

    # ── Test KeyError for unknown KB ──
    try:
        manager.get("nonexistent")
        assert False, "Should have raised KeyError for nonexistent KB"
    except KeyError as e:
        assert "nonexistent" in str(e)
        print(f"KeyError for unknown KB: OK", flush=True)

    # ── Cleanup only if we built the KB ourselves ──
    # Keep the KB for potential re-use / manual inspection
    # Uncomment below to auto-cleanup:
    # shutil.rmtree(KB_OUTPUT_DIR)

    print("E2E server test passed.", flush=True)