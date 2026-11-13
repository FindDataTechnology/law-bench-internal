## Context

See `proposal.md` — Why. 只补设计和落地需要、但从动机里看不出来的现状：

- **执行方有两类，机制上已经分层，只是没写下来。** `src/bench/team_roles.py` 的七个岗位全是**确定性 Python**（`run_warden` / `run_verifier` / 取材 / 结构 / 只提案），跑在 bench 进程里，无 LLM。壹座舰队是 LLM 智能体，跑在 dsh runner 上，按 `cron` 节奏起回合。同一个域同时会收到两种产物，而 `domain_agent_runs` 无法区分。
- **身份有两套且互不校验。** bench 认 `agent:<role>@<domain>`（`agent_ids.py`，API key 铸造，禁 `admin`/`*`）；壹座认 fleet / post / cell。提案行上的 `source` 只是被存下来的字符串。
- **唯一的对接线已经存在但只有一个方向。** paas `server/bench-proposal-mcp.js` 的 `bench_proposal_submit`（change `switch-fleet-proposals-to-domain-inbox`，3.1–3.3 已落，3.4/4.x/5.x 未收）。凭据走 `envRefs` 而不是环境变量字面量，因为 dsh 子进程会擦除形似凭据的 env 名（含 `*TOKEN*`）。
- **两个库不是同一个库。** bench 的生产库是 `law_bench`，且已与另一条产品线共库（这就是 `domain_agent_runs` 不能叫 `agent_runs` 的原因）。因此跨方集成只能走 HTTP 契约，不能走共表。
- **既有收敛判据必须保留。** `dispatch` 已按 `target_key` 判「同缺口已有未关闭任务则不重复创建」，`proposals` 已按 `(domain, source, external_key, pending)` 幂等、驳回后同 `evidence_digest` 拒收。新机制只能在它们之上加，不能替换。

## Goals / Non-Goals

**Goals**

- 一条闭环在真库上可判：缺口 → 工单 → 舰队认领 → 执行 → 运行回写 → 产物入箱 → 确认/驳回 → 结果回流。
- 两类执行方在同一页上可辨：值班长能一眼看出「这一轮是内核跑的，还是舰队跑的，哪个舰队哪一轮」。
- 身份从注释变成事实：三处（提案、工单、运行回写）的来源都经同一条校验，同一个登记记录。
- 内核七岗的行为与既有 spec 语义零回归。

**Non-Goals**

- 不做调度：知验台不决定舰队何时跑，工单只表示「有待办」，认领由舰队自己的节奏驱动。
- 不做共库、不做反向 RPC、不做知验台向壹座推送任务（拉取，不推送）。
- 不改 `domain_proposal_events` 与 `authoring_events` 的 append-only 性质。
- 不在本 change 做三类发布（那是 `add-typed-publications`）、不做控制台改版（那是 `optimize-domain-console`）；本 change 只提供读面所需的事实。

## Decisions

### D1 工单不新建表，`authoring_tasks` 升格

`authoring_tasks` 已经有 `status` 四态、`transitions` JSONB、`target_kind/target_key` 与幂等收敛判据，认领/完成正好是它缺的那两个转移。新建 `work_orders` 表会立刻出现「同一缺口两张单、两套状态机」，而这正是本 change 要消灭的东西。

代价：`assignee` 一列承载三种语义。用 `assignee_kind`（`human` / `kernel-role` / `fleet`）+ `assignee_ref` 两列把它挑明，`assignee` 保留为人读展示名，避免改所有既有读点。

**Alternatives considered**：① 新表 `work_orders` —— 否决，双状态机；② 只加 `assignee_kind` 不改 `assignee` 语义 —— 否决，`assignee` 同时是 `mine = task["assignee"] in {sub,email,name}` 的判据，混用会让授权判断依赖类型。

### D2 舰队登记复用 `distribution_consumers`，不建第二张登记表

`distribution_consumers` 已有 `name`（唯一）、`domains[]`、`token_hash`（唯一）、`revoked_at`，正是「谁、能碰哪些域、凭据、是否失效」这四件事。加 `kind`（`machine` / `fleet`）与 `fleet_ref` 即可。

关键取舍：**一个舰队一条登记、凭据按舰队签发**，不按岗位签发。理由：岗位是 pack 里的声明，会随 pack 版本与岗位增删变化；舰队是平台侧的实体，`source=fleet:<fleet_id>/<post_id>` 里的 `fleet_id` 才是稳定键。按岗位签发会把凭据生命周期绑在易变对象上。

