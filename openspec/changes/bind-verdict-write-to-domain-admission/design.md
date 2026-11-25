# Design

## Context

见 `proposal.md — Why`。实现所依赖的、本轮读码确认过的现状：

```
src/web/routes/distribution.py:556  record_run
  读：runner_ref / role / task_id / counts / artifact_refs / outcome / remaining / detail
  不读：verdict（重读两次确认，0 次）
  同文件 :893 段注释：「no route here creates a verdict … READ-ONLY by construction」

src/bench/submitters.py:178  may_read_runner_ref   ← 前缀隔离判据（三种读者）
src/bench/submitters.py:60   classify_source       ← 四前缀闭集，纯函数
src/bench/agent_ids.py        AGENT_PREFIX / MACHINE_PREFIXES = {agent, fleet, extract}
                              tests/test_agent_ids.py 钉住两者词表一致

src/bench/workspaces.py
  ROLES = (annotator, expert, lead)  ROLE_RANK 0/1/2
  add_member(): 机器身份上限 expert（2026-11-21 真被越权用过一次才补）
  instantiate_domain(): ≤ hard_stops.check(actor, "open_or_archive_domain")
  get_active_role(domain_id, user_id) ← 域角色的唯一真源

src/bench/domain_rubrics.py
  effective_rubrics(domain_path) 就近者胜，行保留 domain_id，origin=own|inherited
  fork(): fork_diff 必填（「silent copy is indistinguishable from parent」）
  create_for_domain(): (domain_id, name) 唯一（libraries.py 建的 rubrics_domain_name_uk）

src/eval/db.py:216  is_harbor(source) → 模板标准只读（rubric_crud._assert_local 403）
src/bench/hard_stops.py  machine actor 不得 open/archive domain

src/bench/distribution.py
  CONSUMER_KINDS = ("machine", "fleet")
  register_consumer(kind=…) 校验闭集
  consumers 行：名称 / domains[] / kind / fleet_ref / token_hash
```

关键事实：**模板层、域层、角色层三套判据都已存在且各自都有测试**。本 change 不新建治理，只把三套判据**接到结论写面上**，并把「谁在这个域里」收敛成一个答案。

## Goals / Non-Goals

**Goals**
- 外部进程（fleet / 域成员）能**且只能**写一条它能复现、且归属正确的结论。
- 「同类定义域」有一个表达（模板版本锚定），「加入」有一个抽象动作，不再三处各判一次。
- 任何主体都改不了已写结论；改自己的标准只影响此后的判定。

**Non-Goals**
- 不重写 `domain_members` / `consumers` 的表结构（存量零迁移）。
- 不引入「个人级」第四层标准（用户明确：同类域是单位，域内用角色分权）。
- 不做「按内容自动选标准/选域」——猜错域/猜错标准是最难发现的一类错误。
- 不改 `proposals` 会话面与历史提案行。

## Decisions

### D1. 写路由与 `record_run` 同族、同令牌、同三态鉴权，不新开凭据面

复用 `_fleet_consumer(request, db, domain_key)` 与 `X-Consumer-Token` 三态（401/403 吊销/403 域不在范围）。**替代方案**：给人另开 Logto 面。否决——人面已有会话路由，机器面与它混会让「谁写的」这件事又要靠一个字段猜。

### D2. 三道门，逐门可分辨拒绝理由

```
① 身份门    classify_source(提交方) → 必须等于凭据派生的主体
            （复用 submitters 纯函数，不新写前缀判断）
② 尺子门    effective_rubrics(subject 域的 path) 里能找到该 ruler
            不可见 → 422，报明「尺子不可见」
③ 层级门    ruler 所属域为模板层(harbor/extends 根) → 任何已登记写者
            ruler 所属域为域层 → 写者须在该域 ≥ expert
            机器主体上限 expert（沿 add_member 既有规则）
            改写既有结论 → 无路径（见 D4）
```

**为什么不把三合一成 401/403**：三种拒绝的处置方向相反（换凭据 / 补登记域 / 换尺子 / 找负责人），合成一个码就是把修复线索扔掉。依据：`submitters.py` 开头 2026-11-14 事故——**闸只按调用方自拼字符串判**，于是冒充通过。

### D3. 「同类域」用模板锚定表达，不新增类型枚举

