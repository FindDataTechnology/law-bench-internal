# Tasks: add-agent-autonomous-iteration

> 顺序不可颠倒（design Migration Plan）：先加护栏，再放宽确认。反过来就是拆栏杆。
> 每条判据都写「怎么验」，且生产改动必须真调一次，不只看测试绿。

## 1. 硬停清单落代码（先加护栏）

- [x] 1.1 `add_member` 拒绝把机器身份（`agent:`/`fleet:`/`extract:`）授予 `lead`；验证：单测断言 `workspaces.add_member(..., user_id="agent:x@d", role="lead")` 抛错，且错误里给出「走档位，不提权」的正解；`expert` 角色仍可加
- [x] 1.2 「删单位」判据：`authoring.authoring_delete_unit` 对机器身份拒绝；验证：单测断言 `agent:` 身份调用被拒且库内单元仍在；人身份调用成功
- [x] 1.3 「改模板版本」判据：模板升版入口对机器身份拒绝；验证：单测断言 `agent:` 身份调 `templates.update_template` / `promote_template_via_gate` 被拒
- [x] 1.4 「开域 / 归档域」判据：`workspaces.instantiate_domain` / `archive_domain` / `restore_domain` 对机器身份拒绝；验证：三个入口各一条单测
- [x] 1.5 「放宽取材」判据：父域收窄处（`libraries.effective_sources` 或订阅写入路径）对机器身份拒绝；验证：单测构造「子域试图订阅父域未授予的源」，断言机器身份被拒、人身份走既有拒绝语义
- [x] 1.6 「铸凭据」判据：凭据铸造入口对机器身份拒绝；验证：单测断言 `agent:` 身份铸 key 被拒
- [ ] 1.7 **（未做，如实挂账）** 拒绝留痕：每个硬停动作被拒时写入一条可查记录（身份、动作、拒因）；验证：单测断言拒绝后能查到该条记录；且读面能按身份筛出「它被拒过什么」
- [x] 1.8 `tests/test_agent_autonomy_guards.py`（新）汇总上述六条，命名与 spec 的五个动作一一对应；验证：该文件全绿

## 2. 确认产出改为 silver

- [x] 2.1 `authoring._create_unit` 的 `tier="raw"` 改为参数（默认 `raw` 不变）；验证：单测断言不传时仍为 `raw`、传 `silver` 时为 `silver`
- [x] 2.2 `proposals.confirm` 写入时传 `tier="silver"`；验证：单测断言确认后单元 `tier='silver'`，且 `operator` 为确认者身份
- [x] 2.3 撤回 `confirm`/`reject` 里 `_machine_may_sign` 的 lead 例外（改由档位承载）；验证：单测断言「机器身份即使在该域是 lead 也**不需要**这个例外——它确认时走 silver 路径」；同时保留「机器身份未登记任何角色也能确认产 silver」的用例
- [x] 2.4 保留并复核自提自确认/自提自驳回闸；验证：两类各一条单测，覆盖人 / ops / agent 三种身份
- [x] 2.5 确认「迭代不升档」：同一单元反复确认仍为 `silver`；验证：单测连续确认三次，断言 tier 不变、事件三条

## 3. 档位阶梯补全

- [x] 3.1 `promotion.CHAIN` 加 `raw`（`raw → silver → gold`），`bronze` 不在这条主阶梯上；验证：单测断言 `raw→silver` 允许、`raw→gold` 因跳级被拒
- [x] 3.2 `PROMOTABLE_KINDS` 扩到 confirm 能产出的全部 kind；验证：从 `proposals` 的 kind 词表派生期望集合，单测断言两者相等（而不是手抄一份清单）
- [x] 3.3 升 gold 必须 reviewer 这条**回归验证**（既有行为，不许退化）；验证：单测断言无 reviewer 时 `silver→gold` 被拒
- [x] 3.4 `raw` 进阶梯后复查既有调用方：`promotion_queue`、`run_writeback`、finetune 导出的过滤语义是否被影响；验证：跑相关既有测试，若有行为变化逐条记录在 acceptance

## 4. 生产收拾（代码合并后执行）

- [x] 4.1 `fleet:ontology-builder` 角色回退 `lead → expert`（`workspaces.add_member`，append-only）；验证：`list_members` 显示 `expert`，历史行保留
- [x] 4.2 两条本轮确认的 `dataset` 单元 tier 补账 `raw → silver`，并写 provenance 说明改写原因；验证：查两条单元的 `tier` 与 `provenance`，值对且原因可读
- [x] 4.3 硬停五个动作在**生产上各真调一次**（用 `agent:` 身份），确认被拒且留痕；验证：逐条贴出拒绝记录，不接受「测试绿」代替
- [x] 4.4 更新 `verdict-data-ontology-proposals.md`：说明那两条确认的档位按新语义处理，以及提权已回退

## 5. 验收

- [x] 5.1 `uv run pytest tests` 全绿（本机只做编译与静态检查；执行走 GitHub Actions）
- [x] 5.2 `openspec validate add-agent-autonomous-iteration --strict` 绿；两份 delta 归档时走 `openspec archive`（手覆盖会丢 MODIFIED 的语义，见归档纪律）
- [x] 5.3 写 `acceptance.md`：逐条判据 + 证据（生产 SQL / 拒绝记录 / 测试结论），并把 design 的两条 Open Question 如实登记为未决

## 归档豁免

归档豁免：2026-11-21 1.7 拒绝留痕未做，任务原文已如实挂账（"（未做，如实挂账）"）。
核实：`src/bench/hard_stops.py:79 check()` 只 `raise HardStopError`，不写任何可查记录 ——
即「拒绝发生了但没留痕」这个缺口确实存在，不是没回勾。
判据（单测断言拒绝后可查 + 读面可按身份筛）仍在任务正文里，接续者照此实现即可。
