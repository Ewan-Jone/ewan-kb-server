# ewan-kb-server

[ewankb](https://github.com/Ewan-Jone/ewan-kb) 知识库的查询服务，提供 MCP（Model Context Protocol）和 HTTP 接口。

## 为什么需要它

ewankb 的查询目前通过 CLI 子进程调用，每次启动都要重新加载图谱、BM25 索引和 jieba 分词器，冷启动开销大。本服务将它们常驻内存，消除重复加载开销，实现亚秒级查询。

## 架构

- **MCP 服务** — 主要接口，供 Claude Code 等 MCP 客户端调用。提供 `query_graph`、`query_kb` 两个查询工具，以及 `list_kbs` 发现工具。
- **HTTP 服务** — 调试接口，绑定 `127.0.0.1`，REST 端点与 MCP 工具对应，方便 curl / 浏览器测试。
- **多 KB 支持** — 同时服务多个知识库。每个 KB 启动时预加载，查询时通过 `kb` 参数指定目标。
- **构建仍用 CLI** — 知识库构建继续用 `ewankb build`，构建完成后重启 server 即可重新加载。

## 安装

```bash
pip install ewan-kb-server
```

会自动安装 `ewankb` 作为依赖。

## 配置

在 `~/.config/ewankb-server/config.toml` 创建配置文件：

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

或复制示例：

```bash
mkdir -p ~/.config/ewankb-server
cp config.example.toml ~/.config/ewankb-server/config.toml
```

配置文件查找顺序：
1. `--config` CLI 参数
2. `EWANKB_SERVER_CONFIG` 环境变量
3. `~/.config/ewankb-server/config.toml`（默认）

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

# 图谱查询
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
| query_text | string | 必填 | 自然语言查询 |
| kb | string | "default" | 知识库名称 |
| traversal | string | "bfs" | "bfs" 概览模式，"dfs" 路径追踪模式 |
| max_nodes | int | 50 | 最大访问节点数 |

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

## 重建知识库

用 `ewankb build` 更新知识库后，重启服务即可重新加载：

```bash
# 重建 KB（使用 ewankb CLI）
cd /path/to/knowledge-base
ewankb build

# 重启服务
ewankb-server  # 或 kill + 重启后台进程
```

## 许可证

MIT