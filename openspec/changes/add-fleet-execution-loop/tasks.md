# Tasks: add-fleet-execution-loop

> 判据先写、代码后写：每个 § 的头两条任务是把「怎么算做对了」钉在真库/真请求上，跑不出读数就不动实现。
> 依赖顺序：0 → 1 → 2 → 3 → 4 → 5 → 6 → 7。§2 与 §3 可并行；§4 依赖 §2 的登记表；§5 依赖 §1/§3/§4 的读面。

## 0. 前置：先把事实钉住

- [x] 0.1 基线取证（只读，2026-11-13 实测生产 `law_bench`）：`domain_proposals` 93 行 → `extract:*` 78 / `fleet:*` 12（含 1 条 `credential-probe` 探针）/ `agent:*` 4；`authoring_tasks` 1 行（`agent:concept@legal`）；`domain_agent_runs` 17 行且确认无 `origin`/`runner_ref`；`distribution_consumers` 2 行（`fd-wire`、`ontology-fleet-win`，均绑 legal）；`domains` 4 个。读数已写入 `design.md`「基线读数」，并据此把校验改为按前缀分三类（D6）
- [x] 0.2 DDL 进 `src/bench/workspace_store.py`（全部带 DEFAULT，幂等 `ADD COLUMN IF NOT EXISTS`）：`authoring_tasks.assignee_kind`（默认 `human`）/ `assignee_ref`、`distribution_consumers.kind`（默认 `machine`）/ `fleet_ref`、`domain_agent_runs.origin`（默认 `kernel`）/ `runner_ref`；`ensure_schema` 一次建齐
- [x] 0.3 启动壳测试扩展 `tests/test_boot_schema.py`：空库跑 boot 后六列就位（跨新连接复核已提交）、重复执行幂等、旧库（无这些列）跑一次后列出现且存量行取到默认值
- [x] 0.4 `docs/domain-proposal-contract.md` 增来源校验与结局读面两节；`tests/test_domain_proposal_contract_doc.py` 双侧校验保持不漂（文档字段集 ↔ 实现字段集）。新增覆盖：四类来源与各自信任依据、九条拒绝原话（双向：文档引了代码里必须有）、四条读面路由
- [x] 0.5 i18n 新键骨架（`workorder.*`、`console.workorder.*`、`console.fleet.*`、`inbox.outcome.*`）zh/en 成对落 `src/web/i18n.py`  → **部分**：工单三键（claim/already-claimed/completed）已加，`workorder.*` 区级键随 1.7

## 1. 工单化（`domain-work-order`）

- [x] 1.1 `src/bench/dispatch.py` 新增 `GAP_ROUTE`（缺口 → `kernel:<role>` / `fleet` / `human`），以 `GAP_OWNER` 为 `kernel` 档的来源；表外缺口保持既有 `ValueError`
- [x] 1.2 `src/bench/dispatch.py` 的 `dispatch()` 入参从自由文本 `assignee` 改为 `(assignee_kind, assignee_ref, display_name=None)`；创建走 `authoring_create_task`，并在缺列时补默认
- [x] 1.3 `src/bench/authoring.py`：`authoring_create_task` 接收类型化指派人并校验三档引用（人身份非空、内核岗位在词表内、舰队引用经 §2 的登记解析且域匹配）
- [x] 1.4 `src/bench/authoring.py`：新增 `authoring_claim_task`（`pending`→`in_progress`，排他，记录认领者与时间）与 `authoring_complete_task`（`in_progress`→`done`，带产物引用与结局说明）；两者各落一条 `transitions` 事件
- [x] 1.5 排他认领的实现方式：`UPDATE ... WHERE id=%s AND status='pending'` 影响行数为 0 即返回「已被认领」，MUST NOT 先查后改（先查后改在并发下会双成功）
- [x] 1.6 `src/web/routes/console.py`：派单路由只调 `dispatch.dispatch()`，删掉任何直接 `authoring_create_task` 的旁路；测试断言「console 路由模块内零直接调用」
- [x] 1.7 `GET /d/{domain_key}/work-orders`（域内可见的工单列表，按状态与指派人筛选）；`domain_dispatch.html` 的指派人从自由输入改为三档选择（人自由填、内核岗位下拉、舰队下拉只列绑定本域的已登记舰队）。这一页单独存在的理由：总览的「我的任务」只匹配 `assignee == user.sub`，派给岗位或舰队的工单在那里根本看不见——它存在、挡住重复派单、而没人能关。舰队下拉只列**绑定本次将派到的域**的活登记（列一支绑在别处的舰队＝给一个点了必然失败的选项）
- [x] 1.8 界面如实区分两档后果：派给内核岗位显示「内核岗位下一轮执行」，派给舰队显示「等待舰队认领」，不共用同一句「已派出」。工单页每行也带同一句——值班的人据此判断要不要催，措辞错了判断就错了
- [x] 1.9 归人的缺口（评审积压）在派单页显示「归人处理」且不可选智能体：`route == 'human'` 时只渲染人这一档，页面上不出现 `fleet` / `kernel-role` 选项
- [x] 1.11 `GET /api/v1/distribution/{domain_key}/work-orders`（规格「工单按执行方可见」要求的机器读面，**原任务表漏列**）：只返回派给本舰队、本域、未关闭（`pending`/`in_progress`）的单，载荷含工单标识/目标/标题/详情/创建时间/状态与已认领人；重复拉取零副作用（载荷逐字相同、事件流一行不增）。去掉归属与关闭过滤后该条注入转红
- [x] 1.10 单测：类型化三档各一条正例、词表外岗位被拒、未登记舰队被拒、跨域舰队被拒、`pending` 直接完成被拒、并发认领只一个成功、完成不写知识单元（断言 `knowledge_units` 行数不变）

