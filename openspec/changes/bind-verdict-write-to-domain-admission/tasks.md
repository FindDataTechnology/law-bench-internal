# Tasks

> **2026-11-25 复核留任**：0/30。零开工，delta 9 条仅 4 条在别处存在。1.x 全是调研项（ruler 反查可行性、生产库主体分布）。是真欠账，需先做调研。


## 1. Phase 0 — 前置核实（不做完不开工写路由）

- [ ] 1.1 确认 `ruler_digest_of()` 可在库内反查：给定 digest 能否找到对应 rubric 行（决定 `ruler_derived_from` 由谁写）
- [ ] 1.2 确认生产库 `consumers.domains` 与 `domain_members` 的实际主体分布（人 / agent / fleet 各多少），据此校准入读面
- [ ] 1.3 确认 `effective_rubrics(subject 域)` 是否包含模板层标准（harbor 行 `domain_id` 指向哪个域）
- [ ] 1.4 若 1.1 反查不可行：`ruler_derived_from` 改由客户端传并整组校验，更新 design

## 2. 数据形状（additive）

- [ ] 2.1 `eval_runs` 增 `ruling_domain_path TEXT`、`ruler_derived_from BIGINT`（`src/eval/store.py` 的 `ensure_schema`）
- [ ] 2.2 `store_result` 接受并写入两列（可空，缺省 null，旧调用方零变化）
- [ ] 2.3 `verdict_problem()` 增加层级字段的整组校验（`ruling_domain_path` 与尺子三件套同组）

## 3. 结论写路由（与三道门同一批交付，不可拆）

- [ ] 3.1 `POST /api/v1/distribution/{domain_key}/runs` 解析 `verdict` 段（现为丢弃），身份字段含 `ruling_domain_path` / `ruler_derived_from`
- [ ] 3.2 身份门：`classify_source` 校验提交方 == 凭据派生主体；不符 403 并报明
- [ ] 3.3 尺子门：`effective_rubrics(subject 域)` 中可见性校验；不可见 422 报明理由
- [ ] 3.4 层级门：模板层放行 / 域层要求 ≥ expert / 机器主体 ≤ expert；拒绝报明所需角色
- [ ] 3.5 只追加：同 identity 不同内容 → 拒（内容指纹比对），既有行字节不变
- [ ] 3.6 回执分段：`{run, verdict, verdict_state}`，`verdict_state` 至少含 `landed` / `dropped`（对端版本无写面时）
- [ ] 3.7 `machine` 种类调用 → 403 报明种类不支持（不是凭据无效）

## 4. 接纳抽象

- [ ] 4.1 `workspaces.admitPrincipal({domain, kind, ref, role})`：kind 闭集 `{user, agent, fleet}`；user/agent 走 `domain_members`（校验 ROLES 闭集 + 机器 ≤ expert），fleet 走 `consumers.domains[]`（role 恒 null）
- [ ] 4.2 `workspaces.listPrincipals(domain, role?)`：UNION 读面，每条带 `kind` / `ref` / `role`
- [ ] 4.3 读面与 `get_active_role` 同源（不另算），并加一致性断言测试
- [ ] 4.4 `ops:` 不纳入成员（走旁路），文档与测试各钉一处
- [ ] 4.5 未在闭集的 kind → 拒并列出闭集

## 5. 测试（负向必须多于正向）

- [ ] 5.1 三道门逐条负向：域外尺子 / 改模板标准 / 机器身份请求 lead / 自报身份冒充
- [ ] 5.2 只追加：同 identity 不同内容拒；既有行 hash 不变
- [ ] 5.3 历史结论在读面不重新校验（先写一条、再停用其尺子、再读回成功）
- [ ] 5.4 三态鉴权：无令牌 / 吊销 / 域不在范围，各 401/403 且报因不同
- [ ] 5.5 回执：结论落 / 结论被丢（写面缺）/ 只带运行（旧形状零变化）
- [ ] 5.6 接纳：三类成员同一读面；舰队角色为 null；机器不得 lead
- [ ] 5.7 层级可分：模板标准与域 fork 各一条结论，`ruling_domain_path` 与血统可区分
- [ ] 5.8 `tests/test_agent_ids.py` 词表一致性断言仍绿（未新增前缀）

## 6. 联调（与 paas companion change `bind-fleet-turn-to-bench-verdict`）

- [ ] 6.1 与 paas 侧同一 `turn_ref` 派生公式对表；同回合重放幂等
- [ ] 6.2 paas 侧 `verdict_state` 从 `dropped` 转 `landed`
- [ ] 6.3 端到端：一轮真实舰队回合 → 结论落库 → paas 拍板行能解析出 `verdict_ref` + `ruler_digest`

## Workflow follow-up

- `openspec archive bind-verdict-write-to-domain-admission`（本仓）；paas 侧 `bind-fleet-turn-to-bench-verdict` 各自 archive。两边 archive 且提交后才是真完成（archive 是本地操作，不碰 git）。
