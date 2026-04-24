# ewan-kb-server 需求备忘

## 背景

当前 ewankb 通过 CLI 子进程调用查询，每次启动都要重新加载图、BM25 索引和 jieba 分词，冷启动开销大。ewan-kb-server 作为独立项目，提供 MCP + HTTP 查询服务，预加载所有配置的 KB，消除重复加载开销。

## 核心需求

1. **MCP 服务**（主要接口）：3 个 tools — `query_graph`、`query_kb`、`list_kbs`，供 Claude Code 调用
2. **HTTP 服务**（调试接口）：绑定 127.0.0.1，4 个 REST 端点 — `/query/graph`、`query/kb`、`/kbs`、`/health`
3. **多 KB 支持**：配置文件指定多个 KB 目录，启动时预加载所有图和 BM25 索引，查询时通过 `kb` 参数指定目标 KB
4. **构建仍用 CLI**：知识库构建用 `ewankb build`，构建完后手动重启 server 重新加载
5. **代码复用**：ewankb 暴露查询相关模块为公开 API（KBContext、query 等），server 作为 ewankb 的依赖调用，避免维护两份代码

## 已完成

### ewankb 侧
- `ewankb/context.py` — KBContext 类（绕过 config_loader 单例，per-KB 实例）
- `ewankb/query.py` — 公开 API 入口，re-export 查询函数
- `ewankb/__init__.py` — 导出 KBContext 和查询函数
- `ewankb/__main__.py` — cmd_query/cmd_query_kb 改用 `from ewankb.query`
- `pyproject.toml` — 加 `fastmcp` optional dep

### ewan-kb-server 侧
- 项目骨架 + 开源标配（pyproject.toml, LICENSE, README.md）
- `ewankb_server/server.py` — FastMCP server + HTTP endpoints
- `ewankb_server/context.py` — KBManager（预加载，缺 graph 时跳过）
- `ewankb_server/config.py` — TOML 配置加载
- `config.example.toml`

### 之前的 bug 修复（ewankb）
- `tokenize` 返回 list 去重保序（避免重复关键词重复计分）
- `cmd_query` max_nodes 未指定 depth 时走 config 默认值
- `tokenization_method` 反映实际路径而非基于输入推测
- 清理 `query_graph_json` 内重复的 tokenize import

## 待优化

- `KBContext.query_graph()` / `query_kb()` 目前仍需临时设置 `EWANKB_DIR` 环境变量 + 清除 config_loader 缓存，不够优雅。理想做法是让 query_engine 和 kb_query 支持直接传入 kb_dir / graph_data / bm25 索引参数，避免依赖全局状态
- `KBContext.preflight()` 方法直接调用 CLI 的 `cmd_preflight` 并捕获 stdout，比较 hack，应该直接实现
- HTTP 模式下 `/query/graph` 等端点返回的是 JSON 包装的文本结果，后续可以考虑直接返回 query_graph_json 的结构化数据
- server 还没有初始化 git repo、没有 CI、没有测试
- `ewankb/__main__.py` 里还有不少地方用 `sys.path.insert(0, EWANKB_ROOT)` + `from tools.xxx`（build 流程那些），后续可以考虑逐步迁移到公开 API