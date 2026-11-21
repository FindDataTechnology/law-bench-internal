# bench-platform Specification

## Purpose
定义知验台（全域知识沉淀 × 评测平台）的内核行为契约：知识单元类型化、域包插拔、双通道评测、溯源四层守卫、meta-eval、柏讯实体升格契约与开源切分边界。内核领域无关，法律垂类是第一个域包。

## Requirements

### Requirement: 知识单元类型化

语料库的存储单元 SHALL 泛化为带 `kind` 的知识单元（如 clause/entity/relation/fact/indicator/qa-pair），clause 为第一个 kind 且存量条款数据零迁移语义变化；评测、复核、组装、微调导出的读写面 SHALL 按 kind 泛化并保持对既有 clause 行为逐字节等价（既有测试套件全绿且断言口径不变）。

#### Scenario: 新增 kind 不改内核
- **WHEN** 以新 kind（如 indicator）写入一条知识单元并对其发起评测
- **THEN** 语料库、评测运行、复核流程均接受该 kind，内核代码无需为该 kind 增改分支

#### Scenario: 法律垂类零回归
- **WHEN** 泛化重构合入后运行既有全量测试套件
- **THEN** 全部测试通过且断言口径与重构前一致，法律域既有行为（组装/评测/复核/导出）无可观测变化

### Requirement: 域包插拔接口

平台 SHALL 以域包（domain pack）承载领域资产：每域包声明其知识单元 kind 集、语料适配器、rubric 包、评测套件与（可选的）确定性校验器；内核 SHALL NOT 含任何领域专有逻辑或领域常量；新增一个领域 SHALL NOT 修改内核代码。法律域包的组件（条款种子、法规目录、引用核检）SHALL 全部迁入域包边界内。

#### Scenario: 新域包接入
- **WHEN** 以域包声明文件接入一个新领域（含语料适配器与 rubric 包）并注册
- **THEN** 该域的知识单元入库、评测与复核全链可用，且本次接入的变更集中不触碰 `src/bench`（内核）内任何文件

#### Scenario: 内核领域无关
- **WHEN** 在内核源码树中检索领域专有名词（合同类型、法条、法条引用等法律常量）
- **THEN** 命中仅存在于法律域包目录与其数据文件，内核源码零命中

### Requirement: 双通道评测

评测对象 SHALL 分两通道：文本对象（草稿/答案/报告/条款）走 LLM-judge × rubric × criteria 通道；数据对象（数据集/指标/图谱快照/AI 取数回答）走确定性校验通道（行数/期数/对账/漂移/基线比对，校验器由域包声明）。两通道 SHALL 共用同一套运行记录、compare、趋势与人工复核机器；每条评测记录 SHALL 如实标注其通道。

两通道的每条运行记录 SHALL 同时携带被评对象地址（`subject`：种类 + 键 + 版本）与尺子地址（`ruler`：种类 + 键 + digest），并符合 `eval-verdict-ledger` 规定的门与结局词汇；通道 MUST NOT 决定记录形状——两条通道落进同一张表、同一组字段，只在通道字段上不同。

#### Scenario: 数据对象确定性评测
- **WHEN** 对一个数据对象（如某指标数据集的快照）发起评测，其域包声明了确定性校验器
- **THEN** 评测运行逐条执行校验器并落 per-check verdict（数值级对/错），不调用 LLM judge，限流与模型故障不影响其结果

#### Scenario: 数据 QA 金集评测 AI 用数
- **WHEN** 以数据 QA 金集（题目绑定真实数据集与期望结果）对 AI 取数/答数对象发起评测
- **THEN** 每题按期望结果判定正误并落可追溯记录（题目→数据集→期望→实际→verdict），可进入 compare 与趋势

#### Scenario: 通道如实标注
- **WHEN** 查询任一评测运行的记录
- **THEN** 记录含通道字段（text/data），下游聚合与展示按通道区分，不混淆

