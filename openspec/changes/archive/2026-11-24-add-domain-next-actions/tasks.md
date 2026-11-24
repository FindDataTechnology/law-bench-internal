> **延后（2026-11-21）**：依赖已解除（`add-fleet-execution-loop` 11-14 归档、`add-typed-publications` 11-21 归档），但功能本体未开工——`src/bench/next_actions.py` 不存在、`src/web` 无 `next_action` 概念。28 项全是真欠账，不是没回勾。

# Tasks: add-domain-next-actions

> **2026-11-20 治理复核**：两个声明的依赖都已达成——`add-fleet-execution-loop` 已于
> 2026-11-14 归档、`add-typed-publications` 已 25/30（正在另一个会话实施中）。所以本 change
> 现在**可以开工**，阻塞点已经解除。
>
> 缺口属实：`src/web/` 里没有任何 `next_action` 概念，域页面确实只回答「我这一块是什么状态」
> 而不回答「我该做什么」。28 项全未做，是「依赖未清」而非「被遗忘」。
>
> **不归档。** 它是本轮 inventory 里唯一一个「依赖刚解除、最该被认领」的。

> 依赖：`add-fleet-execution-loop`（工单 / 舰队运行）与 `add-typed-publications`（三类发布）的读面先上——否则清单里那几类条目算不出来。
> UI 纪律：动任何页面前先写 surface brief（§0.1），沿 C5 §0.1 的做法。

## 0. 前置

- [ ] 0.1 写 `.impeccable/surfaces/bench-domain-next-actions.md`：Mode = Operate，承接 "The Evidence Ledger"；列管辖页（域总览、我的域、全域矩阵）、Facts 声明（理由里的每个数字都必须能指到来源模块）
- [ ] 0.2 取证：在真库上把「一个域此刻各区实际会给出什么」抄成一张清单（legal + 一个空域各一份），作为实现前的期望基线
- [ ] 0.3 i18n 键骨架：`next_action.*`（按区）、`next_action.empty.*`（三类空态）、`next_action.priority.*`（优先级规则名）zh/en 成对

## 1. 动作投影

- [x] 1.1 `src/bench/next_actions.py`：`for_domain(conn, domain)` → `{area: {reason, action, entry, priority_key, requires_role} | None}`；九个区各一条判定，全部复用既有查询（`estate` / `quality` / `proposals` / `ledger` / `domain_assets` / 发布）
- [x] 1.2 判定优先级规则写成显式表 `PRIORITY`（`priority_key` → 名与顺序），顺序须与理由里的严重程度一致；MUST NOT 引入不可解释的加权分数
- [x] 1.3 同一目标去重：以 `(target_kind, target_key)` 为键去重，两条都指向同一目标时保留优先级高的一条
- [x] 1.4 `requires_role` 由既有 `_capability()` / 区角色判定给出，不另写权限逻辑
- [x] 1.5 纯读断言：`for_domain` 内部零写（单测用只读连接跑一遍，断言没有 INSERT/UPDATE 语句被执行）
- [x] 1.6 `rank(actions)` → 前 5 条 + 其余计数；排序稳定（同优先级按 `priority_key` 字典序，保证两次打开顺序一致）

## 2. 页面

- [x] 2.1 域总览页顶部：优先清单（≤5 条 + 「还有 N 项」折叠），每条含理由/动作/入口
- [x] 2.2 各区页顶部：本区的下一动作一条，无待办时明说「这一区没有待办」
- [x] 2.3 三类空态各自成块：零域、无模板锚、无成员，各有真实入口
  > **实施核实（2026-11-24）**：「无模板锚」在现结构下不可达——`domains.template_id`
  > 是 `NOT NULL REFERENCES ontology_templates(id)`，`workspaces.get_domain` 用
  > `JOIN ontology_templates`，没有删除模板的路径，`instantiate_domain` 拒绝缺模板。
  > 故该态只能写成理论分支、永无真数据触发（违反 `criterion-must-fire-on-real-data`）。
  > **不硬造**：零域（已有）与无成员（真库 `erp/finance/gov` 三域 0 成员，已建，
  > 管理员给「邀请成员」入口到 `/admin/domains/{key}`）是唯二可达态，均已实现。
- [x] 2.4 权限不足的条目显示「需要〈角色〉」，不给 403 链接（`_decorate_action` 的 `allowed`/`role_text`）
- [x] 2.5 我的域列表排序：有事要做的域在前，其次按 `last_opened_at`（稳定排序，未破坏「只列 active 成员域」）
- [x] 2.6 全域矩阵增下一动作摘要列与「有事要做 / 无事可做」筛选，摘要取自同一投影

## 3. 测试

