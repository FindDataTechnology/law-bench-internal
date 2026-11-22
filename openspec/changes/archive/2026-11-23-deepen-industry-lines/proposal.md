## Why

知验台的**行业线资产齐、闭环断**。生产库实测（2026-11-23，只读，`law_bench`）：

| 域 | 已建内容 | 尺子 | 真跑过的评测 | 复测义务 |
|---|---|---|---|---|
| `legal` | 5,386 clause + 92 law + 42 concept | 88 | 16 条全 legacy（合同文本通道；其中 7 条有域归属、0 条带 verdict 身份、0 条数据通道） | 无 |
| `gov` | 45 document + 4 agency + 3 concept | 1（`gov-document-quality`） | 1（104/104，11-10） | 无 |
| `erp` | 23 account + 31 crosswalk + 8 org | 1（`erp-ontology-consistency`，8 判据） | **0** | 无 |
| `finance` | 105 fact（gold） | 1（`finance-fact-quality`，8 判据） | **0** | 无 |

四个行业域里，**三个的尺子从没对生产单位跑过**。根因不是「没写评测」，是三处断点：

1. **数据通道的评测无法归属**。`src/bench/data_checks.py::run_data_eval` 会写一条
   `channel='data'` 的 `eval_runs`，但 `store_result` 从不填 `rubric_domain_id`
   ——而 `estate._pillar_eval` 与 `domain_rubrics.runs_for_domain` 全靠
   `rubric_domain_id` 命中域。结果：一次成功的数据评测在域矩阵里**看不见**，
   读出来是「这个域从没被评过」。而且 `run_data_eval` **零生产调用方**（只有测试）。
2. **行业尺子没有可执行的判据**。`erp` 的 `erp-ontology-consistency` 8 条判据是
   seed 进去的文本，`packs/erp` **不存在**，`register_checker` 从没被叫过，所以
   `data_checks.checkers_for('account')` / `('crosswalk')` 恒为空——尺子存在却无法跑。
   `gov` 有 `packs/gov/checks.py` 但 `packs/gov/__init__.py` 只导 `entity_keys`，
   不导 `checks`，所以 `gov-fact` 的 checker 同样空。`finance` 能跑，但 7 条 checker
   在 105 条真金标上 **105/105 全过**——不区分任何东西（`criterion-must-fire-on-real-data`
   明确：全绿的规则没有证据力）。
3. **复测闭环零调用方**。`verdicts.register_retest` 与 `find_open_retest` 写了、
   测了（`test_verdict_run_interlink.py`），但**没有任何生产路径调用它们**：确认提案
   产出 `silver` 之后不复测，模板升版之后不复测。改完了永远不知道有没有用。

另有一处**本体噪音**制造假缺口：`crosswalk` 是内核自己的缝（`proposals.CROSSWALK_KIND`），
不属于任何域的 `entity_types`，于是 `ledger.reconcile` 在 `erp`/`legal`/`finance`
每个域都把它报成 `out_of_vocabulary`——那是把一个**正常的、内核产的** kind 当成异常，
值班的人会去找一条不存在的错。

为什么现在做：行业类别深化不是「再加一个模板」，是让**已有的四个行业域真正能被评测、
被复测、被诚实计数**。没有 C1 的归属，任何行业评测都不可见；没有 C2 的复测，任何
自我迭代都不闭环；没有 C3 的清理，本体台账把正常状态报成异常。三件事是同一套闭环
的三段，缺一段其余两段都白做。

## What Changes

**C1 — 行业数据评测可跑、可归属、可区分（`domain-data-eval`）**

- `store_result` 增 `rubric_name` → `rubric_domain_id` 归属：写入时按生效尺子的
  归属域回填，使数据通道评测在域矩阵里**可见**（沿用 `domain_rubrics.effective_rubrics`
  的唯一口径，不另写映射）。
- 新增 `src/bench/data_eval.py::run_domain_data_eval(conn, domain_key, kind=None)`：
  对某域**活跃单位**跑该 kind 的 checker，落一条**带域归属 + 带 verdict 身份**的
  数据结论。它是 `run_data_eval` 之上的薄封装，复用全部既有逻辑。
- 补 **ERP 的可执行判据**（`packs/erp/`）：把 seed 文本里的 8 条判据中**可由单位
  自身确定性判定**的几类落地为 checker——映射目标在通用科目闭集、映射本端存在、
  映射不冒充已复核（缺 confidence）、科目有 evidence 锚点。**实测这些在真数据上会
  FAIL 一部分**（31 条 crosswalk 全部缺 confidence ⇒ 6 条 restaurant/supply 的映射
  会被「本端存在」判过、但「不冒充已复核」会 FAIL），从而有区分度，不是全绿。
