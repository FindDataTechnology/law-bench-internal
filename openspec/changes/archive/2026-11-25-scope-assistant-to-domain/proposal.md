# 副驾驶收编为域内助手（Scope Assistant to Domain）

## Why

工作台助手（`admin-assistant-web`，2026-09-26 落）是知验台**唯一没跟着平台演进的一个面**。它的规格写于域优先工作台（C5）、智能体团队（C7）、四层本体、评测结论台账之前，此后一次没有回看。实测后果：

- **只有 `admin` 能用。** 真正干活的是域里的 lead / expert / annotator，三种角色全被挡在外面（`src/web/templating.py:126`）。
- **助手不知道「域」存在。** 它把 54 个 MCP 工具平铺给模型，没有当前域、没有该域的下一动作、没有机器核对判据——平台这一周新建的读面它一个也看不见。
- **它是活的但没人用。** runtime pod Running、`health` 200、`COPILOT_RUNTIME_URL` 已配（admin 会话里浮岛是可见的），而 24 小时内 runtime 日志 0 行。

同时，本仓的规格清单里混着**另一个产品**的 copilot 规格：`copilotkit-frontend`（Next.js + LangGraph + HumanInTheLoop 三处，属 `contract-review-agent` 那条线）。2026-11-08 的一次 polish change 里有人写下「岛内交互有独立 `copilotkit-frontend` spec 管辖」——那句话把两个不同的产品指成了一条线，此后再没人纠正。留着它，读规格的人会一直以为工作台助手是 Next.js 应用。

## What Changes

- **权限门从 `admin` 改为「当前域的 active 成员」。** 浮岛对域成员可见，按域角色收敛能力面；平台 admin 保留跨域视图。
- **助手拿到域上下文。** `/copilotkit` 代理转发时带当前域 key；runtime 把它注入 prompt，并能让模型读到该域的下一动作与机器核对结论。
- **工具面按域角色收敛。** 在 runtime 侧过滤（`server.mjs` 已有 `TOOL_DENYLIST` 那一层可扩展），annotator 只读、expert 可写、lead 可发布/升格；删除类对所有角色仍禁。
- **规格与实际对齐。** `admin-assistant-web` 的 Purpose 与五条需求按域模型重写；运行时栈（FastAPI 同源代理 + CopilotKit 浮岛 + Node runtime + MCP）如实写进 design。
- **清出 `copilotkit-frontend`。** 它是 `contract-review-agent` 那条线的规格，不属于本仓；从 `openspec/specs/` 移除，并把 2026-11-08 那句错误指认改掉。

## Capabilities

### New Capabilities

- `domain-assistant-context`: 助手与「当前域」的绑定契约——域如何解析、角色如何决定能力面、无可访问域时的降级；以及「助手不得跨域读取」的边界。

### Modified Capabilities

- `admin-assistant-web`: 入口的权限门由 admin scope 改为域成员身份；工具面由平铺改为按域角色收敛；新增「助手能读到当前域的下一动作与机器核对结论」这一读面要求；Purpose 按域模型重写。

## Impact

**代码（law-bench-internal）**

- `src/web/templating.py`：`assistant_enabled` 从 `_has_scope(user,"admin")` 改为域成员解析（复用 `src/web/domain_context.py` 的解析器）。
- `src/web/routes/copilot.py`：代理转发时注入当前域 key 与角色；仍是唯一公共路径，门不变。
- `assistant-ui/src/main.tsx`：把当前域与角色传给 runtime（provider 配置）。
- `copilot-runtime/server.mjs`：按域角色过滤工具面；prompt 注入域上下文；保留既有 denylist 作为第二道闸。
- `src/web/templates/base.html`：浮岛的挂载条件随之放宽（仍是「配了 runtime 才出现」）。

**数据**：零 schema 改动。域/成员/角色全部复用既有 `domains` / `domain_members` / `workspaces.ROLE_RANK`。

**规格（本仓 `openspec/`）**

- `openspec/specs/copilotkit-frontend/` 删除（属外部线）。
- `openspec/changes/archive/2026-11-08-polish-bench-workbench/design.md` 一句错误指认改正。

**不做什么**

- 不动 `contract-review-agent` 本身（它的 Next.js 前端与 LangGraph 后端与本 change 无关）。
- 不给助手新增写面（确认提案、升格、发布仍走页面）。助手这版仍是「域内阅读与问答」，写面要单独立 change。
- 不改 MCP 实例数量：`law-bench-mcp-assistant` 仍是唯一的助手 MCP 实例，角色过滤在 runtime 侧。

**风险**

- 角色过滤在 runtime 侧意味着「MCP 实例本身不认角色」——如果将来有人把 runtime 指向全量实例，过滤层是唯一防线。`server.mjs` 的 denylist 注释里已有同样判断，本 change 把这条写进 design 作为显式约束。
- 浮岛对域成员可见后，任何域专家的会话都能打到 `/copilotkit`。代理的域解析必须 fail closed：解析不到域就拒绝，不能退化成「无域上下文」。这一点是本 change 的第一条判据。
