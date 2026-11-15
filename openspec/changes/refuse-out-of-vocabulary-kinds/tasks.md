# 任务：词表外 kind 的预检

## 1. 库层

- [x] 1.1 `src/bench/proposals.py`：新增 `class KindNotInVocabulary(ValueError)`，
      文档字符串写明它是「词表裁决」而不是「数据坏了」，且子类化 `ValueError` 是为了让
      确认路径与既有调用方的 `except ValueError` 逐字不变。
- [x] 1.2 `_lane_for_kind`：只在「kind 不在任一张**非空**词表里」这一支抛
      `KindNotInVocabulary`；模板缺失 / schema 非 dict / 两张词表都空仍抛裸 `ValueError`
      （判不出，正解是修服务端数据）。
- [x] 1.3 `preflight_targets`：先捕 `KindNotInVocabulary` → 抛
      `ProposalTargetExists("kind_not_in_vocabulary", …)`，`detail` 点名 kind、模板版本与
      两张词表，`hint` 给两条正当路径；随后仍是 `except ValueError: return`。
      同时改掉函数文档字符串里「kind 越界不预检」那段——它今天已不成立。

## 2. 抽取面

- [x] 2.1 `src/bench/extraction.py`：`skipped` 加 `kind_not_in_vocabulary: 0`，注释写清它与
      `bad_kind` 的分工（包声明词表 vs 域锚定模板词表，两张表可以不一致）。
- [x] 2.2 提交处捕 `ProposalTargetExists` 的分支加这个桶。

## 3. 用例

- [x] 3.1 `tests/test_domain_proposals.py`：
      - 词表外 kind 被拒（409 理由 + 无提案行）；
      - **成对**：词表内 kind 照常进箱（证明拦的是词表而不是「所有提交」）；
      - ~~模板无词表时不拦~~：**撤掉**，那个状态造不出来（`validate_template_schema` 要求两个
        词表键必填且非空），硬插 SQL 造它等于让夹具替我说话。见 design D2。
- [x] 3.2 `tests/test_fleet_loop_e2e.py`：真 HTTP 一条，断言 409 的 `reason` 字段。
- [x] 3.3 抽取桶：断言 `run()` 的报告里**有** `kind_not_in_vocabulary` 这个键（防 KeyError）。
      **不**断言它会自增——那一侧提交前已按同一张模板词表预筛，这一类在抽取路径上不可达；
      写一条「计数会增加」的用例只能靠伪造提交来摆场景，那是夹具替我说话。

## 4. 验证

- [x] 4.1 红证：把 1.3 的捕获删掉，3.1 的第一条必须转红（证明它真的在测新规则）。
- [x] 4.2 全量回归（`nohup` 后台，跨会话存活）：**2192 passed / 60 skipped / 0 failed**（681s）。
      首轮 2189 passed + **3 failed**，三条全是本次规则把既有夹具从「静默可提交」翻成「拒」，
      处置记在 §4.4。
- [x] 4.3 `openspec validate refuse-out-of-vocabulary-kinds --strict` 绿。

## 5. 落地

- [ ] 5.1 只 `git add` 本变更涉及的文件，`-F` 提交并推送真源。
- [ ] 5.2 导出公开面（`SRC_REPO=<干净 worktree>` 走 `sync_public_from_internal.sh`）。
- [ ] 5.3 归档：备份 specs → `openspec archive --yes` → 核对 `Totals`（期望 `+0 / ~1`，
      因为这是 MODIFIED）→ 归档后 `openspec validate fleet-submitter-contract --type spec
      --strict` 绿。

## 4.4 三条被新规则翻红的既有夹具（判据不变，夹具按真实成因重排）

- [x] 4.4.1 `test_the_same_claim_from_two_producers_is_one_row` 与
      `test_different_evidence_for_the_same_key_stays_two_rows` 用 `kind="concept"` 提交，
      而夹具模板词表是 `company`/`indicator` ⇒ **那两条提案本来就永远确认不了**，只是以前
      没人拦。这两条测的是**去重语义**（同键同依据一行 / 异依据两行），`kind` 只是标签，
      改成 `indicator`，断言一字未动。
- [x] 4.4.2 `test_ontology_batch_review.py::test_partial_failure_does_not_roll_back`
      故意用 `kind="spaceship"` 造「确认时失败」的行——正是「**入口拒绝让检查器夹具不可构造**」
      那一族（同 `an-entry-refusal-makes-the-checker-fixture-unconstructible`）。它测的是
      **批量确认一条失败不拖垮整批**，而那条路径在生产里仍然可达：行在箱里待着的时候模板
      收窄，或它本身就是加本规则之前就存在的旧行（生产 #86/#90/#94 正是）。所以改成
      「先合法入箱，再 `UPDATE` 该行 kind」——世界变化而非绕过被测入口。
- [x] 4.4.3 三条都不能走的错路：删掉这些用例（去重与批量确认都是活路径）、给预检开旁路
      （两面口径就分叉）、把夹具改成直接 INSERT 提案行（绕过被测入口）。
