# domain-data-eval Specification

## Purpose
行业数据评测：按**域**对活跃知识单位跑确定性 checker，结论带域归属与 verdict 身份，从而让一个行业域「被评测过」这件事在域矩阵、运行列表与机器读面上都可见、可核。数据通道（`channel='data'`）此前跑得出结论，却因缺域归属而在域作用域里读不到；本能力补的是那条归属与按域触发。

## Requirements

### Requirement: 数据评测结论必须带域归属

以数据通道产出的评测结论 SHALL 填 `rubric_domain_id`，值来自其 `rubric_name` 在尺子表里**唯一**解析到的归属域。

`rubric_name` 零处或多处命中归属域时 MUST 留 NULL，MUST NOT 猜测归属或取「第一个」。理由：给一条无来源的结论伪造 provenance，比缺归属更糟，且会让域作用域读到一个它并不拥有它的结论。

#### Scenario: 唯一命中则回填

- **WHEN** 某数据通道结论的 `rubric_name` 在尺子表里恰好对应一个归属域
- **THEN** 该结论的 `rubric_domain_id` 等于那个域，且该域的评测柱能读到它

#### Scenario: 多命中留空

- **WHEN** 某 `rubric_name` 对应两个不同域的尺子
- **THEN** 结论落库时 `rubric_domain_id` 为 NULL，不任选其一

### Requirement: 按域跑数据评测

系统 SHALL 提供按域触发的一次数据评测：对某域命名空间下**活跃**（未软删）的、由该域 pack 声明了 checker 的 kind 的单位，逐单位跑 checker，聚合成一条结论。

结论 SHALL 沿用既有 verdict 身份（`subject_kind` / `subject_version` / `ruler_kind` / `ruler_key` / `ruler_digest` / `gate='regression'` / 三态 `outcome`），MUST NOT 另写一套身份计算。

该域没有任何可评单位时，结论 SHALL 为 `inconclusive`，MUST NOT 记为 `pass` 或 `fail`。

#### Scenario: 有单位则出三态结论

- **WHEN** 某域有 23 条 `account` 单位、该 kind 注册了 checker
- **THEN** 评测落一条 `channel='data'`、带域归属的结论，`n_criteria` 等于单位数×checker 数，`outcome` 按「全过=pass / 其余=fail / 空集=inconclusive」取值

#### Scenario: 空域判不出来

- **WHEN** 某域没有任何活跃可评单位
- **THEN** 结论 `outcome='inconclusive'`，页面显示「没有可评单位」而不是「全部通过」

### Requirement: 行业 checker 必须先在真数据上证明区分度

一个行业 checker 只有在**生产真数据**上被证明既能通过一部分、又能否决一部分时，才 SHALL 上线为评测判据。

在真数据上恒真的 checker MUST NOT 作为判据保留——它不区分任何东西，全绿与没有这条规则在信息上等价。恒真规则 SHALL 删除或改写成有区分度的判据。

#### Scenario: 全绿规则被拒

- **WHEN** 某拟新增 checker 在生产真数据上对所有单位都返回通过
- **THEN** 该 checker 不作为判据合入；记录其无区分度的事实

#### Scenario: 有区分度的规则上线

- **WHEN** 某 checker 在生产真数据上既有通过、又有否决
- **THEN** 它作为判据合入，且验收报告记录其通过/否决计数作为区分度证据

### Requirement: 数据评测的触发面按域角色判定

域内触发数据评测的入口 SHALL 仅对持该域 `lead` 及具备 `content:write` 的身份开放。

入口 SHALL 报告三态结局与通过比，MUST NOT 把「没有可评单位」呈现成「全部通过」。

#### Scenario: 无权限不给按钮

- **WHEN** 一个只读成员打开域的评测资产区
- **THEN** 看不到「跑一次数据评测」动作，或看到它标注所需角色

#### Scenario: 跑完如实报比

- **WHEN** 负责人触发一次成功的数据评测
- **THEN** 页面显示「通过 N / 共 M」与结局三态之一，且该结论立即出现在同页运行列表
