# Design: 域优先 MCP

## Context

见 proposal「Why」。实现依赖的现状：

- MCP 包 `fd-coding-law-bench-mcp/` 用「wrap `src.*` in place」的方式工作——工具只是薄壳，逻辑在 `src/`。**这意味着一等公民是 `src/` 的模块，不是工具名。**
- 平台内核已经在 `src/bench/`：`workspaces.get_domain/get_active_role/list_domains`、`store.list_knowledge_units/get_knowledge_unit`、`proposals.list_proposals/get/events_for/count_pending`、`next_actions.for_domain`、`unit_checks.checks_for_unit/summarise`、`domain_rubrics.effective_rubrics`。
- 这六组内核函数全部是**纯读**（除 proposals 的 confirm/reject，本 change 不暴露）。
- `rubrics` 表已有 `domain_id`；`prompts`/`eval_runs` 只有 `contract_type` 或什么都没有。
- MCP 的两个部署态（`law-bench-mcp` 全量、`law-bench-mcp-assistant` 带 denylist）共用同一个包与镜像。

## Goals / Non-Goals

**Goals**

- 让「域」成为 MCP 的组织维度，且跨域隔离在数据访问层成立。
- 让法律工具降为 pack，行为零变化。
- 让 `copilot-runtime` 升级时不需要兼容层。

**Non-Goals（design 级）**

- 不改表结构。所有新工具都包既有内核函数。
- 不把 `clauses`（186 条合同条款）并入 `knowledge_units`（5,386 条法条）。
- 不给域面加写工具。

## Decisions

### D1. 工具是薄壳，维度写在**函数签名**里

**决定**：每个域面工具的第一批参数是 `domain: str`，它被直接传给内核的 `domain_key=` 参数。没有「默认域」回退。

**理由**：MCP 包的既有纪律就是「wrap in place」，逻辑不复制。把 `domain` 变成必填参数，跨域隔离就由**数据访问层**保证——`list_knowledge_units(namespace=domain)` 物理上取不到别人的行。

**备选**：在工具内部从某个「当前域」全局变量取。否决——那正是 `search_clauses` 现在的样子（`domain=None` ⇒ 默认 `legal`），一处默认值就把隔离变成了约定。

### D2. 三组标签，域面用平台概念命名

```
tags={"domain"}    domain_list / domain_context / domain_units / domain_unit_checks
                   domain_proposals / domain_proposal_get / domain_publish / domain_assets
tags={"rulers"}    ruler_list（effective_rubrics，已有 domain_id）/ ruler_criteria
tags={"legal"}     ← 17 个法律工具迁入，行为不变
tags={"prompts"|"eval"|"metrics"}   ← 既有组，补 domain 参数
```

**理由**：`tags` 是 FastMCP 的一等结构，`copilot-runtime` 已按它做角色收敛。分组改名 = 白名单自动跟着变，不用第二套记账。

**注意**：`legal` 组名与旧组的 `contracts`/`law`/`clauses` 是**多对一**——旧三个组并成 `legal`。这是 BREAKING，理由见 proposal 的风险段。

### D3. 两类 clause 用工具名前缀分开，不合并数据

```
domain_units(domain, kind="clause")   → knowledge_units 里的法条（5,386）
legal_pack_clause_list(...)           → clauses 表里的合同条款（186，带 {{slot}}）
```

**理由**：它们在语义、用途、数据结构上都不同（见 proposal）。用前缀分开，调用方意图明确；合并会同时毁掉本体归属与装配占位符。

**备选**：统一到 `knowledge_units`。否决——`{{slot}}` 语义不属于知识单元，而装配线（`src/clauses/assemble.py`）依赖 `clauses` 表的结构。

### D4. 域面只读，写面留在页面

**决定**：域面不含 `confirm`/`promote`/`publish`。这些已有页面路由，且带 `hard_stops` 与自提自确认禁令。

**理由**：`proposals.confirm` 有「提交人不得确认自己的提案」这条纪律，`promote_unit` 要求 reviewer 取会话身份。MCP 调用方是机器，没有「会话身份」这个概念——引入它要重设计整套身份模型，不该搭在工具重命名里做。

### D5. `contract-review-agent` 退役

**决定**：移入 `attic/`，删 `Dockerfile.review-backend`，MCP 里的 `agent_runs` HTTP 端点随之摘除。

**理由**（2026-11-24 实测）：未部署（ns 里无 workload）、前端 `package.json` 零 `@copilotkit` 依赖、docstring 自述「务实 MVP，避开 CopilotKit runtime 的复杂度」、无独立 git/CI/spec。它的 `agent_runs` 表与 C7 的 `domain_agent_runs` 是同一概念的两次发明。

**风险**：`attic/` 里的 `.git`（若有）是唯一全量副本——移动前确认工作区干净。

### D6. 零 schema 变更，但 `prompts`/`eval_runs` 的域归属是半成品

**决定**：`prompt_*` / `eval_*` / `compare_*` 增加 `domain` 参数，但**只做过滤，不改表**。`prompts` 没有 `domain_id` 列，所以「按域列 prompt」只能经 `domain_assets` 归属表间接实现；`eval_runs` 连归属都没有，只能按 `rubric_domain_id` 反查。

**理由**：改表会让这个 change 从「重命名 + 加参数」变成「数据迁移」，风险与收益不匹配。这里如实记下缺口，不假装已解决。

**Open issue**：`prompts` 补 `domain_id` 该在哪个 change 做？记在 tasks 挂账里，等有真实需求时再定。

## Risks / Trade-offs

- **[BREAKING 无兼容层]** → 生产唯一调用方是 `copilot-runtime`，同批升级。但若有人直连 MCP 会立刻 404。缓解：在本仓 `IDENTITY.md` 与 MCP README 顶部写一行迁移说明。
- **[`legal` 组名多对一]** → `contracts`/`law`/`clauses` 三组并一组，角色白名单里的旧组名全部失效。缓解：`copilot-runtime` 的白名单改用新组名，并在其自检里断言旧组名不再出现。
- **[合同线虽停但仍有人可能复活]** → `legal_pack_*` 工具保留全部行为，`clauses` 表不动。任何人要复活装配，工具的入口还在，只是不再是「服务器的样子」。
- **[域面工具是薄壳，可能包错]** → 全部直接调 `src/bench/` 的既有函数，不写新逻辑。若某个内核函数本身有缺陷，工具会把缺陷原样暴露（而不是掩盖它）——这是想要的。

## Migration Plan

1. 代码：新增 `tools/domain.py` / `tools/units.py` / `tools/rulers.py`；旧 17 个法律工具移入 `tools/legal_pack/` 子包，函数体不动、只改 `tags` 与注册名。
2. `copilot-runtime/server.mjs`：`READ_GROUPS` / `WRITE_TOOLS` / `LEAD_TOOLS` 按新组名与工具名重写。
3. 出片：`law-bench-mcp` / `law-bench-mcp-assistant` 两个 workload 滚新镜像；`copilot-runtime` 同步滚。
4. 回滚：回退镜像 tag 即回到旧工具面。无 schema 变更，无数据迁移。
5. 灰度：先在 `law-bench-mcp-assistant`（只有浮岛在用）验证，`law-bench-mcp`（外部 agent）后滚。

## Open Questions

- `prompts` / `eval_runs` 的域归属要不要补列？本 change 用间接方式凑合，若真实需求出现再立 change。
- 域面工具要不要暴露给**外部** agent（`law-bench-mcp` 全量态），还是只给浮岛？本 change 先两个部署都开，若发现外部 agent 拿到域面后越权再收。