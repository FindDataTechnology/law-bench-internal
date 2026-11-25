## ADDED Requirements

### Requirement: 主体以种类为数据的统一接纳

系统 SHALL 提供「把某主体加入某个域」的唯一写入口与唯一读面，主体种类 SHALL 是数据（列值），MUST NOT 是代码分支或前缀字符串推断。

`kind` SHALL 是闭集 `{user, agent, fleet}`。三个种类 SHALL 各自映射到它所依据的既有登记，MUST NOT 为接纳另建一张并行的成员表：

- `user` / `agent` → 域成员登记（含角色）
- `fleet` → 消费者登记与该登记绑定的域集合

未在闭集内的 `kind` SHALL 被拒绝并列出闭集。

#### Scenario: 三种主体同一个答案

- **WHEN** 查询域 `legal` 的成员
- **THEN** 一次调用即返回该域的用户、智能体与舰队，每条带自己的 `kind`、引用与角色（舰队无角色，角色为 null 而非空串）

#### Scenario: 未知种类被拒

- **WHEN** 调用方传 `kind="team"`（不在闭集）
- **THEN** 拒绝并列出闭集，MUST NOT 静默归入某个已知种类

### Requirement: 同类由所锚定的模板版本表达

一个域 SHALL 通过其所锚定的模板版本表达「同类」：锚定同一模板（或同一模板的继承链）的域 SHALL 被视为同类。

系统 MUST NOT 另造一套「域类型」枚举来描述同类——模板继承链已经是它的表达，第二个口径会与它漂移。

#### Scenario: 同模板两域是同类

- **WHEN** 两个域各自锚定同一模板版本
- **THEN** 系统按同类对待它们（标准与词表可比），无需任何额外的类型标记

#### Scenario: 子域是父域的特例

- **WHEN** 域 `legal/contract-review` 声明 `extends` 父模板
- **THEN** 它的有效标准 SHALL 是父链并集（父项只读），其「同类」包含父域

### Requirement: 准入是资格判据不是记录页

接纳某主体进域 SHALL 由域所有者执行，且 SHALL 校验主体种类所允许的角色上限。

机器主体（`agent`）SHALL NOT 获得域内最高治理角色；其上限 SHALL 是次高角色。舰队（`fleet`）MUST NOT 持有域内角色，其权限只来自登记里绑定的域集合。

开域与归档域 SHALL 是仅人类可执行的动作，机器身份 MUST NOT 执行。

#### Scenario: 机器不得持有治理角色

- **WHEN** 一个 `agent:` 身份被要求授予最高域角色
- **THEN** 拒绝，并如实报出合法路径（作为成员 + 次高角色）

#### Scenario: 舰队无角色

- **WHEN** 查询某域内的舰队成员
- **THEN** 每条的角色为空（null），系统 MUST NOT 用一个默认角色填充它

### Requirement: 准入留痕且可撤销

每次接纳 SHALL 留下可查的留痕：谁在何时把哪个主体以什么角色加入哪个域。

撤销 SHALL 只影响此后，MUST NOT 删除既有留痕行——成员历史是审计事实。

#### Scenario: 移除是历史不是删除

- **WHEN** 某成员被移出域
- **THEN** 读面不再列出该活跃成员，且它的加入/移除留痕仍可查

### Requirement: 准入抽象不复制既有判据

接纳的资格判据 SHALL 只有一份实现，读面与写面 MUST NOT 各写一遍校验。

系统 MUST NOT 在不同入口对同一主体给出不同的「是否在域内」答案。

#### Scenario: 两个入口同一个答案

- **WHEN** 页面读面与机器读写面同时判定某舰队是否在某域内
- **THEN** 两者给出相同答案，差异必须为零
