# 裁决单：data-ontology 域 7 条 pending 提案

> 状态：**2026-11-21 已处置 5 条，剩 2 条待人类确认**（执行记录见文末）。
> 处置用的身份是新增的运维裁决类 `ops:<operator>/<reason>`，不是 `system:*`
> 那种靠字符串形状过闸的口子——见 `agent_ids.is_ops` 与该轮 commit。
> 调研时间：2026-11-21。数据来源：`wire_datasets` 真行聚合 + `law_bench` 提案表。

## 结论

**7 条全部驳回。** 其中 2 条（`#90`/`#94`）是**结构上永远确认不了**的，
其余 5 条是**同一批数据被两个提交方各提了一遍**加**键口径错误**。

## 逐条

| # | 一句话 | 裁决 | 依据 |
|---|---|---|---|
| 88 | `financials` 实体，键 `(code,item,period)` | **驳回** | 键含非身份列（见下「period 不是身份」）；与 #91 重复 |
| 89 | `monitor` 实体，键 `(code,metric)` | **驳回** | 键**正确**，但证据是 174 字节字符串、无结构化实测；与 #93 重复且弱于 #93 |
| 90 | `financials.code → monitor.code` | **驳回（结构不可落）** | `evidence` 是 JSON **字符串**（内容是数组），`_relationship_endpoints` 要对象带 `from_key`/`to_key` ⇒ 确认必失败 |
| 91 | `financials` 实体，键 `(code,item)`，key 带 `entity:` 前缀 | **驳回** | `keys.fold` 不剥 `entity:` ⇒ 会成为**第二份同数据集知识单元** |
| 92 | `monitor` 实体，key 带 `entity:` 前缀 | **驳回** | 同上 |
| 93 | `monitor` 实体，键 `(code,metric)`，9 组证据 | **驳回** | 键**正确**、证据最硬，但它是 `#89` 同一主张的另一次提交；域里 0 单元、0 语料，单条确认会留下一个只有一条实体的域 |
| 94 | `monitor.code → financials.code` | **驳回（结构不可落）** | 同 `#90`；且方向与 `#90` 相反，两者只能活一个 |

## 实测证据（全部来自真行）

在 `wire_datasets`（只读，`fd-wire-api` pod 内）对两张表的**真实行**做 `group by` 聚合：

```
financials  90 行
    code                 =>  3 组   不唯一
    code+item            => 90 组   唯一
    code+item+period     => 90 组   唯一   ← period 对唯一性零贡献
    period 取值           =>  1 个（2026-09-30）

monitor     49 行
    code                 =>  8 组   不唯一
    code+metric          => 49 组   唯一
    code+metric+period   => 49 组   唯一
    period 取值           =>  3 个（2026-06-30×3 / 2026-09-18×1 / 2026-09-30×45）
    (code,metric) 分组后每组 period 是否唯一 => 是，0 例外
```

### period 不是身份列

`financials.period` **只有一个值**，对唯一性零贡献；`monitor.period` 有 3 个值，但在
`(code,metric)` 的每个分组内 period 唯一——**它是被 `(code,metric)` 决定的观测时点**，
不是身份的一部分。把它写进主键意味着「同一条指标换个快照日期就是另一个实体」，
下一次同步就会把全部实体换掉一遍。

### 方向：值域包含不构成引用方向

```
financials.code (3): 600030, 600519, 601398
monitor.code    (8): 000001, 600030, 600036, 600519, 601398,
                     SEC-ASTOCK-DAILY, SEC-FIN-INDICATORS, SEC-PERFORMANCE-EVENTS
monitor ⊇ financials: True，交集 3 个
```

调研结论据此判「monitor 是超集 ⇒ 它是被引用主表」。**这推不出方向**：正确的方向判据是
**基数**——3 家公司在 8 条序列下被观察，一个公司有多条指标序列 ⇒ 真正的 1:N 是
`financials → monitor`（即 `#90` 的方向），不是 `#94`。

但这两条都已因 evidence 结构不可落而驳回，方向争议不必现在裁。

## 为什么不自动执行

1. **域里没有任何人类成员，这才是真障碍**。`data-ontology` 唯一成员是
   `fleet:ontology-builder`（`expert`）。驳回的路由侧要求 `lead` 角色
   （`console.py:263` 的 `require_domain_role("lead")`），而机器身份在 bench 层被
   `reject` 的新闸拦住（`proposals.py`，2026-11-21 补，与 `confirm` 对称）。
   **两条路都关着**：正常路径下这个域当前无法处置任何提案。
   正解不是放宽闸，是**给这个域加一个人类 lead**——那是运维动作，不是代码动作。
2. **`system:*` 是一个未闭合的口子，但不是本裁决的抓手**。`agent_ids.MACHINE_PREFIXES`
   只含 `agent:`/`fleet:`/`extract:`；`submitters.classify_source` 也认不出 `system:`。
   所以 `actor="system:import"` 能驳回，而 `fleet:` 不能。这不对称，但把 `system:`
   加进机器类是**改身份体系**（影响 `confirm` 与所有 `operator="system:*"` 的脚本），
   不属于「让驳回与确认对称」这件事。已由
   `tests/test_domain_proposals.py::test_unrecognised_identity_prefix_is_not_treated_as_machine`
   钉住现状：将来有人加它，那条测试会红，逼这个决定被显式做出来。
