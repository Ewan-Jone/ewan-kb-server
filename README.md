# ewan-kb-server

[ewankb](https://github.com/Ewan-Jones/ewan-kb) 知识库的 MCP 查询服务。将知识图谱和 BM25 索引常驻内存，消除 CLI 冷启动开销，提供亚秒级查询。

## 安装

```bash
pip install ewan-kb-server
```

## 快速开始

**1. 注册知识库**

在 `~/.ewankb/kb_registry.json` 中注册要服务的知识库（与 ewankb-hub 共用）：

```json
{
  "mall": {
    "dir": "mall-ewan-kb",
    "name": "商城项目业务知识库",
    "description": "订单、支付、商品、会员、库存管理"
  }
}
```

每个条目：key 为查询时的 `kb` 参数值，`dir` 为 `~/.ewankb/` 下的文件夹名（缺省等于 key）。

**2. 启动**

```bash
ewankb-server
```

**3. 配置 MCP 客户端**

在 Claude Code 的 `settings.json` 中添加：

```json
{
  "mcpServers": {
    "ewankb-server": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | `3000` | HTTP 端口 |
| `--host` | `0.0.0.0` | 绑定地址 |
| `--transport` | `sse` | `sse` 或 `http`（streamable HTTP） |
| `--config` | — | 系统配置文件路径（可选，格式见下） |
| `--registry` | `~/.ewankb/kb_registry.json` | KB 注册表路径 |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--log-file` | — | 日志文件路径（不传则仅控制台输出） |
| `--log-format` | `text` | `text` 或 `json` |

`--config` 文件格式（可选）：
```

## MCP 工具

### query_graph

查询知识图谱中的代码关系和语义连接。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query_text | string | 必填 | 自然语言或代码标识符 |
| kb | string | `"default"` | 知识库名称 |
| traversal | string | `"bfs"` | `"bfs"` 概览 / `"dfs"` 路径追踪 |
| max_nodes | int | `50` | 最大访问节点数 |

### query_kb

BM25 关键词检索知识库文档。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query_text | string | 必填 | 搜索关键词 |
| kb | string | `"default"` | 知识库名称 |
| max_results | int | `8` | 最大返回文档数 |
| domain | string | `""` | 按域过滤（可选） |

### search_source

在 `source/` 目录中搜索源代码（大小写不敏感）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query_text | string | 必填 | 搜索文本 |
| kb | string | `"default"` | 知识库名称 |
| glob | string | `"*"` | 文件过滤，如 `*.java` |
| max_results | int | `50` | 最大返回匹配行数 |

返回文件路径、行号、匹配行摘要。

### read_source_file

读取源文件内容（带行号），内置路径穿越防护。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| kb | string | 必填 | 知识库名称 |
| path | string | 必填 | 相对于 `source/` 的文件路径 |
| start_line | int | `1` | 起始行（1-based） |
| end_line | int | `0` | 结束行（0 = 文件末尾） |

### list_kbs

列出所有可用知识库及其状态（节点数、边数、文档数），无参数。

## HTTP 端点

调试用 REST 接口，与 MCP 工具一一对应：

```bash
# 可用知识库
curl http://localhost:3000/kbs

# 图谱查询（返回结构化 JSON）
curl "http://localhost:3000/query/graph?text=付款额度&kb=mall"

# 文档检索
curl "http://localhost:3000/query/kb?text=付款额度&kb=mall&domain=收付款管理"

# 源代码搜索
curl "http://localhost:3000/search/source?text=OrderService&kb=mall&glob=*.java"

# 读取源文件
curl "http://localhost:3000/read/source?kb=mall&path=repos/service/OrderService.java&start_line=1&end_line=50"

# 健康检查
curl http://localhost:3000/health
```

## Docker

```bash
docker run -d \
  -v /path/to/ewankb:/data \
  -p 3000:3000 \
  ewankb-server
```

`/data` 即 `~/.ewankb/` 目录，内含 `kb_registry.json` 和各 KB 子目录。如需额外指定端口等配置，可通过 CLI 参数或挂载 `--config` 文件。

## 日志

每次请求产生两条日志，帮助评估网络带宽开销：

```
[ewankb-server]        search_source | time=14.1ms output=878B     ← 内部处理耗时
[ewankb-server.access] GET /search/source -> 200 | total=14.6ms body=909B  ← 端到端耗时（含网络）
```

`total - time` 的差值 ≈ 网络传输开销。默认仅控制台输出，传 `--log-file` 开启文件日志（滚动策略：10MB × 5 备份）。

## 开发

```bash
cd ewan-kb-server
pip install -e .
ewankb-server
```

### 测试

```bash
# 先构建商城知识库
cd ../ewan-kb
KEEP_OUTPUT=1 pytest tests/test_mall_e2e.py -v

# 运行 server 测试
cd ../ewan-kb-server
pytest tests/test_mall_server_e2e.py -v
```

测试覆盖：KBManager 加载 → list_kbs → query_graph → query_kb → search_source → read_source_file → KeyError 处理。

## 许可证

MIT
