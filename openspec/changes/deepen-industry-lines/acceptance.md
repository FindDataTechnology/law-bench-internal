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
- [~] 点按钮跑一次 → **首次暴露 500**（见 §4）；修复后重滚再点（见 §6）
- [ ] 截图归档（修复后补）

## 6. 出片与滚版

- [x] `sha-983aa03` 进 ccr（skopeo digest `de1d1a85` 与 hkccr 一致）→ 滚 prod，digest 在役
- [x] pod 内实证：`erp` evaluable=[account]、`finance` evaluable=[fact]；C1/C2/C3 生产读数（见上）
- [ ] `sha-425c150`（500 修复）出片 → ccr → 重滚 → 按钮 e2e 通过 + 截图
