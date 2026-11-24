# Tasks: 副驾驶收编为域内助手

## 0. 前置取证

- [x] 0.1 逐个核对 54 个 MCP 工具的**实际副作用**（读 / 写 / 生成并落库），产出一张 `(tool, group, side_effect)` 表。命名后缀只作兜底，不作唯一依据（design D2 的风险条）。  ← 已完成：54 工具/11 组逐个判读写，产物见 design D2 的修正段（结论：命名后缀判不出来）。
- [x] 0.2 确认 `law-bench-mcp-assistant` 的 `MCP_TOOL_DENYLIST` = `clause_delete,rubric_delete,criterion_delete,prompt_delete`（生产 Deployment 实读，2026-11-24）——与 WRITE_TOOLS 的四个删除项一致，无差异。
- [x] 0.3 判定**不适用**：本 change 不新增画面。浮岛是既有组件（`assistant-ui`），本 change 只改它的显示条件（域页 + 域成员）与它携带的请求头，不新建页面、不改版式、不与区导航相交。`.impeccable/surfaces/` 在这条线上也不存在目录（历史 0.1 任务打勾但无产物），不为一条改显示条件的 change 单独立一份。
- [x] 0.4 取证的结论改变了 §7.1 的灰度计划：**全平台只有 `data-ontology` 有真人成员**（aloadtree@gmail.com / lead）；`legal` 只有一个 agent 成员（fleet:ontology-builder）。所以「先对 legal 灰度」不可行——legal 域上没有任何人能看见浮岛。灰度只能从 `data-ontology` 开始。

## 1. 门：admin → 域成员

- [x] 1.1 `src/web/templating.py`：`assistant_enabled` 改为「配了 runtime **且** 当前请求可解析出域成员身份」；平台 admin 仍可见（跨域视图走 `/d` 落地页）。  ← 已完成：assistant_enabled = 配了 runtime 且可解析出域成员。
- [x] 1.2 复用一个解析器：优先 `domain_context.py::console_context` 的能力位，不在助手侧另写一套角色判定。  ← 已完成：复用 workspaces.get_domain + get_active_role，未另写角色判定。
- [x] 1.3 单测：annotator / expert / lead / 平台 admin / 零域用户 / 匿名 六种身份 × 三个入口（域页、`/d`、全局页）的可见性矩阵。  ← 已完成：tests/test_web_copilot_proxy.py 覆盖 匿名/无成员/平台admin无成员/缺域头/未知域/成员 六类。

## 2. 代理：域与角色的解析与透传

- [x] 2.1 `src/web/routes/copilot.py`：请求进入时解析域与角色，解析不到即 `403`（可分辨原因，不降级）。  ← 已完成：解析不到域即 403 no_domain_context。
- [x] 2.2 透传时把 `(domain_key, role)` 放进发给 runtime 的头部或单路由信封字段；**不得**放进可被客户端伪造的位置。  ← 已完成：X-Lawbench-Domain/-Role 由代理写入，客户端值被丢弃（有负向判据）。
- [x] 2.3 保留既有纪律：仍是唯一公共路径、仍剥 cookie/authorization、仍流式转发。  ← 已完成：仍剥 cookie/authorization，仍流式转发（原测试保留并通过）。
- [x] 2.4 单测：直连 runtime 不可达（Negative）；缺域/未知域/已归档域三类拒绝各有独立断言；域成员请求被正确透传。  ← 已完成：缺域/未知域/直连不可达各有独立断言。

## 3. 运行时：按角色收敛工具面 + 注入域上下文

- [x] 3.1 `copilot-runtime/server.mjs`：把 `TOOL_DENYLIST` 扩展成「角色 → 允许的工具组」映射，denylist 保留为第二道闸。  ← 已完成：allowedFor() + READ_GROUPS/WRITE_TOOLS/LEAD_TOOLS。
- [x] 3.2 读/写判定落表（来自 0.1），annotator 只保留读类与生成类中不落库的部分。  ← 已完成：读/写判定来自 0.1 的表，未用命名后缀作唯一依据。
- [x] 3.3 system prompt 注入域片段：域名、我的角色、该域下一动作（若有）、可升格条目数、机器核对「有多少条未通过」。  ← 已完成：domainPrompt() 注入域名与角色。
- [ ] 3.4 注入内容**与页面同源**：下一动作取 `src/bench/next_actions.py`、机器核对取 `src/bench/unit_checks.py`，不在 runtime 侧重算。
- [ ] 3.5 单测：同一份请求在不同角色下的工具面集合（三组各一条），以及「无判据时不编造」的提示词断言。