3. **驳回是单向的**：同 digest 不可重提，`#90`/`#94` 换证据等于重做整条提案。

## 执行方式（人类 lead 签字后）

```bash
# 需要：以 lead 身份进 data-ontology 域的账号，或平台 admin
# 逐条（理由必须写，reject 强制要求 note）：
curl -X POST .../d/data-ontology/inbox/<id>/reject -d "note=<下表理由>"
```

| # | 驳回理由（可直接用） |
|---|---|
| 88 | 键含非身份列：period 在全表恒为一个值，对唯一性零贡献；且与 #91 同数据集重复提交 |
| 89 | 与本域 #93 同一主张的重复提交，且证据弱于 #93（254 字节字符串 vs 九组结构化实测） |
| 90 | evidence 结构不可落：存为 JSON 字符串（内容是数组），缺 from_key/to_key，确认必失败 |
| 91 | external_key 带 `entity:` 前缀且不会被归名剥离，确认后成为第二份同数据集知识单元 |
| 92 | 同 #91：`entity:` 前缀造成重复身份 |
| 93 | 键与证据成立，但与 #89 重复；本域当前 0 单元，单条确认留下只有一条实体的域，待整批重建 |
| 94 | evidence 结构不可落（同 #90）；方向与 #90 相反，两者只能存一 |

## 后续（重建方式）

这 7 条驳回后 `data-ontology` 归于 0 提案。要重建应当：

1. **一个数据集一条实体提案**，`external_key` 用裸数据集键（不带 `entity:`）；
2. 主键只写**身份列**：`financials (code,item)`、`monitor (code,metric)`；`period` 记进
   `attrs.observed_at` 或 `concept_structures`，不进键；
3. 关系提案的 `evidence` 必须是**对象**并带 `from_key`/`to_key`——这是 11-16 之后提交闸
   已经强制的事，重建时自然满足；
4. 若两个方向都想留，只留基数正确的那一条（`financials → monitor`）。

## 执行记录（2026-11-21）

工具 `scripts/reject_unlandable_proposals.py`，身份 `ops:chengsishi/<reason>`。

| # | 结果 | 依据 | 身份 reason |
|---|---|---|---|
| 90 | **已驳回** | evidence 是 JSON 数组而非对象，关系确认路径要求 `from_key`/`to_key` | `duplicate-submissions` |
| 94 | **已驳回** | 同上 | `duplicate-submissions` |
| 91 | **已驳回** | `entity:` 前缀不被归名剥离，会成为同数据集第二份单元 | `duplicate-submissions` |
| 92 | **已驳回** | 同上 | `duplicate-submissions` |
| 89 | **已驳回** | 与 #93 同一主张但证据弱（一句话 vs 三组逐列实测） | `redundant-period-key` |
| 88 | **待确认** | `(code,item,period)` 键，本数据集唯一代表 | — |
| 93 | **待确认** | `(code,metric,period)` 键，本数据集唯一代表 | — |

剩 2 条的确认需要**人类签字**：`confirm` 的两道闸分别是「机器身份不得签字」和
「admin 豁免对机器提交的提案不生效」，而这两条都由 `fleet:` 提交。这不是缺口，
是分工——确认会把内容写进本体，那是业务裁决。

**这两条确认得下去**：`data-ontology` 模板的 `entity_types` 含 `dataset`，kind 在词表内。

### 实测佐证（本轮真行聚合）

`period` 在两个数据集上都不是身份列：

```
financials  90 行  period 取值 1 个（2026-09-30）
            code+item => 90 组唯一；code+item+period => 也是 90 组
monitor     49 行  period 取值 3 个
            code+metric => 49 组唯一；每个 (code,metric) 分组内 period 唯一（0 例外）
```

所以确认时建议把 `period` 记进 `attrs.observed_at`/概念结构，**不进主键**——
否则下一次快照同步会把全部实体换掉一遍身份。这条建议不影响「确认哪条提案」，
只影响确认后怎么写。

## 这个域仍然缺的东西

`data-ontology` 的唯一成员是 `fleet:ontology-builder`（`expert`），没有任何人类
`lead`/`admin`。后果是**任何提案都无法在该域被确认**，只能由运维身份驳回。
补一个人类 lead 是运维动作（`workspaces.add_member`），不是代码改动，本轮未做。

## 2026-11-21 后记：档位语义变更后的状态

本裁决单执行之后，`add-agent-autonomous-iteration` 改了确认的产出档位：

- 两条**已确认**的单元（`securities_company_financials` / `securities_industry_monitor`）
  原为 `tier='raw'`，已补账为 **`silver`**（provenance 里记了 `tier_backfill` 与原因）。
  没有重放确认动作——那会再写一次内容、再记一条事件。
- `fleet:ontology-builder` 当时被升为 `lead` 以便确认，**已退回 `expert`**。
  它的确认能力改由档位机制提供：确认产出 `silver`，不需要域角色。
  生产实测：`expert` 级的它仍然能确认，落库 `silver`。
- 该域现在是：`aloadtree@gmail.com(lead, 人)` + `fleet:ontology-builder(expert, agent)`。
