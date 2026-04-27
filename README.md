# ewan-kb-server

[ewankb](https://github.com/Ewan-Jone/ewan-kb) 知识库的查询服务，提供 MCP 和 HTTP 接口。

## 为什么需要它

ewankb 的查询目前通过 CLI 子进程调用，每次启动都要重新加载图谱、BM25 索引和 jieba 分词器，冷启动开销大。本服务将它们常驻内存，消除重复加载开销，实现亚秒级查询。

## 架构

- **MCP 服务** — 主要接口，供 Claude Code 等 MCP 客户端调用。提供 `query_graph`、`query_kb` 两个查询工具，以及 `list_kbs` 发现工具。
- **HTTP 服务** — 调试接口，绑定 `127.0.0.1`，REST 端点与 MCP 工具对应，方便 curl / 浏览器测试。
- **多 KB 支持** — 同时服务多个知识库。每个 KB 启动时预加载图谱和 BM25 索引，查询时通过 `kb` 参数指定目标。
- **构建仍用 CLI** — 知识库构建继续用 `ewankb build`，构建完成后重启 server 即可重新加载。

## 安装

```bash
pip install ewan-kb-server
```

会自动安装 `ewankb>=0.1.5` 作为依赖。

## 配置

配置分为两个 JSON 文件：**系统配置**（端口、主机等运行参数）和 **KB 注册表**（知识库列表）。

### 系统配置 — `config.json`

在 `~/.config/ewankb-server/config.json` 创建，只包含服务运行参数：

```json
{
  "server": {
    "port": 3000,
    "host": "127.0.0.1"
  }
}
```

此文件可选，未找到时使用默认值（port=3000, host=127.0.0.1）。

查找顺序：
1. `--config` CLI 参数
2. `EWANKB_SERVER_CONFIG` 环境变量
3. `~/.config/ewankb-server/config.json`（默认）

### KB 注册表 — `kbs.json`

在 `~/.config/ewankb-server/kbs.json` 创建，定义要服务的知识库：

```json
{
  "kbs": [
    {
      "name": "default",
      "dir": "/path/to/your/knowledge-base"
    },
    {
      "name": "wms",
      "dir": "/path/to/wms-knowledge-base"
    }
  ]
}
```

每个条目：
- `name` — 查询时传的 `kb` 参数值
- `dir` — KB 目录的绝对路径（由 `ewankb build` 构建的目录）

此文件必需，未找到时服务无法启动。

查找顺序：
1. `--kbs` CLI 参数
2. `EWANKB_SERVER_KBS` 环境变量
3. `~/.config/ewankb-server/kbs.json`（默认）

快速创建配置文件：

```bash
mkdir -p ~/.config/ewankb-server
cp config.example.json ~/.config/ewankb-server/config.json
cp kbs.example.json ~/.config/ewankb-server/kbs.json
# 然后编辑 kbs.json，将 dir 改为你的 KB 目录实际路径
```

## 运行

### MCP 模式（供 Claude Code 使用）

```bash
ewankb-server
```

以 stdio MCP 服务模式运行。在 Claude Code MCP 设置中添加：

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

### HTTP 模式（调试用）

```bash
ewankb-server --transport http --port 3000
```

然后用 curl 测试：

```bash
# 查看可用 KB
curl http://127.0.0.1:3000/kbs

# 图谱查询（返回结构化 JSON）
curl "http://127.0.0.1:3000/query/graph?text=付款额度怎么计算&kb=default"

# 文档检索
curl "http://127.0.0.1:3000/query/kb?text=付款额度&kb=default&domain=收付款管理"

# 健康检查
curl http://127.0.0.1:3000/health
```

## MCP 工具

### query_graph

查询知识图谱中的代码关系和语义连接。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query_text | string | 必填 | 自然语言或代码标识符查询 |
| kb | string | "default" | 知识库名称 |
| traversal | string | "bfs" | "bfs" 概览模式，"dfs" 路径追踪模式 |
| max_nodes | int | 50 | 最大访问节点数 |

返回渲染后的文本摘要。HTTP 端点返回结构化 JSON（含 `matched_start_nodes`、`nodes`、`edges` 等字段）。

### query_kb

基于 BM25 关键词排名检索知识库文档。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query_text | string | 必填 | 搜索关键词或问题 |
| kb | string | "default" | 知识库名称 |
| max_results | int | 8 | 最大返回文档数 |
| domain | string | "" | 可选，按域过滤 |

### list_kbs

列出所有可用知识库及其状态（节点数、边数、文档数）。

## 开发

```bash
cd ewan-kb-server
pip install -e .
ewankb-server --transport http --port 3000
```

### 自测验证

仓库内置了商城项目 E2E 测试，复用 [ewan-kb](https://github.com/Ewan-Jone/ewan-kb) 的商城 fixture 构建知识库，然后验证 server 全部功能：

```bash
# 先构建商城知识库（需要 ANTHROPIC_API_KEY）
cd ../ewan-kb
KEEP_OUTPUT=1 pytest tests/test_mall_e2e.py -v

# 再运行 server 测试
cd ../ewan-kb-server
pytest tests/test_mall_server_e2e.py -v
```

测试覆盖：KBManager 加载 → list_kbs → query_graph（图谱查询）→ query_graph verbose（结构化 JSON）→ query_kb（文档检索）→ KeyError 处理。

测试会自动检测 `/tmp/ewankb_test_mall/` 下已有的知识库，如果之前已构建则直接复用，无需重复调用 LLM。

## 重建知识库

用 `ewankb build` 更新知识库后，重启服务即可重新加载：

```bash
# 重建 KB
cd /path/to/knowledge-base
ewankb build

# 重启服务
ewankb-server
```

## 许可证

MIT