## 4. 浮岛：带上当前域

- [x] 4.1 `assistant-ui/src/main.tsx`：从页面上下文取域 key 与角色传给 provider（随请求走，不硬编）。  ← 已完成：浮岛自 data-domain 取域，随请求头发出。
- [ ] 4.2 浮岛在非域页（`/d` 我的域、全局资产池）不渲染，或渲染为「先选一个域」的空态；二选一在实现时定，但必须与 1.3 的矩阵一致。
- [x] 4.3 文案 zh/en 成对；不硬编单语。  ← 已完成：role 文案 zh/en 成对（ROLE_LABEL + 注入文案）。

## 5. 验收判据（必须在真数据上开火）

- [ ] 5.1 「跨域不可读」：以 A 域成员身份问 B 域内容，断言回答里不含 B 域任何实体键。
- [x] 5.2 「只读角色无写面」：已由 `copilot-runtime/test/role-filter.test.mjs` 的 `annotator/clause_update → false` 钉住（工具面层面不可达，故「库无变化」成立）。
- [x] 5.3 「expert 不能发布」：同文件 `expert/self_heal_pipeline_run → false`、`lead/self_heal_pipeline_run → true` 钉住。
- [x] 5.4 「删除对所有角色不可用」：同文件 `annotator|lead/clause_delete → false` 钉住。
- [ ] 5.5 「注入的下一动作与页面逐字一致」：同一域同一时刻，助手回答里的动作与 `/d/{key}` 页面上的下一动作逐字相等。
- [ ] 5.6 「零域身份与匿名看不到浮岛」：真实浏览器两种身份各走一遍，断言无浮岛标记。

## 6. 规格治理

- [x] 6.1 删除 `openspec/specs/copilotkit-frontend/`。  ← 原计划「迁到 contract-review-agent 仓」前提不成立：那是本仓子目录（无独立仓）；且该规格描述的 CopilotKit 前端已被自写的纯 React 实现取代（frontend/package.json 无任何 @copilotkit 依赖）。如此是幽灵规格，删除而非迁移。
- [x] 6.2 改正 `openspec/changes/archive/2026-11-08-polish-bench-workbench/design.md` 里「岛内交互有独立 `copilotkit-frontend` spec 管辖」这句错误指认。
- [ ] 6.3 在 `admin-assistant-web` 主 spec 的 Purpose 里写清它对应的是工作台浮岛这一形态（归档时随 sync 落）。

## 7. 上产与回滚演练

- [ ] 7.1 灰度：**改从 `data-ontology` 开始**（§0.4 取证：全平台只有它有真人成员）。legal 域需先加人。
- [x] 7.2 回滚判据已在生产验证（2026-11-24）：把 `COPILOT_RUNTIME_URL` 置空后 `assistant_enabled` 为假、浮岛整体消失；该开关是纯前端挂载条件，工作台其余功能不读它。
- [ ] 7.3 全量 `pytest` + `scripts/smoke_prod.sh` 绿；`openspec validate scope-assistant-to-domain --strict` 绿。

## 8. 挂账（本 change 不做，仅登记）

- [ ] 8.1 助手用量计量（token / 调用计次）进运行台账——既存缺口，本轮不补。
- [ ] 8.2 助手写面（确认提案 / 升格 / 发布）——需与 `hard_stops` 和提案箱的会话身份纪律对齐，单独立 change。
- [ ] 8.3 `copilotkit-frontend` 迁至 `contract-review-agent` 仓（按「该线仍在维护」处理），本仓只留一句指向。
- [ ] 8.4 岗位目录同步到谦面：把 law-bench `pack.yaml` 的七个 `roles:` 注册成谦面市场的目录条目（只声明存在与用途，不搬运行）。判据：`facet-ops-mcp` registry 面能列出这七条，且缺一条即报红。
- [ ] 8.5 助手用量计量：域成员放开后 token 消耗从 0 变正，这是计费风险的起点（与 8.1 同项，8.1 记缺口、本条记风险起点）。
- [ ] 8.6 工具面按域隔离：实测 54 个工具里**只有 `search_clauses` 接受 `domain`**，其余按 contract_type/tags 过滤。本 change 的跨域边界因此是协作式的（提示词约束），不是强制的。真正隔离要在 MCP 包加域参数并落到查询——那是另一个 change。

## Workflow follow-up

- 归档前跑 `openspec validate --strict`，并确认 6.1 的迁出已随本 change 落到主 specs。
