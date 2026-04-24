# ewan-kb-server

Query server for [ewankb](https://github.com/Ewan-Jone/ewan-kb) knowledge bases, providing MCP (Model Context Protocol) and HTTP interfaces.

## Why

ewankb queries currently run as CLI subprocesses, which means every query re-loads the graph, BM25 index, and jieba tokenizer from scratch. This server keeps them in memory, eliminating cold-start overhead and enabling sub-second queries.

## Architecture

- **MCP server** — primary interface for Claude Code and other MCP clients. Two tools: `query_graph` and `query_kb`, plus `list_kbs` for discovery.
- **HTTP server** — debug interface bound to `127.0.0.1`. REST endpoints mirror the MCP tools for easy curl/browser testing.
- **Multi-KB support** — serve multiple knowledge bases simultaneously. Each KB is pre-loaded at startup. Specify which KB to query via the `kb` parameter.
- **Build stays with CLI** — knowledge base construction is still done via `ewankb build`. After rebuilding, restart the server to reload the updated graph and index.

## Install

```bash
pip install ewan-kb-server
```

This also installs `ewankb` as a dependency.

## Configure

Create a config file at `~/.config/ewankb-server/config.toml`:

```toml
[server]
port = 3000
host = "127.0.0.1"

[kbs.default]
name = "default"
dir = "/path/to/your/knowledge-base"

[kbs.wms]
name = "wms"
dir = "/path/to/wms-knowledge-base"
```

Or copy the example:

```bash
mkdir -p ~/.config/ewankb-server
cp config.example.toml ~/.config/ewankb-server/config.toml
```

Config file search order:
1. `--config` CLI argument
2. `EWANKB_SERVER_CONFIG` environment variable
3. `~/.config/ewankb-server/config.toml` (default)

## Run

### MCP mode (for Claude Code)

```bash
ewankb-server
```

Runs as a stdio MCP server. Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "ewankb-server": {
      "command": "ewankb-server",
      "args": []
    }
  }
}
```

### HTTP mode (for debugging)

```bash
ewankb-server --transport http --port 3000
```

Then test with curl:

```bash
# List available KBs
curl http://127.0.0.1:3000/kbs

# Query graph
curl "http://127.0.0.1:3000/query/graph?text=付款额度怎么计算&kb=default"

# Query KB documents
curl "http://127.0.0.1:3000/query/kb?text=付款额度&kb=default&domain=收付款管理"

# Health check
curl http://127.0.0.1:3000/health
```

## MCP Tools

### query_graph

Query the knowledge graph for code relationships and semantic connections.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query_text | string | required | Natural language query |
| kb | string | "default" | Knowledge base name |
| traversal | string | "bfs" | "bfs" for overview, "dfs" for path tracing |
| max_nodes | int | 50 | Maximum nodes to visit |

### query_kb

Search knowledge base documents using BM25 keyword ranking.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| query_text | string | required | Search keywords or question |
| kb | string | "default" | Knowledge base name |
| max_results | int | 8 | Maximum documents to return |
| domain | string | "" | Optional domain filter |

### list_kbs

List all available knowledge bases with status (node count, edge count, document count).

## Development

```bash
cd ewan-kb-server
pip install -e .
ewankb-server --transport http --port 3000
```

## Rebuilding Knowledge Bases

After running `ewankb build` to update a knowledge base, restart the server:

```bash
# Rebuild the KB (using ewankb CLI)
cd /path/to/knowledge-base
ewankb build

# Restart the server to reload
ewankb-server  # or kill + restart if running in background
```

## License

MIT