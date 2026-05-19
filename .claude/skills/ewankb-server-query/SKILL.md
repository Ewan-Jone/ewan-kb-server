---
name: ewankb-server-query
description: 通过 MCP 远端查询 ewankb 知识库。默认图谱查询，也可指定 kb 或 deep 双路对比模式。查询结果自动穿透到源代码层，验证规格与实现的一致性。
trigger: /ewankb-server-query
---

# /ewankb-server-query

通过 ewan-kb-server MCP 服务远端查询知识库，无需本地安装 ewankb 或拉取知识库代码。

## 用法

```
/ewankb-server-query <问题>                          # 图谱查询（默认）
/ewankb-server-query graph <kb> <问题>               # 图谱查询（指定 KB）
/ewankb-server-query kb <kb> <问题>                  # 文档检索
/ewankb-server-query deep <kb> <问题>                # 双路对比查询
/ewankb-server-query list                            # 列出所有可用 KB
```

## 执行步骤

### 0. 检查 MCP 配置

在执行任何查询之前，先尝试调用 `list_kbs` MCP 工具确认 ewan-kb-server 已连接。

**如果工具不可用（No such tool available）**，输出以下引导信息并停止：

```
未检测到 ewan-kb-server MCP 服务。请按以下步骤配置：

1. 打开 ~/.claude.json（注意：不是 settings.json，settings.json 不支持 mcpServers）

2. 添加或修改 "mcpServers" 字段：
   "mcpServers": {
     "ewankb-server": {
       "type": "sse",
       "url": "http://<server-host>:22902/sse"
     }
   }
   或使用 Streamable HTTP：                                                      
    "mcpServers": {                                                               
		"ewankb-server": {                                                          
		"type": "streamable-http",                                                
		"url": "http://<server-host>:22902/mcp"                               
	 }                                                                           
	} 

3. 保存后重启 Claude Code 即可生效

如果没有搭建过 ewan-kb-server 服务，参考：https://github.com/Ewan-Jones/ewan-kb-server
```

**如果工具可用**，继续执行后续步骤。

### 0.5. 确定目标 KB

用户可以通过以下方式指定 KB：

1. **子命令中显式指定**：`/ewankb-server-query graph mall "付款额度"`
2. **对话中说明**：如"用 mall 这个库查一下付款额度"

如果用户没有指定 KB，调用 `list_kbs` MCP 工具获取可用 KB 列表，然后：
- 如果只有 1 个 KB → 自动使用它
- 如果有多个 KB → 展示列表让用户选择，展示格式参考`/ewankb-server-query list`的展示


### 1. 判断查询模式

根据用户输入确定模式：
- `/ewankb-server-query <问题>`（无子命令，无 KB）→ 先确定 KB（步骤 0.5），再**图谱模式**（步骤 2A）
- `/ewankb-server-query graph <kb> <问题>` → **图谱模式**（步骤 2A）
- `/ewankb-server-query kb <kb> <问题>` → **kb 模式**（步骤 2B）
- `/ewankb-server-query deep <kb> <问题>` → **双路对比模式**（步骤 2C）
- `/ewankb-server-query list` → 调用 `list_kbs` MCP 工具，**严格按以下模板**展示所有 KB：

```
检测到以下可用知识库：

| 库名（英文） | 库名（中文） | 描述 | 文档数 |
|------|--------|------|--------|
| ... | ... | ... | ... |

请指定要查询的知识库，如：/ewankb-server-query graph <库名> "问题"
```

**list 展示规则**：
- 只展示 4 列：库名（英文）、库名（中文）、描述、文档数，**禁止**展示节点数、边数、目录路径等其他字段
- 库名（中文）根据领域常识推断，若无法推断则填 `—`
- 描述取 `list_kbs` 返回的 description 字段，若无则填 `—`
- 文档数取 `list_kbs` 返回的 docs 字段
- 末尾统一附使用提示

### 2A. Graph 模式（仅图谱）

调用 `query_graph` MCP 工具：

```
query_graph(query_text="用户问题", kb="目标kb", traversal="bfs", max_nodes=50)
```

**解读结果**：

1. **结果为空或节点极少**：
   → 告知用户图中未找到匹配节点，建议：
   - 尝试更短的关键词（如"付款额度" → "付款"）
   - 尝试用英文术语（如"overdraft"、"payment"）
   - 建议用 `/ewankb-server-query kb <kb> "同一问题"` 切换到文档检索

2. **结果非空**：
   → 基于节点和边关系用自然语言合成回答：
   - 从匹配节点出发，描述直接关联的概念
   - 引用 source_file、source_location、relation 作为证据
   - 不要编造图中没有的关系
   - 如果图的深度不足以覆盖问题范围，如实说明

回答末尾附建议："想看原文？试 `/ewankb-server-query kb <kb> \"同一问题\"`"

### 2B. KB 模式（仅文档）

调用 `query_kb` MCP 工具：

```
query_kb(query_text="用户问题", kb="目标kb", max_results=8, domain="")
```

**关联代码为空时的处理**：
如果返回的文档中"关联代码"章节为空，自动触发代码穿透（步骤 3）来查找对应的源代码文件。

回答末尾附建议："想看关联？试 `/ewankb-server-query graph <kb> \"同一问题\"`"

