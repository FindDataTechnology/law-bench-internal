## MODIFIED Requirements

### Requirement: 溯源四层与真值守卫

知识单元与物料 SHALL 标注互斥四层 tier：gold（人工核验，可作 ground truth/reward）、silver（机器草稿或**未经人工核验的确认产出**，仅暖启）、bronze（机器自评，仅失败分析）、raw（无标签语义）；分层语义由加载器单点实现，过滤语义（如「silver 及以上」） SHALL 与现行 finetune 飞轮一致。bronze 与 silver SHALL 永不作 ground truth 或 reward——守卫 SHALL 在导出器单点实现，任何按真值用途取 bronze/silver 的请求即报错拒绝，绕过导出器直读原表 SHALL 被登记为已知风险并纳入文档与代码评审检查项。

**确认产出落在 `silver`**（2026-11-21 修订）：域内提案被确认后写入的知识单元 SHALL 为 `silver`，不论确认者是智能体还是人；`raw` 保留给无标签的批量摄入，MUST NOT 作为确认产出的档位。一条单元从 `silver` 升到 `gold` SHALL 走升档阶梯并携带 reviewer 身份，MUST NOT 由确认动作直接产出 `gold`。

这条把「人签」落在**升档**而不是**确认**上：判断仍然须人，但人判断的对象是「这条事实够不够格当真值」，不是「这条提案能不能进本体」。

#### Scenario: 真值守卫拒绝 bronze
- **WHEN** 下游脚本经导出器按 ground-truth/reward 用途请求 bronze 物料
- **THEN** 导出器报错拒绝并指明 tier 违规，不返回任何 bronze 行

#### Scenario: 分层互斥
- **WHEN** 任一物料尝试同时携带或写入两个 tier 值
- **THEN** 写入被拒绝（422 如实指明），存量数据无多值 tier

#### Scenario: 确认产出 silver 而非 raw
- **WHEN** 任一提案被确认（确认者为智能体或人）
- **THEN** 写入单元 `tier='silver'`，且该单元的 `operator` 记录确认者身份

#### Scenario: silver 升 gold 须 reviewer
- **WHEN** 对一条 `silver` 单元发起升档且未提供 reviewer 身份
- **THEN** 升档被拒，单元保持 `silver`

## ADDED Requirements

### Requirement: 档位阶梯覆盖全部可确认类型

升档阶梯 SHALL 覆盖域内**所有可被确认产出**的知识单元类型，MUST NOT 只对其中的一个子集生效。阶梯的每一级 SHALL 可从一个已知档位到达下一级，MUST NOT 存在「进了某个档位就再也升不上去」的类型。

`raw` SHALL 是阶梯的起点（`raw → silver → gold`），使批量摄入的内容与确认产出的内容走同一条上升路径。`bronze` 保留机器自评语义（仅失败分析），不参与这条主阶梯。

#### Scenario: 任何被确认的类型都能升到 gold
- **WHEN** 某类型经确认产出 `silver` 单元
- **THEN** 该类型可经升档阶梯到达 `gold`，不存在「不在阶梯上」的类型

#### Scenario: raw 可起步升档
- **WHEN** 对一条 `raw` 单元发起升档
- **THEN** 允许升到 `silver`，不再被「raw 不在阶梯上」拒绝

#### Scenario: 不存在不可达档位
- **WHEN** 检视阶梯定义
- **THEN** 每一级都有一条从起点到它的路径，且没有类型被排除在阶梯外
