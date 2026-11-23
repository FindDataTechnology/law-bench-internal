# Acceptance — deepen-industry-lines

> 逐条判据 + 真库读数 + 区分度证据。基线时间 2026-11-23，只读查生产 `law_bench`。
> 三处断点（评测不可归属 / 复测零调用方 / 台账误报缝）各以「改前读数 → 改后读数」对账。

## 0. 基线（改前）

| 读数 | 值 | 来源 |
|---|---|---|
| 生产 `eval_runs` 带 verdict 身份（subject_key 非空）的行 | **0 / 16** | `select count(*) filter (where subject_key is not null)` |
| 生产 `eval_runs` 带域归属（rubric_domain_id 非空）的行 | **7 / 16**（均是 legacy 文本通道；数据通道 0） | 同上 |
| `data_checks.run_data_eval` 生产调用方 | **0** | grep（仅 tests/） |
| `erp` / `finance` 域跑过的数据评测 | **0 / 0** | eval_runs 无对应行 |
| `verdicts.register_retest` 生产调用方 | **0** | grep（仅 tests/） |
| `reconcile` 把 `crosswalk` 报成越界 | erp / legal / finance 均报 | 生产 `ledger.reconcile` 实测 |

## 1. C1 数据评测可归属 + 可跑

判据见 `specs/domain-data-eval/spec.md`。真库读数（改后，生产在役 pod 实测）：

- [x] `finance` 域跑一次数据评测 → run #22 `rubric_domain_id=6(finance)`、`channel='data'`、`outcome=pass`、735/735
- [x] `erp` 域跑一次数据评测 → run #21 `rubric_domain_id=5(erp)`、`channel='data'`、`outcome=pass`、46/46
- [x] 两域 `eval_runs` 的 `last_run` 从「从未 / 陈旧」变为 `2026-11-22T21:05`（域矩阵评测柱更新）
- [x] 空域（`gov`/`legal`/`data-ontology` 无匹配 checker）→ `evaluable_kinds=[]`；页面显示「暂无可评」空态而非「全过」
- [x] 归属探针不毒化事务：pod 内 throwaway DB 验「无 rubrics 表→NULL 不 500」「唯一→回填」

**区分度证据（`criterion-must-fire-on-real-data`）**

- `finance` 7 条 checker 在生产 105 条真金标上 **105/105 全过**。这是**数据本身干净**的事实，
  不是「规则无区分度」——7 条里 6 条是格式/身份不变式（sha256 格式、doc_id 一致、日期可解析…），
  在干净 gold 集上恒真是正确的；它们的作用是未来坏导入时立刻报红。**本 change 不据此伪造区分度**，
  如实记录：finance 线今天证明的是「能被评、能落域」，不是「能挑出坏数据」。
- `erp` 新判据在原型的 4 条里，跨表判据（本端存在、缺 confidence）在真数据上 32/32 或 31/32 全红，
  **无区分度且与既有 `quality.crosswalk_gaps` 重复**——按约束**删除**，只留 2 条无重复的不变式：
  - `account-maps-to-preset`：23/23 account 的 `maps_to` 落在 12 码闭集（未来越界会 FAIL）
  - `account-evidence-anchor`：23/23 account 带 quote+source（未来缺依据会 FAIL）
  这两条无人重复（质量比通道只测 grounding/evidence/crosswalk 覆盖，不测映射目标有效性）。

## 2. C2 复测义务接上调用方

判据见 `specs/domain-retest-loop/spec.md`。真库读数（生产实弹）：

- [x] 确认 pending 提案 #97（`acceptance-20261115-machine-face`）→ `authoring_tasks` 出现 `target_kind='verdict-retest'`、`target_key='knowledge-unit:clause:acceptance-20261115-machine-face@silver'`、`status=pending`；确认前 retests=0，确认后=1
- [x] 确认同时写出单位（`knowledge_units` 出现 `acceptance-20261115-machine-face`、`tier=silver`），且 proposal `state=confirmed`、`decided_by=ops:finddata-80/night-acceptance`
- [ ] 模板升版 → 每个锚定域出现一条 `template:<name>@v<N>` 复测义务（单测 `test_template_promotion_books_retest_per_anchoring_domain` 已覆盖；生产未另立模板升版）
- [x] 域 `eval-runs` 页「待复测项」面板渲染（erp 无义务→明说「没有待复测项」；legal 有 1 条）
- [x] 复测登记抛异常时确认仍成功（单测 `test_confirm_survives_retest_booking_failure`）

## 3. C3 台账不误报内核缝

判据见 `specs/domain-ontology-ledger/spec.md`。真库读数（生产在役 pod 实测）：

- [x] `erp`：`out_of_vocab_kinds=[]`，`seam_kinds=['crosswalk']`
- [x] `legal`：`out_of_vocab_kinds=[]`，`seam_kinds=['crosswalk']`
- [x] `finance`：`seam_kinds=[]`（无 crosswalk），`out_of_vocab_kinds=['fact']`（`fact` 确属词表外的金标 kind，如实报；非缝）
- 说明：`consistent=False` 对 erp/legal 由既有覆盖缺口/模板陈旧造成，**不再由 crosswalk 造成**——这正是要分离的两件事。