`domains` 行早已带 `template_id` / `template_version`，`inheritance.ancestors()` 已给继承链。**替代方案**：加 `domain_kind` 列。否决——第二个口径与模板继承必然漂移，而 `effective_rubrics` 的就近者胜已经按链算。

### D4. 结论只追加：写面没有 UPDATE，靠机制而非纪律

- `eval_runs` 插入即终态；同一条结论再次提交不同内容 → 拒（内容指纹比对，与 `agent-run-store` 同款做法）；
- 材料快照沿用既有：`store_result` 已把 rubric/contract/task_desc 以 TEXT 快照，删改原件不使历史结论失效；
- **读面永不重新校验可见性**（spec 已写死）：历史是事实。

### D5. 接纳抽象 = 一个读面 + 一个写入口，背后两张表

```
admitPrincipal({domain, kind, ref, role})     listPrincipals(domain, role?) → [{kind, ref, role}]
        │                                               │
        ├ kind=user|agent → domain_members  (role 校验: ROLES 闭集 + 机器≤expert)
        └ kind=fleet      → consumers.domains[] (role 恒 null)
```

不建新表。`kind` 是读面 UNION 的列。`ops:` **不纳入成员**（`agent_ids.MACHINE_PREFIXES` 把它单列：运维裁决不是成员；开域已是硬停动作）。

### D6. `domain_members.user_id` 装 `agent:` 前缀 → 保持现状，不拆列

今天 agent 身份就是"user_id 里装一个前缀字符串"。**替代方案**：拆成 `(kind, ref)` 两列。否决——存量迁移 + 所有读点改，收益只是消除一次字符串判断，而 `classify_source` / `is_agent` 已把它集中在一处并有测试钉住。接纳抽象在**读写界面**呈现 `kind` 即可。

## Risks / Trade-offs

- **[写路由是新信任边界入口]** → 三道门与写路由同一批交付，tasks 里显式列为不可拆分的一节；负向用例必须比正向多。
- **[尺子门做成硬拒会挡住「尺子后来被删」的重放]** → 只校验新写入；读面永不校验（D4）。tasks 有专项用例。
- **[改 `runner_ref` 派生会与 paas 幂等键对齐]** → 两边同一公式，paas 的 tasks 3.1 与本 design 共用；联调用例放在 paas 仓（companion 侧提供对端样例）。
- **[`(domain_id, name)` 唯一约束使「同名不同层」不可共存]** → 这正是 `effective_rubrics` 就近者胜的设计（同名即同一标准的一次覆盖）。本 change 不改。

## Migration Plan

1. Postgres additive：`eval_runs.ruling_domain_path TEXT`、`eval_runs.ruler_derived_from BIGINT`（无回填）。
2. 上线写路由；保持 `record_run` 行为不变（只加结论段）。
3. 上线 `admitPrincipal` / `listPrincipals`（只读面先上，写入口后上）。
4. 观察：paas 侧 `verdict_state=dropped` 应随本面上线趋零。

**回滚**：写路由可下线，两列 nullable 无 down-migration；读面变更向后兼容。

## Open Questions

- **尺子门的判定口径**：`effective_rubrics` 按被评**主体**所在域算，还是按写者所在域算？本 design 取前者（「这把尺子在这个域是否可见」），因为结论的归属域是主体域（`domain_agent_runs.domain_key`）。若实际需要「按写者域」，companion 联调时再定，不阻塞。
- ~~**`ruler_derived_from` 的写入方**~~ —— **已定（2026-11-25 取证，task 1.1）**：反查**不可行**。
  `ruler_digest_of(payload)` → `distribution.canonical_digest(manifest)`，它算的是**发布
  manifest**的 digest，不是单把 rubric 行的。库里没有「rubric 行 → digest」的正向映射，
  按 digest 反查需要先对每把尺子重建 manifest 再逐个算——那是 O(n) 且依赖发布时的
  组装口径，不该放在写路径上。
  **因此 `ruler_derived_from` 由客户端传**（task 1.4 的分支），并在 `verdict_problem()`
  里与尺子三件套做整组校验：给了 `ruler_derived_from` 就必须同时给
  `ruling_domain_path` 与尺子三件套，且 `ruler_derived_from` 必须指向本域可见的 rubric 行。
  伪造血统的成本高于留空，所以宁可不填也不猜。
