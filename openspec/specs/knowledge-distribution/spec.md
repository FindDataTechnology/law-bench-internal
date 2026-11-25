# knowledge-distribution Specification

## Purpose

平台与消费者的唯一细线：版本化发布（digest+changelog）、消费者登记、机器拉取面。松耦合铁律——消费者拉取快照落本地独立处理，平台不依赖消费者反向实时输入。总纲见 `docs/knowledge-platform-blueprint.md`（C3）。

## Requirements

### Requirement: 版本化发布

领域负责人（或平台管理员）SHALL 可将其成员域的本体内容发布为不可变版本快照：单调发布版本号、digest（规范 JSON 的 sha256，键序归一、排除生成时间戳）、全量 manifest（模板版本锚定、实体与关系全量、排除软删项）；

#### Scenario: 发布产生可拉取版本

- **WHEN** 领域负责人对其域执行发布且域内有词表内实体与关系
- **THEN** 产生新发布版本（版本号单调、digest 稳定、manifest 含实体与关系全量并锚定模板版本），软删项不出现在 manifest

#### Scenario: 同内容重复发布幂等

- **WHEN** 内容零变更时再次执行发布
- **THEN** 返回既有版本与既有 digest，不产生新快照行

#### Scenario: 空域发布拒绝

- **WHEN** 对没有任何词表内内容的域执行发布
- **THEN** 发布被拒并报明域内无内容，不产生空版本

#### Scenario: 换底不改已发布 digest

- **WHEN** 对换底前落库的任一发布快照按 manifest 重算 digest
- **THEN** 重算值与库中 digest 逐字节相等（等价测试 `tests/test_distribution_kernel.py` 22 条 + 内核 golden 6 例钉住）

#### Scenario: 形状未声明或不受支持即拒

- **WHEN** 适配方声明的 manifest 形状不在内核支持的集合内（当前支持 1=id 寻址、2=键寻址）
- **THEN** 内核在构造时即拒绝并报明「声明不受支持」，而不是按默认形状猜着跑

### Requirement: 幂等（静默返回既有版本，不产生新行） (#1)

同 digest 重复发布 SHALL 幂等（静默返回既有版本，不产生新行）；

