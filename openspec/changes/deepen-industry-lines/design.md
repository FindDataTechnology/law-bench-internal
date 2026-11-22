## Context

见 `proposal.md` — Why。设计相关的现状（全部实测，2026-11-23）：

- **评测身份列已存在**（`eval_runs.subject_kind/subject_key/subject_version/ruler_*/gate/outcome`），
  `data_checks.run_data_eval` 早就填了这些（`subject_kind='knowledge-units'`、`gate='regression'`、
  `outcome` 三态）。所以 C1 **不新建身份机制**，只补一条缺列：`rubric_domain_id`。
- **域可见性的唯一口径**是 `domain_rubrics.effective_rubrics(domain_path)` 与
  `estate._pillar_eval` 的 `rubric_domain_id` join。数据通道结论没填这一列 ⇒ 域矩阵读不到。
- **复测义务已在既有工单机制上**：`verdicts.register_retest` 写 `authoring_tasks`
  （`target_kind='verdict-retest'`），`find_open_retest`/`baseline_for_retest` 读回。
  C2 只补**调用方**，不新建表、不新建机制。
- **checker 注册是导入副作用**：`packs/<x>/checks.py` 在 import 时调
  `data_checks.register_checker`。`packs/gov/checks.py` 写好了但 `__init__` 没导它，
  `packs/erp/` 整个不存在。
- **内核域无涉闸**（`tests/test_kernel_domain_free.py`）禁用一批域词（`合同`,`法条`,…）在
  `src/bench`：所以 ERP 判据只能进 `packs/erp`，不能进 `src/bench`。

## Goals / Non-Goals

**Goals**

- 数据通道结论**落到域**，域矩阵的「评测」柱能看到它。
- 至少两条行业线（erp / gov）的尺子**能跑**，且**在真数据上有区分度**（既有 FAIL 也有 PASS）。
- 确认与升版**登记复测义务**，在域页可见，不被静默丢弃。
- 本体台账不再把内核缝 `crosswalk` 报成越界。

**Non-Goals**

- 不自动执行复测（评测有成本，何时跑由人/调度决定——沿 `register_retest` 既有纪律）。
- 不做 `next_actions` 全量投影（那是 `add-domain-next-actions` 的范围，本 change 只在该区
  渲染一条复测候选，不建 `src/bench/next_actions.py`）。
- 不给 `finance` 造新判据：它 7 条 checker 全绿是**数据本身干净**的事实，不是缺陷；
  本 change 只把它跑起来并落域归属，不伪造区分度。
- 不动 legal 的合同文本通道。

## Decisions

**D1 — `store_result` 加 `rubric_domain_id` 回填，只在唯一解析时写。**

`store_result(rubric="data-checks:fact", ...)` 多一个可选入参；未传时按 `rubric_name`
查 `rubrics` 表里**唯一**归属非空的域。两处以上或零处 ⇒ 留 NULL。理由：`attribute_run`
的「nullable on purpose」纪律——伪造 provenance 比缺失更糟。`data_checks.run_data_eval`
把解析到的域 id 透传。为什么不在 `run_domain_data_eval` 里单独 UPDATE：那会制造第二个
写归属的入口，与 `store_result` 双写必漂移；一处收口（D3 一致）。

**D2 — 按域跑评测 = 对活跃单位跑该 kind 的 checker，复用 `run_data_eval`。**

`run_domain_data_eval(conn, domain_key, kind=None)`：解析域 → 枚举本域 namespace 下
**活跃**（`tags->>'deleted'` 为空）该 kind（或全部 pack 声明的 kind）的单位 → 调
`run_data_eval(units=...)`。空集 ⇒ `outcome='inconclusive'`（`run_data_eval` 已如此），
不冒充 pass。为什么不是新写一个 runner：`run_data_eval` 的聚合、身份、三态已经是对的，
新写只会让两处对「一次数据评测」定义漂移。

**D3 — ERP 判据取「可由单位自身确定性判定」的四条，先在真库证明区分度。**

`erp-ontology-consistency` seed 里的 8 条，能由单个 unit 判定的：
1. `映射目标在通用科目闭集内`：`account.attrs.maps_to ∈ universal-accounts`（12 码）。
2. `映射本端存在`：`crosswalk` 近端键在本域活单位里（或待确认提案）。
3. `映射不冒充已复核`：`crosswalk.attrs.confidence` 缺失即 FAIL（这条在 31 条真 crosswalk
   上**全部缺 confidence** ⇒ 必然有 FAIL，即有区分度）。
4. `科目有 evidence 锚点`：`account.attrs.evidence` 存在。
其余四条（账务事实只在内核 / 回写只出 proposal / 回写科目白名单 / 外部接通三态）需要跨表
或跨系统证据，单 unit 判不了，**如实不进 checker**（checker 只在单 unit 上跑），
留作读面判据（rubric 文本仍在，不由本通道自证）。这与 `erp` seed 脚本注释里「前七条机器
可跑、第八条是前提不可自证」同一纪律。

为什么是这四条：它们全部读 unit 自带的 `attrs`，不需要网络、不需要跨表联查——
符合 `data_checks`「checker 是纯 callable、收到 unit dict」的契约。且第 3 条在真数据上
**确定会 FAIL**，满足「必须先证明有区分度」。

**D4 — gov checker 复活 = 改一行 import。**

`packs/gov/__init__.py` 增 `from packs.gov import checks  # noqa: F401`。`checks.py` 已写好
（8 条 registry 对账判据），只是从未被导入。这是最小改动，且它的数据源是 sibling 仓
`fd-cn-gov` 的 registry，与生产 `gov` namespace 的 `document` 单位**不是同一批**
——所以 gov 的 `gov-fact` checker 生产上会因「找不到 registry 单位」而 inconclusive，
这正是 honest 的：gov 线今天建的是 document 本体，不是 registry 事实。
（读面诚实即可，不强行造 gov-fact 单位。）

**D5 — 复测义务 fail-open 登记。**

`proposals.confirm` 与 `promote_template_via_gate` 成功分支之后，try/except 调
`register_retest`；异常吞掉并记一条日志，**不回滚主操作**。理由：`register_retest`
自己的 docstring 已写明「changed 之后登记，失败不得 unwind 晋升」。

**D6 — seam kind 单列。**

`ledger.reconcile` 增 `seam_kinds = sorted(k for k in out_of_vocab if k in SEAM_KINDS)`，
`SEAM_KINDS = frozenset({proposals.CROSSWALK_KIND})`。`out_of_vocab_kinds` 扣掉 seam 后
再报。`consistent` 判定用扣后的集合——seam 不破坏一致性。`summary_key` 只在扣后有越界时
才 gaps。为什么 seam 是「内核保留」而非域词：`crosswalk` 由 `proposals._write_through_kernel`
写入，与模板 `entity_types` 无关，任何域都可能有；这是内核缝，不是某域缺一个类型。

## Risks / Trade-offs

- **`store_result` 归属回填影响全仓写路径**：只在 `rubric_name` 唯一命中一个非空
  `rubric.domain_id` 时写；否则 NULL。单测覆盖「零命中 / 多命中都不写」。
- **ERP checker 若在真库全绿**：按约束删掉该条，不留全绿规则。开工第一步就是真库实测。
- **gov checker 生产 inconclusive**：如实报，不补假单位。

## Migration

无表结构变更（复测用既有 `authoring_tasks`；归属复用既有 `eval_runs.rubric_domain_id`）。
存量 `eval_runs` 不回填（历史行没有域来源，回填就是伪造）。

## Open Questions

无（三项裁决已定，见 D1–D6）。
