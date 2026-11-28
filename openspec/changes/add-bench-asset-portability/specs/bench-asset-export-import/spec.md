# Spec Delta

## Purpose

让知验台的模板与尺子资产可以离开本实例、在另一个实例落回，且往返可验证：导出的信封与导入后的资产逐字段相等，digest 与同内容发布一致，复制件携带可追血缘。

## ADDED Requirements

### Requirement: 按资产类别导出便携信封

系统 SHALL 提供导出通道，按 `ontology-template` / `vocabulary-release` / `ruler-set` / `gold-set` / `eval-suite` 五类之一产出一个便携信封。导出 SHALL 只读，MUST NOT 改变任何资产状态或产生发布行。导出结果 SHALL 携带 `digest`、`manifest_shape`、逐文件 sha256 清单与（复制件）血缘字段。

#### Scenario: 导出官方模板

- **WHEN** 管理员导出一个 `ontology-template`
- **THEN** 返回包含完整模板 schema 与 digest 的信封，模板行、版本与发布历史均不变

#### Scenario: 导出未注册的资产类别被拒

- **WHEN** 请求导出一个本实例未注册的类别
- **THEN** 拒绝并列出本实例已注册的类别，不产生空信封

### Requirement: 导入先校验后写入

系统 SHALL 在写入任何行之前完成：信封 digest 校验、逐文件 sha256 校验、资产类别校验、复制件的加法校验。任一失败 SHALL 以结构化错误整体拒绝并指名字段或文件，MUST NOT 留下部分资产或临时文件。

#### Scenario: 失配信封零写入

- **WHEN** 导入一个被篡改的信封
- **THEN** 返回结构化拒绝，模板/尺子/金集行数不变

#### Scenario: 同一信封重复导入幂等

- **WHEN** 对同一信封连续导入两次
- **THEN** 第二次不新增资产行，返回与首次相同的 digest 与目标标识

### Requirement: 导入不自动建域也不自动发布

导入一个模板 SHALL 只创建模板记录；MUST NOT 创建域、MUST NOT 发布任何资产、MUST NOT 绑定消费者。建域与发布仍是独立的显式动作。

#### Scenario: 导入模板后域数不变

- **WHEN** 导入一个 `ontology-template` 信封
- **THEN** 模板可见，域列表与发布列表与导入前相同

### Requirement: 复制件携带可追血缘并受加法约束

导入的模板若声明 `lineage.upstream`，系统 SHALL 持久化 `derived_from`、`fork_diff` 与上游 digest；并 SHALL 对照上游词表执行加法校验：新增允许、`superseded_by` 退役允许，删除或改名任一上游条目 SHALL 被拒绝并指名。

#### Scenario: 删除上游条目被拒

- **WHEN** 导入一份缺失上游某个实体类型的 fork 模板
- **THEN** 拒绝并指名该实体类型，模板未被创建

### Requirement: 机器资产面使用受限消费者而非管理身份

资产导出/导入 SHALL 有一个机器通道，凭据为登记消费者（kind 为部署资产档），MUST NOT 要求 Logto 管理身份。该凭据 SHALL 只能调用资产面，MUST NOT 获得成员、发布、提案、确认或任何其它管理能力。域级资产（尺子/金集）SHALL 要求目标域在该凭据的绑定域内。

#### Scenario: 通用机器凭据被拒

- **WHEN** 一个 kind 为普通机器档的消费者请求导出资产
- **THEN** 拒绝并说明需要部署资产档，不产生信封

#### Scenario: 越域导出被拒

- **WHEN** 部署资产凭据请求导出未绑定域的尺子集
- **THEN** 拒绝并报明该域不在绑定范围

### Requirement: v1 可导入类别有明确边界

本版本 SHALL 可导入 `ontology-template` 与 `ruler-set` 两类；其余三类（`vocabulary-release`、`gold-set`、`eval-suite`）SHALL 可导出，但其导入 SHALL 被拒绝并说明原因（需要信封无法命名的目标上下文），MUST NOT 静默跳过或猜测目标。

#### Scenario: 导出-only 类别导入被明确拒绝

- **WHEN** 导入一个 `gold-set` 信封
- **THEN** 拒绝并说明该类别在本版本仅可导出，不写入任何行

### Requirement: 导出受部署开关与审计约束

导出与导入通道 SHALL 由部署配置显式开启，默认关闭并返回可读的关闭原因。成功的导入 SHALL 留一条只增的审计记录（谁、何时、信封 digest、资产类别、目标标识）；失败的导入 MUST NOT 留成功记录。

#### Scenario: 默认关闭

- **WHEN** 在未开启该通道的部署请求导出
- **THEN** 拒绝并说明该通道未开启，不返回信封

#### Scenario: 失败不留审计成功记录

- **WHEN** 一次导入因 digest 失配被拒
- **THEN** 审计里没有该次导入的成功记录

### Requirement: digest 只有一份实现

导出与导入使用的规范序列化与摘要 SHALL 来自 `fd-ontology-kernel`，MUST NOT 在本仓另行实现。

#### Scenario: 与发布 digest 相等

- **WHEN** 导出某本体内容并在本实例发布同内容
- **THEN** 信封 digest 与发布 digest 逐字节相等