## 4. CI

- image.yml（internal Actions，postgres:14 service）：`sha-983aa03`、`sha-425c150` 均 test 绿
- Knowledge Surface Integrity：retrieval-integrity + ontology-conformance 绿
- **e2e 抓到、单测漏掉的 500**：数据评测 POST 路由仍按旧签名调 `evaluable_kinds(domain_key)` → HTTP 500。已修（`425c150`）并补路由级测试 `test_data_eval_button_runs_and_writes_an_attributed_run`。

## 5. ego 真身份走查（`aloadtree@gmail.com`）

- [x] 登录 `lawbench.finddatatech.cloud` → `/d/erp/eval-runs`（会话复用）
- [x] 页面渲染「数据评测」面板：可评 kind=`account` + 按钮「跑一次数据评测」
- [x] 「待复测项」面板渲染，erp 无义务明说「没有待复测项」
- [x] 点按钮 → **不再 500**；flash 显示翻译文本「数据评测完成：通过 46/46 · pass」（`sha-9cc0bd4` 修复后），新 run #24 落库（46/46，22:05:08）
- [x] 截图归档 `/tmp/lawbench-erp-eval-final.png`

> 过程中 e2e 抓到两个只有真浏览器才发现、单测全绿的缺陷：① POST 路由按旧签名调
> `evaluable_kinds` → 500；② flash 用 `console.flash.*`（目录在 `flash.*`）+ `%(x)s`
> printf（translate 用 brace `.format`）→ 渲染原始键。均已修并补路由级断言。

## 6. 出片与滚版

- [x] `sha-983aa03` 进 ccr（digest `de1d1a85`）→ 首滚 prod（含 C1/C2/C3，但按钮 500）
- [x] pod 内实证：`erp` evaluable=[account]、`finance` evaluable=[fact]；C1/C2/C3 生产读数（见上）
- [x] `sha-425c150`（500 修复）→ ccr `1ba68b33` → 滚 prod
- [x] `sha-9cc0bd4`（flash 修复）→ ccr `e96a71c6` → 滚 prod；按钮 e2e 通过（flash 译文 + run #24）
- [x] `scripts/smoke_prod.sh` PASS（13 checks）

## 7. 终态

生产在役 `sha-9cc0bd4`（digest `e96a71c6`）。三条行业线自检：
- `erp`：可评（account），run #21/#23/#24 均 46/46 带域归属
- `finance`：可评（fact），run #22 735/735 带域归属
- `gov`/`legal`/`data-ontology`：如实报无可评确定性判据（诚实空态）
- 复测义务：确认提案即铸 `verdict-retest`，域页可见；台账把 `crosswalk` 单列为内核缝

## 8. 追加：gov 接真实 registry（6.2，用户授权后做）

原 6.2 挂账「gov-fact registry 接生产」。用户 2026-11-23 授权「要做就继续做」后落地：

- `scripts/load_gov_registry.py`（新）：幂等把 `fd-cn-gov` registry（11 源）落成 `gov-fact`
  单位进 `namespace='gov'`（该 pack 的 namespace 已是域 key，无 finance 那种错位）；
  `--dry-run`（不写）/ `--no-eval`（只落不评）；落库后自动跑一次带域归属的数据评测。
- `src/web/routes/console.py`：console 边缘补 import `packs.gov.checks`（否则 app 进程
  gov-fact 无 checker，`evaluable_kinds(gov)` 为空）。
- 区分度（`criterion-must-fire-on-real-data`）：registry 干净 ⇒ 8 checker 11/11 全绿。
  这是**数据本身对**的事实，规则作未来 registry 漂移的警报（非用来挑今天的错）。

**生产实证**（pod 内 `FD_GOV_REPO=/tmp/govrepo python scripts/load_gov_registry.py`）：
- gov namespace：document 45 / issued_by 38 / **gov-fact 11** / agency 4 / concept 3 / defines 3
  （gov-fact 是新增 kind，不动既有本体）
- 数据评测 run #25（脚本）/ #26（页面按钮）均 `data-checks:gov-fact` pass **88/88**、
  `rubric_domain_id=gov`、`channel='data'`
- ego 真身份：`/d/gov/eval-runs` 显示「可评 kind：gov-fact」+ 按钮；点后 flash
  「数据评测完成：通过 88/88 · pass」（截图 /tmp/lawbench-gov-eval.png）

**三维行业线终态**（全部带域归属的数据通道结论）：
- gov：#25/#26 88/88（gov-fact）/ erp：#23/#24 46/46（account）/ finance：#22 735/735（fact）
- legal / data-ontology：如实报无可评确定性判据（诚实空态）

在役镜像：`sha-d7960ac`（digest `fb1339c2`）。
