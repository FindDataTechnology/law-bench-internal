## Why

智能体现在是**只能提、不能判**：`proposals.confirm` 与 `reject` 一律拒机器身份，spec 写着「确认提案 SHALL NOT 被任何智能体执行」。后果不是安全，是**评审队列变成人的点击队列**——实测 `data-ontology` 一支舰队提交了 7 条提案，一条也签不了，全靠人。

用户定调（2026-11-21）：**「agent 自主迭代和判断是我们必须要实现的」**，且「基础设施不光要给人用，也要考虑到给 ai 用」。

**但这个诉求不需要推翻 spec 的那条禁令，它需要换一个承载物。** 系统里已经有一条完整的档位阶梯：

```
raw  ──→  bronze  ──→  silver  ──→  gold
   机器自评      机器草稿       人工核验
                                ↑ promote_unit 强制 reviewer 身份
```

`promotion.promote_unit` 里那句 `"gold promotion requires a reviewer identity ... refusing to promote unverified"` **就是「判断须人签」的机器实现**。它比「谁能点 confirm」精细得多：agent 可以一路迭代到 `silver`，**只有最后一步到 `gold` 必须有人**。

所以真正的问题是：**`confirm` 写死 `tier="raw"`，且 `raw` 不在阶梯上**——agent 确认出来的内容和 agent 直接写的内容无法区分，silver 层在生产里恒为 0（实测：5,283 raw / 105 gold / 10 bronze / **0 silver**）。阶梯存在，但没有一条路径把 agent 的产出送上去。

为什么现在做：本轮已经为「agent 能不能签」这件事在生产上改过一次权限（给舰队升 `lead`），那次改动**违反 spec 三条**（智能体角色不超过 expert、确认 SHALL NOT 由智能体执行、管理员豁免对机器无效）。继续按「放开权限」的思路走，只会越改越散；按档位走，改的是**产出语义**，权限边界不动。

## What Changes

- **`confirm` 按确认者身份决定档位**：智能体确认产 `silver`，人确认也产 `silver`。人的特权不在「能不能确认」，在「能不能把 silver 升成 gold」。这条把 spec 的「确认 SHALL NOT 被智能体执行」改成「智能体确认产出 `silver`；升 `gold` 须给 reviewer」。
- **`raw` 纳入升档阶梯**（`raw → silver → gold`），`bronze` 保留现有语义（机器自评，只做失败分析）。否则 agent 的 silver 永远升不到 gold，阶梯断在半路，而生产里 5,283 条 raw 也不会因此变得可迭代。
- **`PROMOTABLE_KINDS` 扩到 `confirm` 能产出的全部 kind**（当前只有 `entity` / `relation`）。否则 silver 的那些 kind 永远无法升 gold——阶梯只对两类生效，等于只覆盖一半。
- **硬停清单从 spec 文本变成代码**。现在 spec 写了六个动作「SHALL NOT 被任何智能体执行」，代码里**零实现**（`grep HARD_STOP` 无命中）。既然要放宽确认，其余五条就必须真的拦住，否则「放宽一条」会连带放开一片。
- **收回本轮越界的权限授予**：`fleet:ontology-builder` 从 `lead` 退回 `expert`。它的确认能力改由「agent 可 confirm 产 silver」这条统一逻辑提供，不再靠域角色。`ops:<operator>/<reason>` 保留（那是人做的裁决，不违反 spec）。

**不改的**：`admin_override` 仍人类独占；自提自确认 / 自提自驳回仍禁；`silver` 永不作 reward、`bronze` 永不作 ground truth（`tiers.py` 的守卫已就位）；发布快照继续带 `tier` 字段、继续不过滤档位（消费方自行取舍）。

## Capabilities

### Modified Capabilities

- `domain-agent-team`：「确认提案 SHALL NOT 被任何智能体执行」改为「智能体确认产出 `silver`，升 `gold` 须给 reviewer」；「硬停清单」从声明变成可执行判据，并明确它管的是**其余五个动作**（开域/归档、放宽取材、改模板版本、删单位、铸凭据），确认不在其中。
- `bench-platform`：`confirm` 写入的档位随确认者身份而定（`silver`），不再一律 `raw`；档位阶梯的入口从「仅外部登记同步」扩展到「域内确认」。

## Impact

**代码（law-bench-internal）**

- `src/bench/proposals.py`：`confirm` 写入时按 actor 定 tier；撤回 `_machine_may_sign` 的 `lead` 例外（改由档位承载，不再需要提权）。
- `src/bench/authoring.py`：`_create_unit` 的 `tier="raw"` 硬编码改为可传入（默认仍 `raw`，确认路径传 `silver`）。
- `src/bench/promotion.py`：`CHAIN` 加 `raw`；`PROMOTABLE_KINDS` 扩到 confirm 能产出的 kind。
- `src/bench/agent_team.py` 或新模块：硬停清单的可执行判据。
- `src/bench/workspaces.py`：`add_member` 对机器身份的角色上限（`expert`），把 spec 那条变成代码。

**数据（生产，需单独执行）**

- `fleet:ontology-builder` 角色回退 `lead → expert`。
- 本轮已落库的两条确认（`dataset` kind）当前 tier 是 `raw`——按新语义应为 `silver`，需要一次定向补写。

**跨仓**

- `fleet-packs`：舰队模板要不要声明「默认授予哪个域、什么角色」，属本变更的**非目标**（见 design），但硬停清单的实现会影响它。

**明确不做**

- 不做「agent 自己给自己提权」的任何路径。
- 不放开 `admin_override`、不自提自签。
- 不让 `silver` 变成 ground truth 或 reward——`tiers.py` 的守卫不动。
- 不在本次改发布语义（`silver` 继续可被消费，只是带档位标记）。