#### Scenario: 两通道记录同形
- **WHEN** 比较一条文本通道与一条数据通道的运行记录
- **THEN** 两者的对象地址、尺子地址、门与结局字段同形，可在同一张趋势图上按对象聚合

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
### Requirement: meta-eval（尺子的尺子）

平台 SHALL 对判官与评测套件本身做度量：judge 对 gold 的校准（按置信分档的准确率与单调性）与评测套件的漂移检测 SHALL 为一等运行记录，与被评对象共用趋势机器；判官校准结果 SHALL 随 judge 模型与提示词版本留痕。现行判官（all_pass 仅 31%、存在结构性误读）SHALL 作为第一个校准对象，其结构性误读修复前 SHALL NOT 被任何域包声明为可信 gold 信号源。

校准运行 SHALL 以 `eval-verdict-ledger` 的结论形态落库：被评对象为「该判官的模型 + 提示词版本」，尺子为该次校准所用 gold 集（携带其 digest），门为 `calibrated`。判官的校准状态 SHALL 由这些结论行推导，MUST NOT 另立一份「是否已校准」的独立存储。

#### Scenario: judge 校准运行
- **WHEN** 对某 judge（模型+提示词版本）在指定 gold 集上发起校准运行
- **THEN** 产出按置信分档的准确率矩阵与单调性结论，落库可查，纳入该 judge 的版本档案

#### Scenario: 未校准判官受限
- **WHEN** 某域包尝试将未通过校准（或校准失败）的 judge 声明为 gold 信号源
- **THEN** 声明被拒绝并如实指明「judge 未通过校准」，不产生该域的 gold 标注

#### Scenario: 校准结论携带 gold 集 digest
- **WHEN** 一次校准运行落库
- **THEN** 其尺子地址携带该 gold 集的 digest，换 gold 集后新旧校准结论不可直接相比

#### Scenario: 校准状态由结论推导
- **WHEN** 某判官被问到「是否已校准」
- **THEN** 答案取自其最近一条 `calibrated` 门结论的结局，MUST NOT 来自配置项或人工声明

### Requirement: 柏讯实体升格契约

平台 SHALL 从 fd-wire entity-layer 读取实体/关系声明作为 **seed 升格原料**，按 raw→bronze→silver→gold 审核流升格。

#### Scenario: 实体升格入库
- **WHEN** 一次性导入 wire 实体声明并经机器预标注（bronze）与人工核验（gold）
- **THEN** 知验台产生带 wire 源引用的 gold 实体，seed 身份可回指 wire；平台发布的本体版本以该 gold 内容为权威形态

#### Scenario: 重复导入幂等但不是持续同步
- **WHEN** 对同一 wire 图谱连续导入两次，随后 wire 一周无变化
- **THEN** 第二次导入零新增行；平台创作、评审与发布流程在该周内照常进行，不报同步停滞

#### Scenario: gold 回写带档
- **WHEN** gold 实体/关系回写 wire
- **THEN** 回写载荷含 sensitivity/tier 标记，wire 侧 ACL 与舰队可直接消费；回写失败如实报错且知验台侧状态不误标「已回写」

#### Scenario: 草稿不触发回写
- **WHEN** 一条单元仍是 bronze（机器预标注）或尚未经人工核验
- **THEN** 不产生任何指向 wire 的写请求

#### Scenario: 发布权威源
- **WHEN** 消费者（含 wire）经分发面拉取平台已发布本体
- **THEN** 快照以平台发布版本为权威（digest 锚定），消费者本地处理不构成第二权威源；wire 本地存储与平台发布版本的分歧按消费者侧本地版本化处理（对账依 pull 面）

### Requirement: 是**一次性**操作：重复导入幂等（零新增行、不 bump 更新时间），但平台 MUST NOT 以定时任务或常驻通道持续镜像 … (#1)

seed 导入 SHALL 是**一次性**操作：重复导入幂等（零新增行、不 bump 更新时间），但平台 MUST NOT 以定时任务或常驻通道持续镜像 wire 的变化——平台的工作 MUST NOT 因为 wire 停止变化而停止。 **wire 是 seed 原料源，已发布本体的权威源是平台**（蓝图 §六）。 平台发布面是全部消费者的唯一权威分发路径；

