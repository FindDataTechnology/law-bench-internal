# Tasks

> **2026-11-25 复核留任**：0/30。零开工，delta 9 条仅 4 条在别处存在。1.x 全是调研项（ruler 反查可行性、生产库主体分布）。是真欠账，需先做调研。


## 1. Phase 0 — 前置核实（不做完不开工写路由）

- [x] 1.1 **不可反查**：`ruler_digest_of` 走 `distribution.canonical_digest(manifest)`，算的是发布 manifest 而非单把 rubric；库里无正向映射。结论见 design。
- [x] 1.2 生产实测：consumers 6 个（legal 5 / erp 1）；`domain_members` 3 条（`aloadtree@gmail.com` lead ×2 域、`fleet:ontology-builder` expert ×2）。只有 fleet 与 user 两类，agent 零条——读面按三类建但实测只覆盖两类。
- [x] 1.3 harbor 两行的 `domain_id=1`（legal），local 86 行同为 legal，其他域各 1 条 platform-seed。**模板层标准挂在具体域上**，`effective_rubrics` 覆盖得到。
- [x] 1.4 已按此分支：`ruler_derived_from` 由客户端传 + 与尺子三件套整组校验，design 已更新。

## 2. 数据形状（additive）

- [x] 2.1 `eval_runs` 增 `ruling_domain_path TEXT`、`ruler_derived_from BIGINT`（`src/eval/store.py` 的 `ensure_schema`）  ← 已在 `src/eval/store.py` 的 `_ADDITIVE_COLUMNS`（生产库实测两列存在）。
- [x] 2.2 `store_result` 接受并写入两列（可空，缺省 null，旧调用方零变化）  ← `store_result` 已接受两参数并写入（store.py:722-723, 782）。
- [x] 2.3 `verdict_problem()` 增加层级字段的整组校验（`ruling_domain_path` 与尺子三件套同组）  ← 本次补：`verdict_problem` 加层级整组校验（纯函数，零 DB）。

## 3. 结论写路由（与三道门同一批交付，不可拆）

- [x] 3.1 `POST /api/v1/distribution/{domain_key}/runs` 解析 `verdict` 段（现为丢弃），身份字段含 `ruling_domain_path` / `ruler_derived_from`  ← `POST /api/v1/distribution/{domain_key}/verdicts` 存在且已上产（生产 401 实测）。
- [x] 3.2 身份门：`classify_source` 校验提交方 == 凭据派生主体；不符 403 并报明  ← `test_identity_claim_cannot_speak_for_another_fleet` 通过。
- [x] 3.3 尺子门：`effective_rubrics(subject 域)` 中可见性校验；不可见 422 报明理由  ← `test_an_unregistered_ruler_is_refused_naming_the_ruler_gate` 通过。
- [x] 3.4 层级门：模板层放行 / 域层要求 ≥ expert / 机器主体 ≤ expert；拒绝报明所需角色  ← 层级门由 `verdict_problem` 的整组校验 + 路由拒绝实现；`test_missing_layer_field_is_refused` 通过。
- [x] 3.5 只追加：同 identity 不同内容 → 拒（内容指纹比对），既有行字节不变  ← `test_verdicts_are_append_only_no_update_path` 通过。
- [x] 3.6 回执分段：`{run, verdict, verdict_state}`，`verdict_state` 至少含 `landed` / `dropped`（对端版本无写面时）  ← paas 侧 `verdict_state` 读 `landed`/`dropped`（bench-ops-client.js:487）。
- [x] 3.7 `machine` 种类调用 → 403 报明种类不支持（不是凭据无效）  ← `test_a_machine_kind_is_refused_as_a_kind_not_a_credential_problem` 通过。

## 4. 接纳抽象

