# ewan-kb-server 需求备忘

## 背景

当前 ewankb 通过 CLI 子进程调用查询，每次启动都要重新加载图、BM25 索引和 jieba 分词，冷启动开销大。ewan-kb-server 作为独立项目，提供 MCP + HTTP 查询服务，预加载所有配置的 KB，消除重复加载开销。

## 核心需求

1. **MCP 服务**（主要接口）：5 个 tools — `query_graph`、`query_kb`、`list_kbs`、`search_source`、`read_source_file`
2. **HTTP 服务**（调试接口）：6 个 REST 端点 — `/query/graph`、`/query/kb`、`/kbs`、`/health`、`/search/source`、`/read/source`
3. **多 KB 支持**：默认读取 `~/.ewankb/kb_registry.json`（与 ewankb-hub 共用注册表），启动时预加载所有 KB
4. **构建仍用 CLI**：知识库构建用 `ewankb build`，构建完后手动重启 server 重新加载
5. **代码复用**：ewankb 暴露查询相关模块为公开 API（KBContext、query 等），server 作为 ewankb 的依赖调用
6. **源代码穿透**：`search_source` + `read_source_file` 提供远端文件检索能力，替代 agent 本地 grep/cat

## 已完成

### ewankb 侧
- `ewankb/context.py` — KBContext 类（绕过 config_loader 单例，per-KB 实例）
- `ewankb/query.py` — 公开 API 入口，re-export 查询函数
- `ewankb/__init__.py` — 导出 KBContext 和查询函数
- `ewankb/__main__.py` — cmd_query/cmd_query_kb 改用 `from ewankb.query`
- `pyproject.toml` — 加 `fastmcp` optional dep

### ewan-kb-server 侧
- 项目骨架 + 开源标配（pyproject.toml, LICENSE, README.md）
- `ewankb_server/server.py` — FastMCP server + HTTP endpoints + ASGI access log middleware
- `ewankb_server/context.py` — KBManager（预加载）+ `search_source` / `read_source_file`
- `ewankb_server/config.py` — JSON 配置加载，默认读 `~/.ewankb/kb_registry.json`
- 结构化日志：双路日志（内部耗时 + 端到端耗时），支持 text/json 格式，滚动持久化

## 待优化

- `KBContext.query_graph()` / `query_kb()` 目前仍需临时设置 `EWANKB_DIR` 环境变量 + 清除 config_loader 缓存
- Docker 镜像发布到 GitHub Container Registry
- CI / 自动化测试