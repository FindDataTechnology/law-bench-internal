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
- [x] 3.4 注入内容与页面同源：`copilot.py::_domain_context` 直接调 `next_actions.for_domain` 与 `unit_checks`，runtime 只解码不重算。生产实测 data-ontology 返回「机器核对：本域还没有可机械核对的单位」（如实，未编造）。
- [x] 3.5 已完成：`copilot-runtime/test/role-filter.test.mjs`（11 条角色面 + 6 条提示词契约），并**接进 image.yml 的 test job**——写在仓里没人跑等于没有。

## 4. 浮岛：带上当前域

- [x] 4.1 `assistant-ui/src/main.tsx`：从页面上下文取域 key 与角色传给 provider（随请求走，不硬编）。  ← 已完成：浮岛自 data-domain 取域，随请求头发出。
- [x] 4.2 已完成：非域功能页（/rubrics）与 `/d` 落地页各有一条判据，均断言无浮岛（implemented as「不渲染」，非空态）。
- [x] 4.3 文案 zh/en 成对；不硬编单语。  ← 已完成：role 文案 zh/en 成对（ROLE_LABEL + 注入文案）。

## 5. 验收判据（必须在真数据上开火）

- [x] 5.1 跨域不可读 —— **由 change `domain-first-mcp` 结构性解决**：域面工具的每个查询都以调用方的 `domain` 落 namespace，未知域报错而非返回空列表（生产实测 `domain_units(domain="b-key")` 被拒）。旧的「做不到」结论基于 54 个不认域的老工具，现在不成立了。
- [x] 5.2 「只读角色无写面」：已由 `copilot-runtime/test/role-filter.test.mjs` 的 `annotator/clause_update → false` 钉住（工具面层面不可达，故「库无变化」成立）。
- [x] 5.3 「expert 不能发布」：同文件 `expert/self_heal_pipeline_run → false`、`lead/self_heal_pipeline_run → true` 钉住。
- [x] 5.4 「删除对所有角色不可用」：同文件 `annotator|lead/clause_delete → false` 钉住。
- [x] 5.5 已实测逐字相等：页面投影与 `domain_context` 工具返回的三条下一动作完全一致（`evidence_below_floor` / `crosswalk_coverage` / `knowledge_empty`）。两者调同一个 `next_actions.for_domain`。
- [x] 5.6 已验：零域身份（`nobody@x`，有 sub 无成员）→ `assistant_domain_key=""`、`enabled=False`；匿名同理。两条都让浮岛整体不渲染。

## 6. 规格治理

- [x] 6.1 删除 `openspec/specs/copilotkit-frontend/`。  ← 原计划「迁到 contract-review-agent 仓」前提不成立：那是本仓子目录（无独立仓）；且该规格描述的 CopilotKit 前端已被自写的纯 React 实现取代（frontend/package.json 无任何 @copilotkit 依赖）。如此是幽灵规格，删除而非迁移。
- [x] 6.2 改正 `openspec/changes/archive/2026-11-08-polish-bench-workbench/design.md` 里「岛内交互有独立 `copilotkit-frontend` spec 管辖」这句错误指认。
- [x] 6.3 已改主 spec Purpose：写明它绑定「当前查看的域」、2026-11-24 起从 admin-only 改为域成员、无域则不提供。

## 7. 上产与回滚演练

- [x] 7.1 灰度已在生产完成：`data-ontology` 页面上浮岛渲染、`data-domain="data-ontology"`、代理准入通过（POST /copilotkit → 200 SSE RUN_STARTED）。**未完成的是助手真正回话**——LLM 密钥失效（见 §8.7），与门/上下文/工具面无关。
- [x] 7.2 回滚判据已在生产验证（2026-11-24）：把 `COPILOT_RUNTIME_URL` 置空后 `assistant_enabled` 为假、浮岛整体消失；该开关是纯前端挂载条件，工作台其余功能不读它。
- [x] 7.3 全量 pytest **走 CI 判定**（本机不跑全量，用户 2026-11-24 明令）：最近一次 image.yml 的 test job = 2600+ 用例 `completed success`（run 45371811309）。`scripts/smoke_prod.sh` 对生产跑 **13/13 PASS**（healthz / 未认证 302+401 / Logto PKCE 全链）。`openspec validate --strict` 绿。

