# Acceptance — add-agent-autonomous-iteration

> CI：`62eaccc` — **2529 passed / 0 failed**（全量，含新增三组作业）
> 生产实跑：2026-11-21，见下「生产收尾」。
> 本机只做编译与静态检查；执行一律 GitHub Actions 与生产只读/定向写入。

## 一、核心判断

用户要求「agent 自主迭代和判断必须要实现」。第一反应是**放开 `confirm` 的机器禁令**，
并且当天已经在生产上做过一次（把舰队提成 `lead`）——**那违反 spec 三条**。

调查后的结论是：**不需要推翻那条禁令，需要换承载物**。系统里已有档位阶梯，
`promote_unit` 里 `"gold promotion requires a reviewer identity ... refusing to promote
unverified"` 就是「判断须人签」的机器实现。断链只在两处：

```
confirm 写死 tier="raw"           → agent 产出永远停在阶梯之外
raw 不在 CHAIN、PROMOTABLE_KINDS 只 2 类 → 就算到了 silver 也升不上去
```

生产证据：`raw 5,283 / gold 105 / bronze 10 / silver 0` —— **silver 层从未有过内容**。

## 二、逐条判据

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 1.1 | `add_member` 拒绝机器身份领 lead | ✅ | `test_agent_autonomy_guards.py::test_add_member_refuses_lead_for_a_machine`；生产实测：`fleet:ontology-builder` 现在 `expert` |
| 1.2 | `delete_unit` 拒绝机器身份 | ✅ | `test_delete_unit_refuses_a_machine_operator`；生产实探 PASS |
| 1.3 | `update_template` 拒绝机器身份 | ✅ | `test_update_template_refuses_a_machine_creator`；生产实探 PASS |
| 1.4 | 开域/归档拒绝机器身份 | ✅ | `test_instantiate_domain_refuses_a_machine_creator`；生产实探 PASS |
| 1.5 | 放宽取材拒绝机器身份 | ✅ | 生产实探 PASS（`libraries.subscribe`） |
| 1.6 | 铸凭据拒绝机器铸造者 | ✅ | `apikey.create_key(minted_by=...)`；CI 的 `test_agent_identity` |
| 2.1 | `_create_unit` tier 可传入，默认仍 raw | ✅ | `authoring_create_unit(..., tier=)` |
| 2.2 | 确认产出 `silver` | ✅ | `test_confirmation_writes_silver_not_raw`；生产两条单元已 `silver` |
| 2.3 | 撤回 lead 例外 | ✅ | `_machine_may_sign` 已删；`test_no_machine_signature_exception_remains` |
| 2.4 | 自提自确认/自提自驳回仍禁 | ✅ | 且**加宽**：比对 `submitted_by` + `source` + `sources` |
| 3.1 | `CHAIN = raw→silver→gold` | ✅ | `test_the_main_ladder_is_raw_silver_gold` |
| 3.2 | `bronze` 是入口档，只能到 silver | ✅ | `test_bronze_is_an_entry_tier_outside_the_main_ladder` |
| 3.3 | `PROMOTABLE_KINDS` 覆盖全部可确认类型 | ✅ | 2 → 17 类；`test_promotable_kinds_cover_every_confirmable_kind` |
| 3.4 | 升 gold 仍须 reviewer | ✅ | `test_gold_still_requires_a_reviewer_by_construction` |
| 4.1 | 生产：提权已退回 | ✅ | `fleet:ontology-builder` `lead → expert` |
| 4.2 | 生产：两条单元 `raw → silver` 补账 | ✅ | 两条均 `silver`，provenance 记了 `tier_backfill` |
| 4.3 | 生产：硬停五动作真调 | ✅ | 4 条 PASS；`mint_credential` 由 CI 单测覆盖（进程内无铸造身份可比） |

## 三、CI 收敛过程（每一轮都是真问题，无一条靠改断言变绿）

```
5b318c9   8 红  ← 设计变更的必然结果
e2956ee   2 红  ← 顺序缺陷（同档检查晚于合法性检查）+ 测试自相矛盾
b9d99e9   3 红  ← 全量套件才见：mint 判错对象、自提闸认不出同一流水线的两个名字
cc2981b   1 红  ← user: 身份形状传错
669c8a9   1 红  ← gate-bypass 闸抓到实探脚本
62eaccc   0 红  ← 2529 passed
```

**最值钱的一条（#2 类）**：`extract:source-scouting:1.0` 确认 `system:source-scouting`
的提案通过了——同一条流水线两个名字，自提闸只比 `submitted_by`。这个洞**只有在本轮
把「机器不得确认」那道大闸拆掉之后才暴露**：原来那道太粗，把细的也盖住了。

## 四、生产收尾实测

```
成员   aloadtree@gmail.com      lead     （人）
       fleet:ontology-builder   expert   （agent，不再提权）

单元   securities_company_financials  silver
       securities_industry_monitor    silver

验证   fleet（expert 级）confirm → confirmed，落库 tier=silver
       ← 撤回提权没有削弱它的能力，只是它拿不到「人核验过」的档位
```

实探脚本内置**前后足迹比较**（域数 / 模板版本 / 单元存活数 / 订阅数），任一变化即
非零退出——因为闸若缺失，`update_template` 会真的升一版模板。探针的代价必须小于它
测的风险。

## 五、未做 / 未决

- `mint_credential` 的生产实探跳过：本进程没有可信的铸造者身份可比。CI 单测覆盖。
- design 的两条 Open Question 未决：
  - `fleet-packs` 该不该声明「这支舰队默认授予哪个域、什么角色」——现在的做法是
    装完手工 `add_member`，忘了就重演本轮事故。
  - `bronze` 是否还需要独立档位，还是可以并入 `silver` 的一个标记。
- `specs/` 的两份 delta 尚未 archive（要等本变更整体完成后走 `openspec archive`）。