## 2. 舰队登记与来源校验（`fleet-submitter-contract` / `knowledge-distribution`）

- [x] 2.1 `src/bench/distribution.py`：`register_consumer` 增 `kind` 与 `fleet_ref`；校验「同一实体至多一条未吊销登记」；`list_consumers` 投影两列
- [x] 2.2a `src/bench/submitters.py`：**零 DB 依赖**的判定纯函数 `classify_source` / `verdict` / `is_allowed`，九类结论（`ok` / `unregistered` / `revoked` / `domain_mismatch` / `pipeline_impersonation` / `agent_domain_mismatch` / `agent_not_member` / `malformed` / `unknown_prefix`）；`tests/test_submitter_contract.py` 36 条穷举（含生产库真实来源形状），已注入验证可红（放行 `extract:` 后 3 条转红）
- [x] 2.2b `src/bench/distribution.py`：`resolve_submitter(conn, source, domain_key, *, via, authenticated_as=None)` —— 只负责把登记行与成员事实取来，判断全交给 2.2a；无副作用、不抛
- [x] 2.3 `src/bench/proposals.py`：`submit` 前调 2.2b 并按结论映射错误；`unknown_prefix` / `malformed` / `pipeline_impersonation` 在任何档位都拒绝
- [x] 2.3b `src/web/routes/console.py` 的内部提案端点显式传 `via="in_process"`；外部 `POST /api/d/{key}/proposals` 传 `via="http"`（两处必须分开，`extract:` 的放行只依赖这一个值）
- [x] 2.4 迁移计数要有读面：`GET /api/v1/distribution/legacy-sources`（admin scope），返回去重来源与计数，供翻硬档前判零
- [x] 2.5 `scripts/register_fleet.py`：`--fleet-ref` / `--domains` / `--name`；`--from-observed` 从 `domain_proposals.source` 枚举 `fleet:*` 去重值，dry-run 输出建议映射与计数，`--apply` 才写。三处拒写都实跑验过：无 `--apply` 不写、`--apply` 缺**现有** token 拒绝（不发明凭据）、`fleet_ref` 已有未吊销登记拒绝；空库给「先建库」而不是裸 traceback。`tests/test_register_fleet_script.py` 7 条，两处注入各转红 1 条
- [x] 2.6 单测（DB 侧）：`fleet:` 未登记 403 / 吊销后 403 / 跨域 403；`extract:` 外部 403（伪装）而进程内放行；`agent:` 域不一致 403、非成员 403、域一致放行；宽松档下未知前缀入库且计数 +1、但 `extract:` 外部仍 403；同一舰队重复登记被拒
- [x] 2.6b 路由级测试：**从真实 HTTP 路由**发 `source=extract:...`，断言 403（测路由不测函数——`via` 传错等于没有校验）。四条：`extract:` 外部 403 且**不留半行**、未登记舰队 403、已登记舰队 200 而同一 fleet_ref 在他域 403「域不在绑定范围」（不是「未登记」——错的是域，得指对原因）、冒用他人身份 403 而本人 200。注入验证：把路由的 `via` 改成 `VIA_IN_PROCESS`，`extract:` 那条立刻转红、其余仍绿
- [x] 2.7 排他性测试：两个来源标识不能同时解析到同一条登记（`fleet_ref` 唯一有效档）

## 3. 运行台账分来源与外部回写（`domain-run-ledger`）