### 2C. 双路对比模式（deep）

用 Agent 工具**并行**启动两个 subagent（同一条消息）：

**Subagent A（graph）**：
> 调用 `query_graph` MCP 工具（query_text="{问题}", kb="{kb}", traversal="bfs"），分析结果（涉及哪些节点、边、域）。从结果中提取技术术语（字段名、类名、API路径等），用于代码穿透。

**Subagent B（kb）**：
> 调用 `query_kb` MCP 工具（query_text="{问题}", kb="{kb}"），分析结果。从文档内容中提取技术术语（字段名、类名、API路径、表名等），用于代码穿透。如果文档的"关联代码"为空，标记需要代码穿透。

**对比 + 歧义处理**：
- 两路结果一致 → 合并汇总回答
- 存在歧义 → 向 subagent 追问具体歧义点，追问结果继续对比，还有歧义就再追问，直到一致（最多 5 轮）

**代码穿透**：Subagent A/B 完成后，汇总两路提取的技术术语，执行代码穿透（步骤 3），重点比对**规格描述 vs 实际实现**的差异。

最终回答格式：
```
## 回答
[综合回答]
## 信息来源
- 图谱：[关键发现]
- 文档：[关键发现]
- 代码：[关键发现]（如有代码穿透结果）
## 代码验证（如有差异）
- [规格 vs 实现] {差异描述}
- 证据：{源文件路径}:{行号}
## 差异说明（如有）
```

### 3. 代码穿透（search_source + read_source_file）

无论哪种查询模式，在获得知识库/图谱结果后，执行代码穿透来验证规格与实现的一致性。

**执行前提**：
- 查询结果中包含可映射到代码的技术术语 → 执行代码穿透
- 用户问题纯业务描述，不含任何可映射到代码的实体（如"什么是合同管理"） → 跳过
- 知识库文档的"关联代码"已完整覆盖问题范围 → 跳过

**步骤 1：提取技术术语**

从知识库/图谱查询结果中提取可用于搜索源代码的技术关键词：

| 来源类型 | 可提取的术语 | 示例 |
|----------|-------------|------|
| 接口文档 | API路径、请求参数名、响应字段名 | `/contract/info/page`, `contractCode` |
| 需求文档 | 表名、字段代码、业务实体编码 | `contract_archive_info` |
| 图谱节点 | source_file 中的路径片段、类名 | `ContractInfoRest` |
| 文档正文 | 任何明确提及的技术标识 | `config.js`, `advanceUser` |

同时从中文术语推断可能的技术命名：
- 业务实体 → 可能的模块/目录名（如"合同管理" → `contractManage`、`ContractInfo`）
- 业务动作 → 可能的 API/方法名（如"查询合同" → `searchContract`、`contractPage`）

**步骤 2：搜索源代码**

调用 `search_source` MCP 工具搜索源代码：

```
search_source(query_text="技术术语", kb="目标kb", glob="*.java", max_results=50)
```

根据目标语言调整 glob 参数：
- Java → `*.java`
- Vue/前端 → `*.vue` 或 `*.ts` 或 `*.js`
- Python → `*.py`
- 不限 → `*`（默认）

如果搜索结果中包含关键文件，用 `read_source_file` 深入阅读：

```
read_source_file(kb="目标kb", path="repos/.../KeyFile.java", start_line=1, end_line=0)
```

**步骤 3：补充回答**

将源代码搜索结果作为补充信息纳入回答：

- 如果知识库文档的"关联代码"为空，用代码穿透结果填充，引用具体源文件路径和行号
- 如果知识库文档与源代码存在差异，**必须标注差异**，并注明代码证据的文件路径和行号
- 回答中增加"代码验证"章节
- 如果代码穿透未找到相关代码，如实说明，不编造

### 4. 回答约束

**严格模式约束**：用户选择了哪种查询模式，就只用该模式的结果回答。禁止因为认为结果不理想而自动切换或追加其他模式的查询。

**代码穿透是所有模式的标配**：代码穿透不是独立查询模式，而是每种模式回答后的验证步骤。即使严格模式约束下，代码穿透仍然执行。

- 回答信息来源包括三层：知识库文档、知识图谱、源代码（通过代码穿透获得）
- 只用知识库和源代码中的实际信息回答，不编造
- 引用具体文件路径、类名、文档标题
- **结论优先**：先给出结论，再展开推断过程和细节
- **面向非技术人员**：关于代码的描述不要占大篇幅，除非提问者专门问代码细节
- **保持原问题**：回答标题和检索关键词必须使用用户的原始提问，禁止在检索前将业务语言改写为技术术语（如把"出库直发单"改写为"CZF"）。改写会缩小搜索范围，导致漏掉上游源头逻辑。如果检索结果中发现了对应的技术编码，在回答正文中补充说明即可，但不能用它替换原问题。
- **溯源到底**：当问题是"X 是怎么解析/产生/来的"这类溯源型提问时，找到一层解析逻辑后不能停，必须继续追问"这个输入值又是谁设置的"，直到追溯到系统边界（上游推送的原始字段）。只描述中间某一层映射机制不算完整回答。
- **规格与实现必须对齐**：当知识库文档描述了业务规则或功能定义，而源代码的实际实现与文档存在差异时，必须标注差异并在"代码验证"章节中说明。