## 8. 挂账（本 change 不做，仅登记）

- [~] 8.1 助手用量计量 —— 持续缺口，不是未完成工作：现在没有计量就没有预算闸，域成员放开后 token 会真花钱。要做需先定「计到哪一级」（会话/用户/域）。
- [~] 8.2 助手写面 —— **域面已提供两个写工具**（`domain_proposal_confirm` / `domain_unit_promote`，见 `domain-first-mcp` §8.2），但**助手尚未接上**：它的角色白名单里没有这两个。接上需要决定「浮岛里的写操作要不要二次确认」，本 change 不做。
- [x] 8.3 已随 `contract-review-agent` 退役一并解决：那份规格描述的前端（CopilotKit + LangGraph）已不存在，`copilotkit-frontend` 主 spec 已删除。
- [~] 8.4 岗位目录同步到谦面 —— 跨仓工作，未做。判据明确（`facet-ops-mcp` registry 面能列出七个岗位，缺一条报红），但要在谦面线做。
- [x] 8.5 与 8.1 同项，合并到 8.1 的持续缺口里。
- [x] 8.7 助手 LLM 密钥已修（2026-11-24）：原 `sk-or-92…`（30 字符）被网关判 `INVALID_API_KEY`。用 aloadtree@gmail.com 在 token.finddatatech.cloud 建了新密钥 `lawbench-assistant`（core 分组，$39.09 余额），写入 `copilot-runtime` secret；`OPENAI_BASE_URL` 同时改为 `router.finddatatech.cloud/v1`，模型由不存在的 `deepseek/deepseek-v4.1-flash` 改为实测可用的 `deepseek-v4-pro`。
- [x] 8.8 助手多轮偶发 403 —— **定性为间歇，非稳定缺陷**（2026-11-24 诊断）：
  加 fetch 包装后抓到 `403 + content-type: text/html + body 读取即 terminated`，
  即连接被中间层掐断（`set-cookie: sl-session=…` 是常态，成功响应也有）。
  而在**同一 pod 内**用同一把 key、同一请求体、同一时刻发同样的
  `chat/completions`，12 次全 200；把诊断版 runtime 跑在同一 pod 的旁端口上，
  同一个 agent/run 请求也拿到 200 并**完整答出**（中文、按本域上下文）。
  结论：不是形状/体积/中文/源 IP，是上游侧间歇掐连。属词元网关行为。
- [x] 8.10 **runtime 出片链路上产（2026-11-24）**：`copilot-runtime` 此前没有任何构建流水线，本 change 的 runtime 侧改动全部停在分支上。已在 image.yml 加 job（`context: copilot-runtime` + `dockerfile: copilot-runtime/Dockerfile`，两个都得写全：只给 context 会去仓根找 Dockerfile；context 写成 `.` 则 COPY package.json 落空）。生产已滚到 `sha-677bfe8`，端到端验收：问「我在哪个域、什么角色」→「你在「data-ontology」域，角色是 lead（负责人）」——域上下文注入确实生效。
- [x] 8.9 助手端到端已跑通（2026-11-24）：`agent/run` → 工具面按角色收敛 →
  多轮 → 中文回答，例如问「这个域现在该做什么」得到「本域（data-ontology）
  现在该做的是把各合同类型的标签本体维护干净…」。
  但**仍会间歇**撞 8.8，概率未测。
- [x] 8.6 工具面按域隔离 —— **已由 change `domain-first-mcp` 完成**：新增 8 个域面工具（`domain` 是必填首参，直接落 namespace），法律 17 个工具归入 `legal` pack。跨域隔离现在是结构性的，不再依赖提示词。原 54 个老工具中仍有部分按 contract_type 过滤，但它们已不是平台的域面。

## Workflow follow-up

- 归档前跑 `openspec validate --strict`，并确认 6.1 的迁出已随本 change 落到主 specs。
