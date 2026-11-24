# Design: 副驾驶收编为域内助手

## Context

见 proposal「Why」。这里只列实现必须依赖的现状：

- 工作台助手由四块拼成，都在产：`src/web/routes/copilot.py`（同源代理，唯一公共路径）、`assistant-ui/`（CopilotKit 浮岛，构建成 IIFE 由 `base.html` 挂载）、`copilot-runtime/`（Node + CopilotKit runtime，ClusterIP:3111）、`law-bench-mcp-assistant`（MCP 实例，`MCP_TOOL_DENYLIST` 已禁四个删除工具）。
- 当前的门在 `src/web/templating.py:126`：`bool(COPILOT_RUNTIME_URL) and _has_scope(user, "admin")`。
- 域模型已经在产：`domains` / `domain_members`、`workspaces.ROLE_RANK = {"annotator": 0, "expert": 1, "lead": 2}`、`src/web/domain_context.py::console_context` 负责解析「当前域 + 我的角色 + 能力位」。
- `src/bench/next_actions.py`（域下一动作投影）与 `src/bench/unit_checks.py`（机器核对结论）都是纯读、无写出，可直接被助手复用。
- MCP 工具已按概念分组（`tags={"clauses"|"contracts"|"eval"|"law"|"metrics"|"pipeline"|"prompts"|"rubrics"|"search"|"tags"}`），分组即角色收敛的天然单位。
- runtime 侧 `server.mjs` 已有一层 `TOOL_DENYLIST` 过滤，是这次扩展的落点。

## Goals / Non-Goals

**Goals**

- 把门从「平台 admin」换成「本域成员」，且解析不到域时 fail closed。
- 让模型看得到域身份、角色、该域下一动作、机器核对结论。
- 工具面按域角色收敛，且收敛发生在**能读到角色**的那一层。

**Non-Goals（design 级）**

- 不给助手任何写面（确认提案、升格、发布仍走页面）。写面要单独立 change，因为它需要与 `hard_stops` / `proposals` 的会话身份纪律对齐。
- 不做多域会话（一次一个域）。
- 不重构 `contract-review-agent` 的 Next.js 前端。

## Decisions

### D1. 域与角色由代理判定，运行时只消费

**决定**：`/copilotkit` 代理解析当前域与角色，作为请求头/字段传给 runtime；runtime 按角色过滤工具面。判定不在 runtime 里做。

**理由**：代理是唯一公共路径，也是唯一能读工作台会话（Logto cookie → 用户 → 域成员）的地方。让 runtime 自己解析等于把同一套判定复制两份。

**备选**：runtime 直连数据库查成员。否决——runtime 是 Node，届时要么复制身份解析，要么给它数据库凭据（扩大攻击面）。

### D2. 工具面按 MCP 分组映射到角色，而不是逐工具白名单

**决定**：

```
annotator (0)  clauses.search  contracts.read   eval.read   law   metrics        (只读)
expert   (1)  + prompts.*  rubrics.*  clauses.write  eval.write  pipeline  tags   (可写)
lead     (2)  + 发布/升格相关                                                    (负责)
所有角色       删除类一律不可用
```

按已有的 `tags` 分组收敛，不满逐工具列表。

**理由**：54 个工具逐条列白名单会立刻腐烂（加一个工具就要改三处角色表）。分组是 MCP 已经维护的一等结构，工具增删落在组内自动生效。

**备选**：逐工具 allowlist。否决：维护成本随工具数线性增长，且与 `law-bench-mcp-assistant` 的 denylist 形成第二套记账。

**注意（已按 0.1 取证修正）**：分组里区分「读/写」必须用工具级信息，`tags` 只表达概念。
**命名后缀判不出来**——取证实测：`compare_run`、`contract_generate*`、
`self_heal_pipeline_run`、`auto_reject_pipeline_run`、`tag_iteration_apply` 全部**落库**，
但它们经 `anyio.to_thread` 间接调用，源码扫描与命名后缀都会判成只读；而 `pipeline`
组内 `pipeline_list`/`pipeline_get` 只读、另两个是重写操作——**同组读写混杂，不能整组授予**。

因此角色映射 = 「组」+「组内例外清单」，例外清单以 0.1 的副作用表为准（见 tasks 0.1）。
实现时不得以工具名为唯一依据。

### D3. 域上下文以「读面注入」而非「新工具」给模型

**决定**：runtime 在 system prompt 里注入域片段（域名、角色、下一动作、可升格条目数、机器核对摘要），并提供两个**只读**的域查询能力（下一动作、单位核对）。不加新的写工具。

**理由**：模型回答问题需要的是「这几条事实」，不是「一个能查更多东西的工具」。注入降低工具调用轮数，也避免模型自己去翻库。