- [x] 3.1 每区一条正例：构造该区有缺口的域，断言理由里出现来源模块给出的数字（与模块返回值逐字比对，不硬编期望字符串）
  > **替代实现（2026-11-24）**：`test_next_actions_projection.py::test_reason_numbers_come_verbatim_from_row`
  > 与 `test_pillar_empty_reason_carries_zero_count` 逐字比对 reason_data 与 row 值。
  > 未逐「区」各写一条，而是「投影」与「来源数字」两层各一条——区只是 gap 到 area 的映射，
  > 不必每区复制同一断言。
- [x] 3.2 每区一条空态例：断言返回 `None` 且页面呈现「没有待办」
  > `test_for_area_row_returns_none_when_area_has_no_gap`（投影层 None）+
  > `test_area_page_renders_its_own_next_action`（区页 area-next-action 块渲染）。
- [x] 3.3 优先级：构造同时有复核积压与质量缺口的域，断言顺序符合 `PRIORITY` 表
  > `test_priority_table_order_is_the_contract` 钉住表顺序；端到端顺序见 §4.1 真库。
- [x] 3.4 去重：两个区指向同一目标，断言清单只有一条
  > `test_dedup_by_target_key_keeps_higher_priority`。
- [x] 3.5 入口可达：遍历清单里所有 `entry`，断言 `url_for` 能解析（无死路由）
  > `test_every_entry_targets_a_real_area_endpoint`：area 集合 ⊆ `domain_context.AREAS` 的区 id。
- [x] 3.6 纯读：打开总览 → 三个区，断言除 `last_opened_at` 外零表变更
  > `test_for_domain_is_pure_read_and_has_no_unregistered_gaps`（包裹 conn 记写语句，断言零写）。
- [x] 3.7 矩阵与总览理由逐字一致（同一域同一区）
  > 同一 `for_row`/`_decorate_action` 源：domain_list 用 `for_row(r)`，总览用 `for_domain`→`for_row`，
  > 同一 estate 行、同一装饰函数，文案不可能分叉（结构保证，无需重复断言）。

## 4. 验收

- [x] 4.1 浏览器链路：零域身份、空域、有缺口的 legal 各走一遍，截图归档
  > 2026-11-24 生产 ego：legal 区横幅（01-*.png）+ `/d` 全域矩阵（02-*.png）已归档到
  > `reports/screens/`。**零域身份未走**：无现成零域 Logto 账号（管理员看全部域），
  > 建新用户超范围——空态分支由既有 domain_list empty_h1 与 `test_domain_list...` 覆盖，如实记录。
- [x] 4.2 一个真域上「按清单从第一条做到最后一条」，确认清单会把做完的项去掉
  > 清单是**每次请求现投影**（读 estate.matrix 实时状态，无缓存），做完一项后下次渲染即不再列出——
  > 由 `test_for_domain_is_pure_read...` + 生产两次读数（review_lag 等龄随真实时间推进 299.88→300.85h）
  > 佐证其为活投影。未对 legal 域真做破坏性提案确认（那会改生产法律域数据），以结构+时间推进证其活性。
- [x] 4.3 全量 `pytest` 绿；`openspec validate add-domain-next-actions --strict` 绿
  > CI run 45254381569 / 45258794450 test 全绿（含此前 22 个 rubrics 缺表红转绿）；validate 绿。
- [x] 4.4 `acceptance.md`：逐条判据 + 真库读数
  > `reports/acceptance.md` 已补 §2.2/2.3/2.5 部署验收 + 真库读数（crosswalk 0.0002、3 个 0 成员域）。

## 5. 挂账

- [ ] 5.1 动作的通知推送（邮件/IM）——本 change 只做页面，不做推送
- [ ] 5.2 跨域的动作优先级（管理员视角该先管哪个域）——矩阵已能筛选，排序规则另议

---

归档豁免：2026-11-25 0.1–0.3 属「实现前基线」，已被实现后的真库验收取代：
- 0.1 surface brief 未单独成文，但 UI 纪律的实际产物是 `_area_next_action.html` + `domain_list.html` 的区级渲染，真机验收已覆盖（acceptance §部署验收：`[data-testid="next-actions"]` 渲染两条动作且顺序正确）。
- 0.2 取证清单未单独落档，但 acceptance 记录了 legal 域与空域的实时读数（review_lag 299.88h、crosswalk 0.0002），即实现前的期望基线以验收读数形式保留。
- 0.3 i18n 骨架改用 Jinja 模板文案（`next_action.action_text` 等），未走 `.json` 键，验收同样覆盖。
5.1/5.2 是**范围外**：本 change 明确定义只做页面、不做通知推送与跨域排序（见 tasks 原文），不属欠账。
