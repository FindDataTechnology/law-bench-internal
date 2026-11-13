# 验收读数：add-fleet-execution-loop

> 本文件只记**读数**，不重复需求文字。每条判据写「怎么判的、真读数是多少、注入后是否
> 转红」。凡是没有真读数的，明确写「未做」及其阻塞原因——不留「应该没问题」。
>
> 采集日期：2026-11-14。库：本地 PG 17.11 `:5432`（`law_bench` 走逐测试临时库，
> `law_bench_opscheck` 用于脚本实跑）。生产库只做过只读基线查询（§0.1）。

## 一、基线（只读，2026-11-13 生产 `law_bench`）

| 项 | 读数 |
|---|---|
| `domain_proposals` | 93 行 |
| ├ `extract:*` | 78 |
| ├ `fleet:*` | 12（含 1 条 `fleet:credential-probe/post_probe` 探针） |
| └ `agent:*` | 4 |
| `authoring_tasks` | 1 行（`agent:concept@legal`） |
| `domain_agent_runs` | 17 行，无 `origin`/`runner_ref` 列 |
| `distribution_consumers` | 2 行（`fd-wire`、`ontology-fleet-win`，均绑 legal） |
| `domains` | 4 |

这条基线推翻了初稿「source 必须解析到一条已登记消费者」的假设（78 条提取产物会被全部
拒掉，而它们正是最大生产者），校验因此改为按前缀四类分流。

## 二、判据与读数

### 1. 提交方四类分流（§2）

| 判据 | 怎么判 | 读数 / 注入 |
|---|---|---|
| 九类结论穷举 | `tests/test_submitter_contract.py`（零 DB 依赖纯函数） | 36 条通过；把 `extract:` 在 HTTP 档放行后 **3 条转红** |
| `fleet:` 需登记 + 绑域 + 未吊销 | `tests/test_fleet_registration.py` 13 条 | 全绿；重复登记被拒并点名既有登记 |
| `extract:` 外部一律拒 | 函数级 36 条 + **路由级** `test_http_call_cannot_claim_an_extract_source` | 403 且**不留半行**；把路由 `via` 改成 `VIA_IN_PROCESS` 后该条转红、其余仍绿 |
| `agent:` / `user:` 只能是自己 | 路由级 2 条 | 冒用 403「只能以自己的身份提交」；本人 200 |
| 已登记舰队跨域 | 路由级 | 403「域不在绑定范围」（**不是**「未登记」——错的是域，得指对原因） |
| 判定落库 | `domain_proposals.submitter_verdict` | `ok` 落在行上；`list_outcomes`/legacy 计数都读这一列 |

### 2. 运行台账分来源（§3）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 内核 = `kernel`、舰队 = `fleet` | `tests/test_external_run_writeback.py` 9 条 | `start()` 产 `origin=kernel`/`runner_ref=NULL`；`record_external_run` 产 `origin=fleet` |
| 幂等靠存在性检查 | 同 `runner_ref` 两次 | 行数 1；第二次 `created=False` 且结局/计数**未被改写**（`ok`/3 未被 `failed`/99 覆盖） |
| 结局出词表被拒 | 同上 | `running` / `done` / `""` 均 `ValueError`，不落行 |
| 回写不进质量比 | `quality.all_metrics` 前后对比 | 完全相等 |
| 两类同屏可辨 | `test_team_ledger_separates_the_two_origins` | 表头「外部执行方」在、`fleet:fleet_a/post_1#1` 完整显示；去掉两列表头后该条转红 |
| 回执可读回 | `tests/test_run_readback.py` 11 条 | 自己 1 行；别人的前缀 **403 而非空列表**；machine 档 403；吊销 403 |
| 回执隔离判据 | 三处注入 | 去掉前缀判据转红 3 条、前缀改子串转红 1 条、去掉 fleet 种类检查转红 1 条 |
| 写面入参校验 | `test_fleet_loop_e2e.py` | `role` 为空 422「role 不能为空」；`task_id` 指到别域的工单 404；`counts` 非对象 / `artifact_refs` 非数组 422；**写坏的 JSON 422 而不是当空体**（当空体会让舰队以为 note 记上了）。关单空体仍合法（200） |

### 3. 工单三档（§1）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 三档正例 / 词表外被拒 / 未登记舰队被拒 / 跨域被拒 | `tests/test_work_orders.py` 18 条 | 全绿 |
| 认领排他 | 同一工单连续三次认领 | 一胜两负（`TaskAlreadyClaimed`），`transitions` 里只留一条认领记录 |
| 完成不写知识单元 | 前后 `knowledge_units` 行数 | 相等 |
| 归人缺口不派智能体 | `test_review_backlog_is_never_dispatched_to_an_agent` | `route=human`，`authoring_tasks` 零新增 |
| 归属表同源 | `team_roles.GAP_OWNER == {gap: kernel_role_for(gap)}` | 相等，且 `quality:review_lag → None` |
| 界面三档后果分开 | 工单页每行一句 | 「内核岗位下一轮执行」/「等待舰队认领」/「由人处理」三条都在；删掉那一行后转红 |
| 归人缺口界面不可选智能体 | 派单页 | 只有人这一档，页面无 `value="fleet"` / `value="kernel-role"` |
| 舰队下拉只列绑本域的 | 派单页 | `bound-fleet` 在、`other-fleet` 不在；去掉过滤后转红 |

### 4. 提案结局回流（§4）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 提交方读到自己被驳回的理由 | `tests/test_proposal_outcomes.py` 11 条 | `state=rejected`、`decision_note` 是**原文**「依据无法回源」 |
| 读不到别家的 | 同上 + 路由级 | 换来源 → 空；路由级 403「只能读取自己来源的结局」 |
| 同 digest 拒 / 换 digest 收 | 复用既有判据 | 不变 |
| 迁移计数 | `GET /api/v1/distribution/legacy-sources` | 仅平台管理员（非管理员 403）；`mode` 与实际档位一致 |