- 修 `packs/gov/__init__.py` 让 `checks` 随风导入即注册（`gov-fact` 的 checker 复活）。
- 域 `eval-runs` 页增一个「跑一次数据评测」动作（`lead` 闸 + `content:write`），
  跑完 flash 出「通过 N / 共 M」；结果立刻落到同页的运行列表。

**C2 — 确认与升版之后的复测义务（`domain-retest-loop`）**

- `proposals.confirm` 成功写出一条单位后，调用 `verdicts.register_retest`
  （subject = 该单位，基线 = 该域最近一条数据/文本结论，无则「立基线」）。**失败不得
  回滚确认**（沿既有纪律：复测是登记义务，不是断言）。
- 模板升版（`template_readiness.promote_template_via_gate` 成功分支）登记一条
  「模板 @新版本」复测义务。
- 域 `eval-runs` 页显示**未结复测义务**（标题 + 目标版本 + 基线 id），并把它作为
  一条「下一动作」候选的来源（不新建 `next_actions` 模块，直接在该区渲染一条）。

**C3 — 本体台账里把内核缝单列（`ontology-ledger-seam`）**

- `ledger.reconcile` 把**内核保留 kind**（`crosswalk`，及未来同类缝）从
  `out_of_vocab_kinds` 里分出，单列 `seam_kinds`，并断言它们 `consistent=True`
  ——它们是内核约束下的正常内容，不是异常。`unused_kinds` 与真正越界的 kind
  仍如实报。

## Capabilities

### New Capabilities

- `domain-data-eval`: 行业数据评测——按域对活跃单位跑确定性 checker，结论带域归属与
  verdict 身份，在域矩阵与运行列表可见；覆盖 ERP（新判据）、gov（复活）、finance（既有）。
- `domain-retest-loop`: 确认与升版之后的复测义务登记与展示——义务被登记、可读、
  不被静默丢弃；不自动执行（评测有成本）。

### Modified Capabilities

- `eval-verdict-ledger`: 「晋升与发版后强制复测」从**有此机制**补到**真的有人调用**；
  且数据通道结论必须填 `rubric_domain_id`（否则域作用域读不到）。
- `domain-ontology-ledger`：`reconcile` 把内核保留 kind（缝）与真正越界 kind 分开报。

## Impact

**代码（law-bench-internal）**

- `src/eval/store.py`：`store_result` 增可选 `rubric_domain_id` 回填（按 `rubric_name`
  查生效归属域），不动既有列、不影响无域归属的 legacy 行。
- `src/bench/data_eval.py`（新）：`run_domain_data_eval`。
- `src/bench/data_checks.py`：`run_data_eval` 透传 `rubric_domain_id`。
- `packs/erp/`（新）：`checks.py` + `__init__.py` + `pack.yaml`（kinds=[account, crosswalk]，
  eval_suites=[erp-ontology-consistency]）。
- `packs/gov/__init__.py`：补 `from packs.gov import checks`。
- `src/bench/proposals.py`：`confirm` 尾部登记复测（fail-open）。
- `src/bench/template_readiness.py`：`promote_template_via_gate` 成功分支登记复测（fail-open）。
- `src/bench/ledger.py`：`reconcile` 增 `seam_kinds`。
- `src/web/routes/console.py` + `domain_console_bench.html`：数据评测触发 + 未结复测展示。
- `src/web/i18n.py`：新增键 zh/en 成对。

**数据（生产）**

- 不新建表：复测义务用既有 `authoring_tasks`（`target_kind='verdict-retest'`）。
- 一次生产验收：对 `finance` / `gov` / `erp` 各跑一次 `run_domain_data_eval`，
  取证「有 FAIL 也有 PASS」（区分度），并把结论的 `rubric_domain_id` 落到对应域。

**测试**

- 新 `tests/test_data_eval_domain.py`：域归属回填、按域跑出结论、空域报 inconclusive、
  纯读边界。
- 新 `tests/test_erp_checks.py`：每条 checker 一条真样例、一条反例（区分度铁证）。
- 新 `tests/test_retest_wiring.py`：确认后出现复测义务、升版后出现、失败不回滚。
- 补 `tests/test_domain_ledger.py`：`seam_kinds` 单列、不误报、真正越界仍报。

**风险**

- `store_result` 是全仓评测写入口；加归属回填必须**只在能唯一解析归属域时**写入，
  解析不到就留 NULL（沿 attribute_run 的「nullable on purpose」纪律），否则会给
  无来源的 legacy 结论伪造 provenance。
- ERP checker 必须**先证明在真库上有区分度**才能上（见约束
  `criterion-must-fire-on-real-data`）；全绿的 checker 删掉，不留。