- [x] 3.1 `src/bench/agent_runs.py`：`start`/`finish` 增 `origin` 与 `runner_ref`；内核岗位调用点**不改语义**（`origin` 缺省 `kernel`）
- [x] 3.2 `src/bench/agent_runs.py`：新增 `record_external_run(conn, *, runner_ref, role, domain_key, outcome, counts, artifact_refs, remaining=None, detail=None)`——按 `runner_ref` 存在性检查幂等，重复调用返回既有行且不改任何字段
- [x] 3.3 幂等实现必须走存在性检查而非唯一索引（`runner_ref` 允许为空，空值不参与唯一性）；测试用两次同 `runner_ref` 断言行数 1 且字段逐一相等
- [x] 3.4 `src/web/routes/console.py` 的 team 区：台账按 `started_at DESC` 排序、`origin` 只作分列与筛选不参与排序；`domain_console_team.html` 增来源列与外部执行方标识列（`fleet:` 行显示完整 `runner_ref`，内核行显示「—」）
- [x] 3.5b **机器写面补齐**（闭环必需，原任务漏了）：`POST /api/v1/distribution/{domain_key}/work-orders/{id}/claim`、`.../complete`、`POST .../runs`。会话路由把非人档当「不是我的」，所以「等待舰队认领」这句话在只有会话路由的世界里**永远不会发生**——那正是这个 change 要拆的「看着闭合其实没接」。授权读 `assignee_kind`+`assignee_ref`（显示名相同不算），重复认领 409、跨舰队 runner_ref 403、结局出词表 422
- [x] 3.5 `GET /api/d/{domain_key}/runs`（提交方可见的只读回写校验面：按 `runner_ref` 查本次回写是否落库），供 paas 侧自检。实现成**两个入口一条判据**：会话面给域成员（页面本就能看整份台账），机器面 `/api/v1/distribution/{domain_key}/runs` 复用拉取面那枚 `X-Consumer-Token`、只放 `fleet` 种类且只读自己 `fleet:<fleet_ref>/` 前缀的轮次——paas 是机器，只给浏览器入口等于没有这一面。读别人的前缀返回 **403 而不是空列表**（空列表会被读成「我的回写没落库」）。`tests/test_run_readback.py` 11 条，三处注入各转红（去掉前缀判据转红 3 条、把前缀改成子串转红 1 条、去掉 fleet 种类检查转红 1 条）
- [x] 3.6 单测：回写幂等、结局词表外被拒、回写不进入质量比（`domain_quality_metrics` 前后一致）、内核岗位行为零变化（既有 run 相关测试全绿）、team 页两类行同屏

## 4. 提案结局回流

- [x] 4.1 `src/bench/proposals.py`：新增 `list_outcomes(conn, *, source, domain_key=None, limit=...)`，从 `domain_proposals` + `domain_proposal_events` 组装结局行（含驳回理由原文与依据 digest）
- [x] 4.2 路由 `GET /api/d/{domain_key}/proposals/outcomes`：按来源校验（§2.2）后只返回该来源的行；跨来源读取 403
- [x] 4.3 驳回理由必须可取原文：`domain_proposal_events` 里已存的 `reason` 直接投影，MUST NOT 重新生成或摘要化
- [x] 4.4 「换依据才可重提」判据与既有 `canonical_evidence_digest` 对齐：同 key + 同 digest 被拒并报明、换 digest 被收（复用既有测试断言，不新建第二套判定）
- [x] 4.5 单测：提交方读到自己的驳回理由、读不到别家的行、同 digest 拒 / 换 digest 收

## 5. 控制台最小读面

- [x] 5.1 总览页增「谁在跑」卡：最近一轮内核岗位与最近一轮舰队各占一行（来源/岗位/外部执行方/时间/结局），无任一类时**只**给该类空态——合成一句「最近活动」会把「舰队从没动过」说成「有人在跑」
- [x] 5.2 提案箱列表的来源列改为「解析后的来源」：已登记显示舰队名 + 岗位，未登记显示原字符串并标 `legacy` 徽标。实现是 `proposals.describe_sources`（用的是提交闸同一个分类器，页面不会和「今天会不会被接受」说反）
- [x] 5.3 工单在团队区与派单页同时可见（同一数据源，不做第二份查询）：团队区取一次 `authoring_list_tasks`，按三档分组显示未完成数与最近 5 条，并链到工单页
- [x] 5.4 兼容表逐条验证：`/d`、`/d/{key}` 十区、`/estate`、`/workbench/{key}` 全部可达且权限判定不变

## 6. 迁移与上产