### 5. 闭环（§6.4 离线那半 / §7.1）

`tests/test_fleet_loop_e2e.py`：**一条测试全走真实 HTTP**，不调内核函数（除造世界）：

```
缺口存在 → 派单给舰队(303) → 舰队领单(200, in_progress)
        → 重复领单(409) → 回写运行(created=true) → 重放(created=false, 结局未被改写)
        → 回执读回(count=1) → 提案入箱(200) → 负责人确认(303, 无 err)
        → knowledge_units 出现该键(1 行) → 缺口消失 → 结局可见(confirmed) → 关单(done)
        → 四份证据齐（done 工单 1 / runner_ref 运行 1 / confirmed 提案 1）
```

四个只测「不该通的路」：别的舰队领单 403、`machine` 档消费者 403、跨舰队 `runner_ref`
403、结局出词表 422 且零行。

注入（各转红一条）：去掉工单归属校验 → 跨舰队那条红；去掉 `runner_ref` 归属 → 跨舰队
回写那条红；把机器面收窄成只放 `machine` 档 → **整条闭环当场断在领单**。

> 这一处是本 change 唯一「原任务漏了」的地方：会话路由把非人档当「不是我的」，所以
> 「等待舰队认领」这句话在只有会话路由的世界里**永远不会发生**。补齐三个机器写面
> （claim / complete / runs）之后，闭环才真的闭。
> 闭环里还有一个必须分开的身份：提交用舰队侧服务身份（`svc-fleet`, expert），复核用
> 域负责人（`lara`, lead）。两个人时自提自确认闸放行；同一个人时被拦（实测 `err=1`
> 「提案人不得自提自确认」）——这条不是障碍，是判据。

### 6. 回退演练（§6.5，本地真库四步）

| 步 | 命令 | 读数 |
|---|---|---|
| ① strict 下看遗留 | `register_fleet.py --legacy` | `enforcement mode: strict`；2 组：`extract:qwen:2025-10` 3 行（**无判定**）、`user:someone@example.com` 1 行（`user_mismatch`） |
| ② 切宽松 | `BENCH_SUBMITTER_MODE=lenient` 提交两条 | `fleet:fleet_unregistered/post_9`、`mirror:legacy-shape` **都入库** |
| ③ 计数可读 | 同 ① | 4 组：多出 `unregistered` 1 行、`unknown_prefix` 1 行 |
| ④ 翻回 strict | 再提交同样两条 | 两条都被拒（`unregistered` / `unknown_prefix`）；宽松期写入的 2 行仍在，`origin`/`runner_ref`/`kind`/`fleet_ref` 四列都在 |

同时验证了另一条真实的升级形态：本地 `law_bench` 停在**变更前**的库结构，脚本给出
`UndefinedColumn` → EXIT=2 并提示「先跑启动步骤把列建出来」；`ensure_schema` 之后
EXIT=0 并报 `tasks: 0`。

## 三、全量回归与两条非本 change 的失败

`database_url=law_bench .venv/bin/python -m pytest tests/ -q` 首次 **2105 passed / 59 skipped / 2 failed**（12:29）；
定性并处置后（下面两条），排除环境性的那一条再跑一次：
**2106 passed, 59 skipped, 1 deselected, 0 failed**（5:04）。

| 失败 | 定性 | 依据 |
|---|---|---|
| `test_contract_artifact_storage.py::test_generate_stored_real_minio` | **环境**：本机没有 MinIO | `nc -z 127.0.0.1 9000` → closed；单独跑该测试挂到 180s 超时（EXIT=124）。测试自身写着「unreachable 就 skip」，但客户端没有超时设置，所以是挂死而不是跳过。未碰任何 storage 代码 |
| `test_dispatch.py::test_closing_a_task_reopens_the_gap_for_dispatch` | **本 change 的契约变更**，已改测试 | 它从 `pending` 直接 `to=done`；§1.4/§1.10 明确「完成必须先认领」。改成 claim→complete，并把「未认领直接完成被拒」也钉在该测试里。改后 10 条全绿 |

## 四、未做项与阻塞
| 项 | 状态 | 阻塞 |
|---|---|---|
| §6.2 生产库真身核对（六列在真 pod 上就位） | **未做** | 要等出片后有 pod 起一次 |
| §6.3 生产登记（`--from-observed` → 人确认 → `--apply`） | **未做** | 需要该舰队**现有** token；脚本拒绝发明凭据（发明＝切断正在跑的舰队） |
| §6.4 跨仓真跑 | **离线那半已做**（见上） | 需 paas 侧按同一 HTTP 契约接入（`add-bench-ops-tools`） |
| §8.1–8.3 | 明确不做 | 直接调度 / 优先级计费 / 舰队侧客户端，均超出本 change |

## 五、这一轮最该记住的三条

1. **「看起来闭合」的闭环最容易骗人**：数据面区分了来源，界面还合着说；会话路由拒绝
   了非人档，却没有任何机器入口能让舰队自己认领。两处都不是报错，都是静默。
2. **裸中文串不能证明页面渲染了它**：`base.html` 嵌着整份 `window.__LOCALE__`。判据
   必须先剥掉那段脚本（`_rendered()`），否则注入不转红也看不出区别——我自己先写错过
   一次，是注入没红才发现的。
3. **同一句话对不同档不能说**：「已派出」对内核岗位是真的（下一轮就跑），对舰队是假
   的（要等它认领）。文案级的错误会让值班的人催错对象、或者不催。