#### Scenario: split-out behaviour 1
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 不可改写不可删除 (#2)

快照发布后 SHALL 不可改写不可删除；

#### Scenario: split-out behaviour 2
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 可对账（发布的每条内容可回指其事件史） (#3)

变更事件流与发布流水 SHALL 可对账（发布的每条内容可回指其事件史）。

#### Scenario: split-out behaviour 3
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 由共享内核持有，本面 MUST NOT 再有一份自己的实现——两面各写一遍，一旦对「同一内容」判定不一致，跨面比对即失去意义 (#4)

规范形态（条目键集、排序键、类型归一）与 digest 配方 SHALL 由共享内核持有，本面 MUST NOT 再有一份自己的实现——两面各写一遍，一旦对「同一内容」判定不一致，跨面比对即失去意义。

#### Scenario: split-out behaviour 4
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 为**键寻址形状**（条目以 `kind` + `external_key` 寻址、关系以两端键寻址），形状版本与所遵循的内核契约版本 SHALL … (#5)

发布的 manifest SHALL 为**键寻址形状**（条目以 `kind` + `external_key` 寻址、关系以两端键寻址），形状版本与所遵循的内核契约版本 SHALL 随发布物一并声明；

#### Scenario: split-out behaviour 5
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 拒绝而不是猜测 (#6)

声明不受支持时系统 SHALL 拒绝而不是猜测。

#### Scenario: split-out behaviour 6
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 位于载荷之外，MUST NOT 进入 digest——否则每次引入形状都会作废已发布的所有 digest (#7)

形状版本 SHALL 位于载荷之外，MUST NOT 进入 digest——否则每次引入形状都会作废已发布的所有 digest。

#### Scenario: split-out behaviour 7
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 变更日志

每次新发布 SHALL 相对上一发布版本产生 changelog（新增/删除/变更三类条目，实体与关系逐条，变更条目含字段级差异摘要）；首版 changelog SHALL 记为初始清单；消费者可经拉取面获取任一版本的 changelog。

#### Scenario: 二版携带差异
- **WHEN** v1 发布后专家新增一条实体并修改一条关系，负责人发布 v2
- **THEN** v2 changelog 含 1 条新增实体条目与 1 条变更关系条目（字段级摘要），v1 changelog 保持初始清单不变

### Requirement: 消费者登记与机器凭据

平台管理员 SHALL 以登记制准入消费者（名称、绑定域列表、机器令牌——仅存 sha256 哈希，明文只在创建时展示一次）；消费者 SHALL 只能拉取其绑定域的已发布版本；令牌 SHALL 可吊销（吊销即时失效）；凭据纪律沿平台既有脱敏规则（日志与错误永不携带明文）。

消费者 SHALL 按其登记种类获得对应的写面集合：`machine` 只读已发布制品；`fleet` 额外可提交提案、回写运行台账，**以及回写评测结论**。写面的身份 SHALL 由凭据派生，MUST NOT 取自请求体里的自称。

消费者登记 SHALL 在「把某主体加入某域」的统一读面里作为 `kind=fleet` 的一类出现，其域绑定 SHALL 与该读面同源，MUST NOT 由第二个口径另算。

#### Scenario: 登记与吊销

- **WHEN** 管理员为消费者 wire 登记绑定域 legal 并签发令牌，随后吊销该令牌
- **THEN** 吊销前该令牌可拉取 legal；吊销后同令牌请求被拒（403 如实报「令牌已吊销」）

#### Scenario: 只有 fleet 能写

- **WHEN** 一个 `machine` 种类消费者调用结论回写
- **THEN** 403，且报明是种类不支持而非凭据无效

#### Scenario: 写面身份来自凭据

- **WHEN** 回写请求体里的提交方与令牌所属登记不一致
- **THEN** 403，MUST NOT 采信请求体自称

#### Scenario: 舰队登记携带稳定标识

- **WHEN** 管理员为一支舰队登记并绑定域 legal
- **THEN** 该登记的种类为 `fleet`、携带舰队标识与绑定域，且提案与运行回写可用该标识反查到这条登记

#### Scenario: 同一舰队不得重复登记

- **WHEN** 对已登记且未吊销的舰队再次登记
- **THEN** 被拒并指向既有登记，不产生第二条有效凭据

### Requirement: 机器拉取面

平台 SHALL 提供机器通道拉取端点（`GET /api/v1/distribution/{domain_key}/ontology`，头 `X-Consumer-Token`），支持指定版本或缺省最新，json/yaml 双格式（`format` 参数，缺省 json）；载荷 SHALL 含 domain、模板版本锚定、发布版本与 digest、实体与关系全量（含 tier/sensitivity 标记与关系结构化 from/to）；鉴权 SHALL 三态如实区分：无凭据 401、令牌未登记或已吊销 403（报明）、令牌有效但域不在其绑定范围 403（报明）；拉取面 SHALL NOT 依赖 Logto 交互会话。

平台 SHALL 另提供机器通道的结论回写端点（`POST /api/v1/distribution/{domain_key}/runs`），接受一次运行回执并可选携带一条完整评测结论身份。其鉴权 SHALL 沿用同一枚令牌与同一套三态区分，并额外执行三道写入门：

1. **身份门** — 调用主体由凭据派生；请求体里的提交方只能替自己的登记说话。
2. **尺子可见性门** — 结论所依据的尺子 SHALL 在该被评域的有效标准范围内可见；不可见即拒，MUST NOT 落一条无人能复现的结论。
3. **层级门** — 依据模板标准判定 SHALL 对任何已登记写者开放；依据域自有标准判定 SHALL 要求写者在该域具备足够角色（机器主体以其次高角色为上限）；改写既有结论 SHALL 无任何路径。

回执 SHALL 分开表达「运行已入账」与「结论已入账」。结论未能入账时 SHALL 如实说明（含「本版本尚无结论写面」这一情形），MUST NOT 让调用方把「运行记上了」读成「结论也记上了」。

结论写入 SHALL 只追加：系统 MUST NOT 提供就地改写既有结论的路径。

#### Scenario: 消费者拉取最新版

- **WHEN** 已登记消费者以有效令牌请求其绑定域的最新本体
- **THEN** 收到 200 载荷（发布版本、digest、实体与关系全量含档位标记），格式为请求的 json 或 yaml

#### Scenario: 指定历史版本

- **WHEN** 消费者请求 v1 而当前已到 v2
- **THEN** 收到 v1 快照内容与 v1 digest，与 v1 发布时的 digest 逐字节一致（快照不可变）

#### Scenario: 越域拉取拒绝

- **WHEN** 绑定域仅 legal 的消费者令牌请求 domain_key=fin
- **THEN** 403 报明该域不在绑定范围，fin 的任何内容零出现

#### Scenario: 三态鉴权如实区分

- **WHEN** 无令牌 / 令牌已吊销 / 令牌有效但域不在绑定范围 三种情形各调用一次结论回写
- **THEN** 分别得到 401 / 403（报明吊销）/ 403（报明域不在范围）

#### Scenario: 尺子不在域内可见即拒

- **WHEN** 回写携带的尺子在该域有效标准里不可见
- **THEN** 拒绝并报明「尺子不可见」，MUST NOT 落库

#### Scenario: 回执区分运行与结论

- **WHEN** 回写携带完整结论身份并成功落库
- **THEN** 回执同时标明运行入账与结论入账；若结论段缺失，回执 MUST NOT 呈报整体成功

#### Scenario: 结论不可改写

- **WHEN** 调用方试图对同一条已落库结论提交不同内容
- **THEN** 拒绝，既有结论字节不变

### Requirement: 发布面向词表执法的契约锚

发布 manifest 中的实体与关系 SHALL 携带发布时的域模板版本锚定；关系键 SHALL 沿用创作面的确定性键约定（`{from_key}->{kind}:{to_key}`），使消费者可据以重建身份对齐；模板词表或键约定的变更 SHALL 出新发布版本而非就地改写历史快照。

#### Scenario: 消费者侧身份重建
- **WHEN** 消费者解析 manifest 中的关系条目
- **THEN** 依据关系键约定与结构化 from/to 可重建两端身份，无需第二套身份解析逻辑