#### Scenario: split-out behaviour 1
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 形成第二权威 (#2)

wire 侧本地存储与平台发布版本的分歧按消费者侧本地版本化处理，MUST NOT 形成第二权威。

#### Scenario: split-out behaviour 4
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 保证： - seed 阶段 wire 为原料身份的参照键（平台 … (#3)

升格流水线 SHALL 保证： - seed 阶段 wire 为原料身份的参照键（平台 KU 以 wire 源引用与 `external_key` 回指 seed）；

#### Scenario: split-out behaviour 5
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 只经 crosswalk 表达（见 `bench-wire-seam`），MUST NOT 靠复制词表或以 … (#4)

- 两层之间的语义同一性 SHALL 只经 crosswalk 表达（见 `bench-wire-seam`），MUST NOT 靠复制词表或以 wire 键作为平台主键来「实现对齐」；

#### Scenario: split-out behaviour 6
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 附带 `sensitivity`/`tier` 标记（面向 seed 源的档位回写，供其 ACL … (#5)

- gold 回写 wire 时 SHALL 附带 `sensitivity`/`tier` 标记（面向 seed 源的档位回写，供其 ACL 与舰队消费）；

#### Scenario: split-out behaviour 7
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 单向——只承载平台已确认的标注，MUST NOT 承载 wire 实体的结构性变更，且机器草稿 MUST … (#6)

回写方向 SHALL 单向——只承载平台已确认的标注，MUST NOT 承载 wire 实体的结构性变更，且机器草稿 MUST NOT 触发回写；

#### Scenario: split-out behaviour 8
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 可追溯（每条 gold 可回指 wire 源声明与审核人） (#7)

- 升格与回写全程 SHALL 可追溯（每条 gold 可回指 wire 源声明与审核人）； 发布契约见 `knowledge-distribution`。

#### Scenario: split-out behaviour 9
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: 开源切分边界

公共仓 SHALL 仅含内核、域包接口与法律域包；内部域包（柏讯连接器、内部语料、gold 数据集、客户数据）SHALL 存于内部仓（law-bench-internal）。公共仓 CI SHALL 增加泄露扫描：内部仓路径引用、凭据形态、客户数据样本 SHALL 令构建失败；公共仓文档中的能力宣称 SHALL 与公共仓实际可运行面一致。

#### Scenario: 泄露扫描拦截
- **WHEN** 公共仓某次提交引用内部域包路径、内嵌凭据或包含客户数据样本
- **THEN** CI 扫描失败并逐条指明违规文件与处置方式，不产出镜像

#### Scenario: 公共面宣称一致
- **WHEN** 公共仓 README 或文档宣称某能力
- **THEN** 该能力在公共仓内（或经其声明的公开依赖）可运行，内部仓专属能力须显式标注「内部」

### Requirement: 启动期清理失败须降级，不得使应用退出

平台在启动时执行的清理步骤（如回收上一个进程遗留的运行任务）SHALL 在失败时降级：
记录可诊断的日志并继续启动，MUST NOT 因清理失败而中止应用启动。

启动路径上的每一处日志调用 SHALL 使用本模块已定义的 logger。

#### Scenario: 清理抛异常时应用仍可用

- **WHEN** 启动期的遗留任务清理因数据库连接或约束冲突抛异常
- **THEN** 应用记录告警并完成启动，各页面可正常访问

#### Scenario: 降级分支里的符号必须已定义

- **WHEN** 清理的 `except` 分支引用一个模块级符号（如 logger）
- **THEN** 该符号在模块导入时已定义，不依赖正常路径是否执行过

> 实证：2026-11-21 `src/web/app.py` 的 `_reap_stale_generation_jobs` 在 `except`
> 分支使用未定义的 `logger`，正常启动与 CI 全绿；一旦清理失败即
> `NameError: name 'logger' is not defined` → `Application startup failed. Exiting.`

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
