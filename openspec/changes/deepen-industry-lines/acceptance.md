# Acceptance — deepen-industry-lines

> 逐条判据 + 真库读数 + 区分度证据。基线时间 2026-11-23，只读查生产 `law_bench`。
> 三处断点（评测不可归属 / 复测零调用方 / 台账误报缝）各以「改前读数 → 改后读数」对账。

## 0. 基线（改前）

| 读数 | 值 | 来源 |
|---|---|---|
| 生产 `eval_runs` 带 verdict 身份（subject_key 非空）的行 | **0 / 16** | `select count(*) filter (where subject_key is not null)` |
| 生产 `eval_runs` 带域归属（rubric_domain_id 非空）的行 | **9 / 16**（均是 legacy 文本通道；数据通道 0） | 同上 |
| `data_checks.run_data_eval` 生产调用方 | **0** | grep（仅 tests/） |
| `erp` / `finance` 域跑过的数据评测 | **0 / 0** | eval_runs 无对应行 |
| `verdicts.register_retest` 生产调用方 | **0** | grep（仅 tests/） |
| `reconcile` 把 `crosswalk` 报成越界 | erp / legal / finance 均报 | 生产 `ledger.reconcile` 实测 |

## 1. C1 数据评测可归属 + 可跑

判据见 `specs/domain-data-eval/spec.md`。真库读数（改后，出片上产后补）：

- [ ] `finance` 域跑一次数据评测 → 结论 `rubric_domain_id` = finance 域 id，`channel='data'`
- [ ] `erp` 域跑一次数据评测 → 结论带域归属
- [ ] 空域（无 checker 的 gov）→ `outcome='inconclusive'`，页面显示「暂无可评」而非「全过」

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

判据见 `specs/domain-retest-loop/spec.md`。真库读数（出片后补）：

- [ ] 确认一条 pending 提案 → `authoring_tasks` 出现一条 `target_kind='verdict-retest'`、`target_key` 含该单位
- [ ] 模板升版 → 每个锚定域出现一条 `template:<name>@v<N>` 复测义务
- [ ] 域 `eval-runs` 页「待复测项」面板列出未结义务；无则明说「没有待复测项」
- [ ] 复测登记抛异常时确认/升版仍成功（单测 `test_confirm_survives_retest_booking_failure` 已覆盖）

## 3. C3 台账不误报内核缝

判据见 `specs/domain-ontology-ledger/spec.md`。真库读数（出片后补）：

- [ ] `erp` / `finance` / `legal` 的 `reconcile`：`out_of_vocab_kinds` 不再含 `crosswalk`
- [ ] `seam_kinds == ['crosswalk']`，且 `consistent` 不再因它而 false（若本无其它越界）

## 4. CI

- image.yml（internal Actions，postgres:14 service）：见 runs 结论
- Knowledge Surface Integrity：retrieval-integrity + ontology-conformance

## 5. ego 真身份走查（`aloadtree@gmail.com`）

- [ ] 登录 `lawbench.finddatatech.cloud` → `/d/erp/eval-runs`
- [ ] 点「跑一次数据评测」→ 三态结论 + 通过比
- [ ] 「待复测项」面板可见
- [ ] 截图归档

## 6. 出片与滚版

- [ ] 镜像进 ccr（`skopeo --override-arch amd64` 核）
- [ ] fd-infra-deploy `all-services/law-bench/deployment.yaml` 滚 tag → push gitee（ArgoCD 读 gitee）
- [ ] pod 内实证：新代码在役（`evaluable_kinds` 非空 / 新面板存在）
