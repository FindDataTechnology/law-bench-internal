# Tasks — refuse-unlandable-proposals

## 1. 库层（`src/bench/proposals.py`）

- [x] 1.1 新增异常 `ProposalTargetExists(ValueError)`：字段 `reason`
      （`key_already_live` / `endpoints_missing`）、`external_key`、`detail`、`hint`；
      消息里带既有单位 id/kind 或缺的端点。
- [x] 1.2 新增 `preflight_targets(conn, *, domain, kind, external_key, evidence)`：
      用 `_lane_for_kind` 分道、`authoring_live_key_kinds` 取活集合、
      `authoring_get_unit` 取既有行走软删过滤。**不写任何 `knowledge_units` 的 SQL**。
      两处口径修正（都来自实跑）：
      · **kind 不在词表 ⇒ 直接返回**（判不出 lane 就不该拦），词表执法仍归确认侧——
        否则等于偷偷加了第三种拒绝，本变更没声明它；
      · **端点「已在箱里」也算成立**（`活单位 ∪ 本域待确认提案键`）：
        `test_ontology_extraction.py::test_same_batch_entity_closes_the_endpoint` 当场转红
        （submitted 3→2），那是抽取流水线在同一批里提交实体+关系的主路。假红比假绿更糟。
- [x] 1.3 插在 `submit()` 的「同键同依据已驳回」之后、INSERT 之前（幂等去重在前）。

## 2. HTTP 面（`src/web/routes/distribution.py`）

- [x] 2.1 `submit_proposal` 捕获 `ProposalTargetExists` → **409**，body 为
      `{"reason","message","hint"}`；`ValueError` 兜底仍是 422（两档处置方向不同）。

## 3. 测试

- [x] 3.1 `tests/test_domain_proposals.py` 8 臂：重复键被拒且既有正文逐字未变／
      端点缺失被拒（点名缺的那个）／**两端都在 ⇒ 照常进箱**（正路对照）／
      同键异 kind 被拒且 detail 写明既有 kind／幂等重放仍 `created=false`／
      语义判断不被预检碰／**同批闭合（端点在箱里）被接受**。
- [x] 3.2 `tests/test_fleet_loop_e2e.py` 2 臂（真 HTTP + 真 token）：重复键 → 409
      `key_already_live` 且提案行数 0、既有单位正文未变；端点缺失 → 409
      `endpoints_missing` 且提案行数 0。
- [x] 3.3 红证：注释掉 `preflight_targets` 调用后**恰好 5 条转红**
      （4 条库层 + 机器面 2 条里的 2 条，实测 `5 failed, 43 passed`），恢复后全绿。
- [x] 3.4 既有用例的正当调整 1 处：
      `test_confirm_relationship_uses_the_relationship_kernel_path` 原先把「端点还没入库
      的关系提案」当作可提交前提，现已与新规则冲突 ⇒ 补两行 `_seed_unit` 前置，
      判据（确认走关系内核路径、attrs 两端、事件行数）不变。

## 4. 收口

- [x] 4.1 相关六套件 111 passed（proposals / fleet_loop_e2e / proposal_outcomes /
      contract_doc / distribution_web / ontology_extraction）。
- [x] 4.2 `openspec validate refuse-unlandable-proposals --strict` 绿。
- [x] 4.3 生产基线（只读，2026-11-15）：`legal` 域 `state='rejected'` 里
      「键已在库」8 条、「端点不闭合」4 条，作为改造前的存量；改造后若再出现这两类
      新行，说明预检漏了，属回归。

## 5. 全量回归暴露的三件事（2026-11-15 晚，6 条红逐条处置）

- [x] 5.1 **`endpoint_open` / `key_already_live` 这两种形状在提交口已经不可构造**，所以
      质检员（`team_roles.run_verifier`）的用例不能再用「先造单位、再提交」来摆场景——
      那样摆出来的状态新规则不允许存在。真实成因是**事后**变化：提案进箱后，同一个键被
      别人确认为活单位（重复），或某个端点被软删（端点开着）。三条夹具按此重排：
      · `test_verifier_flags_a_key_that_already_exists`：先提交、再建单位；
      · `test_verifier_flags_an_open_relationship_endpoint`：两端都建 → 提交关系 →
        `authoring_delete_unit` 软删一端（这正是「闭合」在质检时刻的含义）；
      · `test_verifier_never_changes_a_proposal_or_the_ontology`：先提交、再建单位。
      **判据一行没改**（`by_check[...]` 的断言原样）；改的只是"这个世界是怎么变成这样的"。
      ⇒ 质检员没有因此变成死代码：生产里 95 条既有提案、以及任意「pending 期间世界变化」
      都仍然需要它。
- [x] 5.2 **我自己撞了内核的禁词闸**：`test_kernel_domain_free.py` 扫描 `src/bench` 源码里的
      领域词（`民法典`/`法条`/`法规`/`合同`…），零容忍。我写的注释
      `# 软删的不算活单位，与 live 集合同口径` 里「集合**合同**口径」跨词拼出了「合同」⇒ 当真命中。
      改成「与 live 集合一致」。**这条闸是子串匹配、没有词边界**，所以在 `src/bench/` 里写中文
      注释要避开这些字相邻的可能；改成英文或换词都行，但**不要**去放宽 BANNED_TERMS。
- [x] 5.3 **两条与本变更无关的既有红（顺手修了断言，判据不变）**：`test_agent_identity.py`
      的两条用例断言文案是「智能体不得确认提案」/「管理员豁免不适用于智能体提交的提案」，而
      11-14 那笔 `3294c8f`（「签字人闸只认 `agent:` 前缀——`fleet:` 形状能直接签字」）已把
      运行时文案统一成「机器身份」以覆盖 `fleet:`/`extract:`。测试文件最后一次改是 11-13 ⇒
      **文案漂移，不是我这两天的改动**。只更新期望文案，判据（机器身份不得确认、豁免不替机器
      背书）不变。