- [x] 6.1 `scripts/backfill_assignee_kind.py`：按展示名形状归类存量派单行（只认平台自铸的 `agent:<role>@<domain>` → `kernel-role`、`fleet:<ref>/...` → `fleet`，其余含人名一律留 `human`），`--dry-run` 出三档计数；只改 `assignee_kind`/`assignee_ref`，不改 `assignee` 展示名。已类型化的行一律跳过（哪怕展示名像另一种身份）。**登记在案的局限**：`human` 是列默认值，脚本无法区分「默认」与「刻意的 human」——因此这条判据只对形状可判的行成立，人名行本来就不动。`tests/test_backfill_assignee_kind.py` 7 条，去跳过判据后 2 条转红。本地空/旧库两条路径都实跑过：无列时 EXIT=2 并指明「先跑启动步骤」，跑完 `ensure_schema` 后 EXIT=0
- [ ] 6.2 生产库真身核对：起一次 pod，确认 `ensure_schema` 把六列建齐且存量行取到默认值（判据＝列存在 + 存量行非空默认值）  → **未做**：要等出片后真 pod 起一次
- [ ] 6.3 登记：`register_fleet.py --from-observed` dry-run → 人确认 → `--apply`；翻硬前 `legacy-sources` 计数须为 0  → **脚本已就绪、本地三档都实跑过**（`--from-observed` / `--legacy` / `--apply` 缺 token 时拒写）；**未做**的是对生产那一跑：`--apply` 必须由人给出该舰队**现有** token（脚本拒绝发明凭据——发明即切断正在跑的舰队），且 `--from-observed` 的清单不能直接灌（探针来源 `fleet:credential-probe/post_probe` 也在里面，它不是一个舰队）
- [ ] 6.4 一轮真跑（跨仓，与 paas `add-bench-ops-tools` 联合）：喂一个真缺口 → 派给舰队 → 舰队领单 → 回写运行 → 提交提案 → 域负责人确认 → `knowledge_units` 出现该键；四份证据（工单行、运行行、提案行、单元行）都在  → **离线那半已做**：`tests/test_fleet_loop_e2e.py` 用真 HTTP 走完整闭环、四份证据逐份核对；**待做**的是跨仓那半——paas 侧按同一 HTTP 契约接入（`add-bench-ops-tools`）
- [x] 6.5 回退演练：把校验档切回宽松，确认未登记来源仍入库且计数可读；列保留不影响读。**本地真库实跑**（`law_bench_opscheck`，四步）：① strict 档读出 2 组遗留（`extract:qwen` 3 行无判定、`user:` 1 行错配）；② `BENCH_SUBMITTER_MODE=lenient` 下 `fleet:fleet_unregistered/post_9`（`unregistered`）与 `mirror:legacy-shape`（`unknown_prefix`）**都入库**；③ 计数从 2 组变 4 组、逐组可读；④ 翻回 strict 后**同样两条被拒**（`unregistered` / `unknown_prefix`），宽松期写入的行仍在、`origin`/`runner_ref`/`kind`/`fleet_ref` 四列各 2 个都在

## 7. 验收

- [x] 7.1 浏览器链路 e2e：登录 → `/estate` 派单给舰队 → `/d/{key}` 看到工单 → 团队区看到两类运行 → 提案箱看到解析后的来源与驳回理由。落在 `tests/test_fleet_loop_e2e.py`：**一条测试走完整闭环**（缺口→派单→舰队领单→回写运行→提案入箱→负责人确认→单元落库→缺口消失→对提交方可见→关单），四份证据逐份核对；另有 4 条只测「不该通的那几条路」。三处注入各转红一条，把机器面收窄后闭环测试当场断在领单
- [x] 7.2 判据测试套件：§1.10 / §2.6 / §3.6 / §4.5 全部纳入回归，`pytest` 全绿。新增 11 个测试模块全部入回归：`test_submitter_contract`(36) / `test_fleet_registration`(13) / `test_external_run_writeback`(9) / `test_work_orders`(18) / `test_proposal_outcomes`(11) / `test_register_fleet_script`(7) / `test_run_readback`(11) / `test_backfill_assignee_kind`(7) / `test_fleet_loop_e2e`(5) / 控制台新增 12 条 / 契约文档 6 条
- [x] 7.3 `openspec validate add-fleet-execution-loop --strict` 过绿
- [x] 7.4 写 `acceptance.md`：逐条判据 + 真库/真请求读数。已落 `openspec/changes/add-fleet-execution-loop/acceptance.md`：六节读数（基线 / 四类分流 / 台账 / 工单 / 结局 / 闭环 / 回退演练），每条判据写明「怎么判、读数多少、注入后是否转红」；未做项（6.2 生产列、6.3 生产登记、6.4 跨仓）逐条写明阻塞原因

## 8. 挂账（本 change 不处理）

- [ ] 8.1 知验台直接调度壹座（推任务而非等认领）——本 change 明确不做，若要做另立
- [ ] 8.2 工单的优先级/截止时间/计费——无业务依据，不做
- [ ] 8.3 舰队侧客户端实现与 pack 接线——在 paas `add-bench-ops-tools`