**备选**：新增 `domain_next_actions` / `unit_checks` 两个 MCP 工具。否决于本轮——那要改 MCP 包并滚 `law-bench-mcp-assistant`，而这两个数据代理侧本来就有。

### D4. 无可访问域 = 助手不可用，不退化成全局助手

**决定**：解析不到域时 `assistant_enabled=False`，代理对任何 `/copilotkit` 请求返回可分辨的拒绝（`403 no_domain_context`）。

**理由**：一个「没有域」的助手会退回到今天这个 admin 全局问答形态——那正是要收编掉的东西。退回去等于这个 change 白做。

### D5. `copilotkit-frontend` 从本仓移除

**决定**：删 `openspec/specs/copilotkit-frontend/`，并改正 `openspec/changes/archive/2026-11-08-polish-bench-workbench/design.md` 里那句「岛内交互有独立 `copilotkit-frontend` spec 管辖」。

**理由**：那份规格描述的是 Next.js 整站应用（`/api/copilotkit` 代理、`CopilotSidebar`、三处 `useHumanInTheLoop`），属 `contract-review-agent`。留着它，任何人都可能据此认为工作台助手是 Next.js 应用。

**风险**：如果 `contract-review-agent` 仍在维护，它的规格需要落在那个仓（或跨仓引用）。本 design 记这条为 open question，不影响本 change 的落地。

### D6. 副驾驶不迁谦面（agent 归口判断）

**决定**：助手保持为平台内功能，不发布为谦面市场条目。**但**知验台的七岗（`pack.yaml` 的
`roles:` 段）应当有谦面市场的目录条目。

**理由**：谦面的 agent 条（`agents[]`）只有 `id/name/description/persona`，工具面、节奏、
权限边界在 `fleet.members[]` 里，且由 cron 驱动、可被市场安装。助手是「人点一下问一句」
的会话界面，零写入、不可安装、身份取人的域角色——两者生命周期与契约厚度都不同，塞进
市场只会多一个装不上跑不起来的条目。

**但岗位目录是另一回事**：`roles:` 段目前**只有 law-bench 自己在读**（`src/bench/packs.py`
→ `agent_team.declared_roles`），谦面市场完全没有这些岗位的条目，于是「知验台有七个岗位」
这件事没有任何对外可见的地方。`facet-ops-mcp` 的 registry 面本来就有 AgentCard 操作，
只差有人把岗位灌进去。

**落点**：谦面 = agent 的目录与发布面；运行与契约仍在各线仓。本 change 只登记这条缺口，
同步动作单独立项（见 tasks §8.4），因为它是跨仓改动。

## Risks / Trade-offs

- **[角色过滤只存在于 runtime 侧]** → 谁把 runtime 指向全量 MCP 实例，过滤层就是唯一防线。缓解：`server.mjs` 保留 denylist 作第二道闸；本 change 的 tasks 加一条「过滤层单测覆盖与 MCP 实例无关」。
- **[读/写按命名后缀判定]** → 一个叫 `contract_generate` 的工具是写（生成并落库）则靠后缀判不出。缓解：tasks 里要求逐个核对 54 个工具的实际副作用并列出清单，命名判定只作为兜底而非唯一依据。
- **[浮岛对更多会话可见]** → 任何域成员的浏览器都能打到 `/copilotkit`，而它背后是 LLM 计费。缓解：既有 `COPILOT_RUNTIME_URL` 开关仍在；本轮不加预算闸，但要记为后续 change 的挂账（助手用量没有计量，这是既存缺口）。
- **[域上下文注入的准确性]** → 注入的「下一动作」若与页面不一致，助手会说出与页面矛盾的话。缓解：注入与页面调**同一个投影函数**，判据写在 tasks（同一域同一时刻两者逐字相等）。

## Migration Plan

1. 代码：`templating.py` 门 + `copilot.py` 域解析与透传 + `assistant-ui` 带域 + `server.mjs` 角色过滤与 prompt 注入。
2. 可逆性：`COPILOT_RUNTIME_URL` 仍在——出问题时清空该环境变量，助手整体消失，工作台其余部分不受影响。
3. 灰度：先在 `legal` 域验证（它有 5,000 条条款与真实机器核对结论），再放开其余域。
4. 回滚：回退镜像 tag 即回到 admin-only 形态；无 schema 变更，无数据迁移。

## Open Questions

- `contract-review-agent` 是否仍在维护？若不是，`copilotkit-frontend` 这份规格应当整份删除而非「移到别仓」。这不影响本 change 的代码落地。
- 助手用量计费（token/调用计次）是否要进运行台账？本轮不做，属既存缺口。