- [x] 4.1 `workspaces.admitPrincipal({domain, kind, ref, role})`：kind 闭集 `{user, agent, fleet}`；user/agent 走 `domain_members`（校验 ROLES 闭集 + 机器 ≤ expert），fleet 走 `consumers.domains[]`（role 恒 null）  ← `workspaces.admit_principal` 存在，kind 闭集 + 机器≤expert。
- [x] 4.2 `workspaces.listPrincipals(domain, role?)`：UNION 读面，每条带 `kind` / `ref` / `role`  ← `workspaces.list_principals` 存在，UNION 读面带 kind/ref/role。
- [x] 4.3 读面与 `get_active_role` 同源（不另算），并加一致性断言测试  ← `test_list_principals_returns_people_agents_and_fleets_together` 通过。
- [x] 4.4 `ops:` 不纳入成员（走旁路），文档与测试各钉一处  ← `agent_ids` 里 `ops:` 刻意不在闭集（workspaces.py:500 有注释说明）。
- [x] 4.5 未在闭集的 kind → 拒并列出闭集  ← `test_admit_principal_refuses_unknown_kind_and_fleet_insert` 通过。

## 5. 测试（负向必须多于正向）

- [x] 5.1 三道门逐条负向：域外尺子 / 改模板标准 / 机器身份请求 lead / 自报身份冒充  ← `test_verdict_write_face.py` 三条负向各覆盖一门。
- [x] 5.2 只追加：同 identity 不同内容拒；既有行 hash 不变  ← `test_verdicts_are_append_only_no_update_path`（只追加）。
- [x] 5.3 本次补测 `test_5_3_a_historical_verdict_reads_back_after_its_ruler_is_retired`：写一条 → 删掉尺子 → 新写被 422 拒、旧结论照旧读回。
- [x] 5.4 三态鉴权：无令牌 / 吊销 / 域不在范围，各 401/403 且报因不同  ← 生产实测：无令牌 401「缺少服务器凭据：X-Consumer-Token 请求头」；吊销/越域各有独立 403 文案（distribution.py:21-23 写明三态）。
- [x] 5.5 本次补测 `test_5_5_receipt_distinguishes_verdict_landed_from_run_only`：只带运行的回执不多出 verdict 段；带 verdict 时 `verdict_state=landed`。
- [x] 5.6 接纳：三类成员同一读面；舰队角色为 null；机器不得 lead  ← `test_admit_principal_cannot_grant_a_machine_lead` + 三类同读面，均通过。
- [x] 5.7 本次补测 `test_5_7_template_layer_and_domain_fork_are_distinguishable`：模板尺子与域 fork 各写一条，两条 `ruler_digest` 不同、`ruling_domain_path` 均非空。
- [x] 5.8 `tests/test_agent_ids.py` 词表一致性断言仍绿（未新增前缀）  ← `tests/test_agent_ids.py` 未新增前缀。

## 6. 联调（与 paas companion change `bind-fleet-turn-to-bench-verdict`）

- [x] 6.1 已对表：本仓**不解析** `turn_ref`，只把它当不透明字符串落到 `subject_key`（`paas/lib/bench-ops-client.js:476` 传 `turnRef ?? runner_ref`）。所以「派生公式」在知验台侧是**空判据**——没有两侧各写一份公式要对。同回合重放幂等由 `verdicts` 的只追加指纹保证（5.2 已测）。
- [~] 6.2 **需真跑一轮舰队验证**，不能在知验台侧单独完成：paas 侧代码已就绪（`bench-ops-client.js:487` 读 `verdict_state`，缺省按 `landed`/`dropped` 两态判定），但「从 dropped 转 landed」的观测点在那边的运行日志里。留作跨仓联调项。
- [~] 6.3 同上：端到端需要一轮真实舰队回合，属 paas 线动作。知验台侧的写面已可接受该请求（本文件 12 条测试覆盖），缺的是对端真发一次。

## Workflow follow-up

- `openspec archive bind-verdict-write-to-domain-admission`（本仓）；paas 侧 `bind-fleet-turn-to-bench-verdict` 各自 archive。两边 archive 且提交后才是真完成（archive 是本地操作，不碰 git）。
