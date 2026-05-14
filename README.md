# ewan-kb-server

[ewankb](https://github.com/Ewan-Jones/ewan-kb) 知识库的 MCP 查询服务。将知识图谱和 BM25 索引常驻内存，消除每次 CLI 调用的冷启动开销。

## 安装

Python 3.10+，无需其他系统依赖。

```bash
pip install ewan-kb-server
```

## 快速开始

### 1. 注册知识库

在 `~/.ewankb/kb_registry.json` 中注册要服务的知识库：

```json
{
  "mall": {
    "dir": "mall-ewan-kb",
    "name": "商城项目业务知识库",
    "description": "订单、支付、商品、会员、库存管理"
  }
}
```

- key（如 `mall`）：查询时 `kb` 参数的值
- `dir`：`~/.ewankb/` 下的文件夹名，缺省等于 key
- `name` / `description`：可选，用于展示

### 2. 启动服务

```bash
# 前台运行（开发调试用，Ctrl+C 停止）
ewankb-server

# 后台运行（生产环境用）
ewankb-server start
```

默认启动 SSE 和 Streamable HTTP 双协议，监听 `0.0.0.0:22902`。

- SSE 端点：`http://localhost:22902/sse`
- Streamable HTTP 端点：`http://localhost:22902/mcp`

使用 `--transport sse` 或 `--transport http` 可切换到单协议。

### 3. 停止与重启

```bash
ewankb-server stop       # 停止后台服务
ewankb-server restart    # 重启后台服务（保留原有参数）
```

`stop` 通过 `~/.ewankb/ewankb-server.pid` 定位进程，先发 SIGTERM 优雅退出，超时 5 秒后 SIGKILL 强杀。

### 4. 配置 Claude Code

**方法一：命令行添加（推荐）**

```bash
claude mcp add-json ewankb-server '{"type":"http","url":"http://localhost:22902/sse"}' --scope user
```

**方法二：编辑配置文件**

全局配置写入 `~/.claude.json`，项目级配置写入 `.mcp.json`：

```json
{
  "mcpServers": {
    "ewankb-server": {
      "type": "http",
      "url": "http://localhost:22902/sse"
    }
  }
}
```

服务端默认开启双协议，SSE 用 `/sse`，Streamable HTTP 用 `/mcp`。根据客户端 `--transport` 模式选择对应 URL。配置保存后需重启 Claude Code 生效。

## CLI 参数

### 子命令

| 命令 | 说明 |
|------|------| 
| *(无)* | 前台运行（默认） |
| `start` | 后台启动 |
| `stop` | 停止后台进程 |
| `restart` | 重启后台进程 |
| `refresh` | 手动触发全量重载（注册表 + 图谱/BM25 索引） |

`start`、`restart` 接受以下全部参数；`stop`、`refresh` 不需要参数，通过 PID 文件定位进程。

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | `22902` | HTTP 端口 |
| `--host` | `0.0.0.0` | 绑定地址 |
| `--transport` | `both` | `sse` / `http` / `both` |
| `--config` | — | 配置文件路径，格式见下 |
| `--registry` | `~/.ewankb/kb_registry.json` | KB 注册表路径 |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--log-file` | `.ewan-kb-server.log` | 日志文件路径 |
| `--log-format` | `text` | `text` 或 `json` |
| `--reload-interval` | `60` | 注册表自动重载间隔（秒），设为 0 禁用 |
| `--index-reload-interval` | `600` | 图谱/BM25 索引自动重载间隔（秒），设为 0 禁用 |

`--config` 文件格式（所有字段可选，未指定则使用上表默认值）：

```json
{
  "server": {
    "port": 22902,
    "host": "0.0.0.0"
  }
}
```

## MCP 工具

### query_graph

查询知识图谱中的代码关系和语义连接。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query_text` | string | 必填 | 查询文本 |
| `kb` | string | `"default"` | 知识库名称 |
| `traversal` | string | `"bfs"` | `"bfs"` 概览 / `"dfs"` 路径追踪 |
| `max_nodes` | int | `50` | 最大访问节点数 |

### query_kb

BM25 关键词检索知识库文档。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query_text` | string | 必填 | 搜索关键词 |
| `kb` | string | `"default"` | 知识库名称 |
| `max_results` | int | `8` | 最大返回文档数 |
| `domain` | string | `""` | 按域过滤，可选 |

### search_source

在 `source/` 目录中搜索源代码（大小写不敏感）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query_text` | string | 必填 | 搜索文本 |
| `kb` | string | `"default"` | 知识库名称 |
| `glob` | string | `"*"` | 文件名过滤，如 `*.java`、`*.vue` |
| `max_results` | int | `50` | 最大返回匹配行数 |

返回文件路径、行号和匹配行摘要。

### read_source_file

读取源文件内容，带行号标注。内置路径校验，拒绝越权访问。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `kb` | string | 必填 | 知识库名称 |
| `path` | string | 必填 | 相对于 `source/` 的文件路径 |
| `start_line` | int | `1` | 起始行号 |
| `end_line` | int | `0` | 结束行号，`0` 表示读到文件末尾 |

### list_kbs

列出所有可用知识库及其节点数、边数、文档数。无参数。

## HTTP 端点

以下 REST 接口用于调试，与 MCP 工具一一对应：

```bash
# 可用知识库
curl http://localhost:22902/kbs

# 图谱查询
curl "http://localhost:22902/query/graph?text=付款额度&kb=mall"

# 文档检索
curl "http://localhost:22902/query/kb?text=付款额度&kb=mall"

# 源代码搜索
curl "http://localhost:22902/search/source?text=OrderService&kb=mall&glob=*.java"

# 读取源文件
curl "http://localhost:22902/read/source?kb=mall&path=repos/service/OrderService.java&start_line=1&end_line=50"

# 健康检查
curl http://localhost:22902/health
```

## Claude Code 集成

项目自带 `/ewankb-server-query` skill，让 Claude Code 通过 MCP 直接查询远端知识库，无需在本地安装 ewankb 或拉取知识库代码。

### 安装 Skill

将 `.claude/skills/ewankb-server-query/` 复制到 `~/.claude/skills/ewankb-server-query/`：

```bash
cp -r .claude/skills/ewankb-server-query ~/.claude/skills/
```

### 使用

```
/ewankb-server-query <问题>                          # 图谱查询（默认）
/ewankb-server-query graph <kb> <问题>               # 图谱查询（指定 KB）
/ewankb-server-query kb <kb> <问题>                  # 文档检索
/ewankb-server-query deep <kb> <问题>                # 双路对比（图谱 + 文档 + 代码穿透）
/ewankb-server-query list                            # 列出所有可用 KB
```

Skill 会自动检测 MCP 配置是否正确，未配置时给出引导。查询结束后自动执行代码穿透，通过 `search_source` + `read_source_file` 验证规格与实现的一致性。

## Docker

```bash
docker run -d \
  -v /path/to/ewankb:/data \
  -p 22902:22902 \
  ewankb-server
```

`/data` 对应宿主机的 `~/.ewankb/` 目录，内含 `kb_registry.json` 和各 KB 子目录。如需调整端口或其他参数，在镜像名后追加 CLI 参数即可：

```bash
docker run -d -v /path/to/ewankb:/data -p 8080:8080 ewankb-server --port 8080
```

## 日志

每次请求产生两条日志：

```
[ewankb-server]        search_source | time=14.1ms output=878B
[ewankb-server.access] GET /search/source -> 200 | total=14.6ms body=909B
```

- `ewankb-server`：服务端内部处理耗时（不含网络传输）
- `ewankb-server.access`：端到端耗时（含网络传输 + 响应体大小）

两者的差值可近似评估网络传输开销。默认仅输出到控制台，通过 `--log-file` 可开启文件日志（滚动策略：单文件 10MB，保留 5 个备份）。

## 开发

```bash
git clone https://github.com/Ewan-Jones/ewan-kb-server.git
cd ewan-kb-server
pip install -e .
```

### 测试

需要同级的 `ewan-kb` 项目，先用其内置的商城 fixture 构建知识库，再运行 server 的 E2E 测试：

```bash
# 构建商城知识库（需要 ANTHROPIC_API_KEY）
cd ../ewan-kb
KEEP_OUTPUT=1 pytest tests/test_mall_e2e.py -v

# 运行 server 测试
cd ../ewan-kb-server
pytest tests/test_mall_server_e2e.py -v
```

测试覆盖：KBManager 加载 → list_kbs → query_graph → query_kb → search_source → read_source_file → KeyError 处理。

## 许可证

MIT