**Alternatives considered**：① 新表 `fleet_registrations` —— 否决，两张表都要回答「能碰哪些域」，必然漂移；② 沿用 `agent:<role>@<domain>` 由舰队自报 —— 否决，自报身份等于没有身份。

### D3 运行台账同表分列，不建第二本账

`domain_agent_runs` 加 `origin`（`kernel` / `fleet`）与 `runner_ref`（`fleet:<id>/<post>#<round>`）。同表的价值是四态、进度不变量、`counts` 口径全部**共用一份判定代码**；两本账会让「`thin` 要不要升级给人」这类判定出现两套实现。

外部回写用 `run_key` 幂等：`run_key = runner_ref`，重放不新增行（`guard` 在 `agent_runs.start` 已有的 `run_key` 语义上扩展为唯一约束或等价的存在性检查）。**必须选存在性检查而非唯一索引**：`run_key` 允许为空（内核岗位有用例不传），Postgres 的 `UNIQUE` 对 NULL 不去重，加唯一索引会给出「看起来防住了其实没防」的安全感。

**Alternatives considered**：① 建 `fleet_runs` 表 —— 否决，判定逻辑分叉；② 回写时直接 `INSERT` 依赖调用方不重放 —— 否决，网络重试是常态。

### D4 分诊规则进代码，不进提示词

「确定性活归内核、需判断的活归舰队」写成 `dispatch.GAP_ROUTE`（缺口 → `kernel:<role>` 或 `fleet`），而不是写在岗位提示词里让 LLM 自己判断。理由：提示词是建议，代码是约束；写进提示词等于把一个可判定的规则变成概率。

`GAP_OWNER` 保留原值作为 `kernel` 一档的实现，`GAP_ROUTE` 是它的超集。缺口词表以外的值仍按既有行为报 `ValueError`。

### D5 `source` 收紧是有意的破坏性变更，配一次性迁移通道

收紧后未登记来源 403。为了不让在跑的舰队静默断掉，提供 `scripts/register_fleet.py --from-observed`：从既有 `domain_proposals.source` 里枚举出 `fleet:*` 形态的去重值，dry-run 输出计数与建议的 `fleet_ref`，由人确认后写登记。

**不做自动登记**：自动把观察到的字符串变成登记，等于把「来源是事实」换成「来源是曾经出现过的东西」，那和现在没有区别。

## Risks / Trade-offs

- [收紧 `source` 会让在跑的舰队被拒] → 先跑 dry-run 迁移；切换窗口内 `BENCH_PROPOSAL_STRICT_SOURCE=0` 保留一档宽松（记录 `legacy` 计数），观察一轮后翻硬。
- [工单与派单并存造成两张单] → 工单必须由 `dispatch.dispatch()` 创建，路由层不再有第二条 `authoring_create_task` 调用点；测试断言「路由层零直接调用」。
- [外部回写的 `counts` 口径与内核不一致，让「六项质量比」不可比] → 回写只写 `counts` 与 `artifact_refs`，比率仍由 `domain_quality_metrics` 从库重算；回写值只进台账展示，不进比率分子分母。
- [`assignee` 保留人读名会让授权判断拿到展示名] → 授权统一改读 `assignee_kind` + `assignee_ref`；`mine = assignee in {sub,email,name}` 只在 `assignee_kind='human'` 分支保留。
- [同表分列后，team 页排序把两类混在一起] → 排序键改为 `started_at DESC`，`origin` 只作分列与筛选，不参与排序（否则「最新一轮」会被某一类垄断）。
- [迁移期既有 `domain_proposals.source` 里存在无法对应任何舰队的历史值] → 归入 `legacy` 保留可读，不参与校验、不阻断读面；`legacy` 行的数量进迁移报告。

## Migration Plan

1. **加列（幂等）**：`ensure_schema` 增 `authoring_tasks.assignee_kind/assignee_ref`、`distribution_consumers.kind/fleet_ref`、`domain_agent_runs.origin/runner_ref`，全部带 `DEFAULT` 使存量行可读（`assignee_kind='human'`、`kind='machine'`、`origin='kernel'`）。
2. **回填**：`scripts/backfill_assignee_kind.py` 按 `GAP_ROUTE` 把既有派单行的 `assignee_kind` 归到 `kernel-role`（仅当 `assignee` 命中内核岗位名），dry-run 出计数。
3. **登记**：`scripts/register_fleet.py --from-observed` dry-run → 人确认 → 写登记。
4. **翻校验**：先 `lenient`（记 legacy），跑一轮真实提交与回写，确认 `legacy` 计数为 0 后翻 `strict`。
5. **回退**：把校验档位切回 `lenient`（一行配置），不动数据；列保留不影响读。
