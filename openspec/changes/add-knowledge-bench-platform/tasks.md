## 1. P0 · 合流与奠基

- [ ] 1.1 造 donor 白名单：对 law-bench-server 拷贝的 `contracts/`、`paper/`、README 差异逐文件列示审查，明确「无凭据文件」（`.env`、`ssh-config.json`、`.git` 及任何 config/密钥永不在列）；清单落档于本 change 根 `donor-whitelist.md`，每行含审阅结论（verify: 清单文件存在且逐行有结论）
- [ ] 1.2 按白名单拷入正身仓，单提交（verify: `git show --stat HEAD` 仅含白名单路径，无凭据形态文件）
- [ ] 1.3 law-bench-server 标记为只读供体（目录内注记：不再迭代，仅资产来源）（verify: 注记文件存在）
- [ ] 1.4 确立基线：合流提交后跑全量 pytest，存档基线输出（verify: 基线全绿且输出文件留档，供 2.2 对比断言口径）

## 2. P0 · 内核抽取（知识单元泛化）

- [ ] 2.1 知识单元 `kind` 幂等加列 + 存量回填 `clause`（verify: schema 幂等自建测试过；存量条款行 kind 计数 = 条款总数）
- [ ] 2.2 建 `src/bench` 内核包：语料库/评测/复核/组装/导出读写面按 kind 泛化，内核不含法律常量（verify: 既有 pytest 全绿且断言口径与 1.4 基线一致，未改任何既有断言）
- [ ] 2.3 `law_catalog`、`clause_seeds`、法律引用组件迁入 `packs/legal`，经域包声明接入（verify: 法律全链 组装→评测→复核→MCP 工具→公共 API 行为等价；MCP 37 工具面只增不减）
- [ ] 2.4 CI 内核领域无关断言：法律常量在 `src/bench` 源码树零命中（verify: 扫描脚本入 CI 且通过）
- [ ] 2.5 数据通道：评测运行加通道字段（text/data）+ 确定性校验器注册表接口（verify: 样例数据对象评测全程未调 judge 且 verdict 落库；注入限流/模型故障不影响数据通道结果）
- [ ] 2.6 真值守卫从 finetune 导出器扩展到全平台导出面（verify: bronze/silver 按 ground-truth/reward 用途请求被单点守卫拒绝（新增测试）；既有 finetune 守卫测试不回归）

## 3. P0 · 开源切分

- [ ] 3.1 内部仓 law-bench-internal 承接内部资产与柏讯连接器骨架（verify: 内部仓测试绿；公共仓源码对内部模块引用零命中）
- [ ] 3.2 公共仓 CI 泄露扫描 fail-closed：内部仓路径引用/凭据形态/客户数据样本令构建失败（verify: 注入违规样本 CI 失败并逐条指明，移除后恢复绿）
- [ ] 3.3 公共仓 README/文档能力宣称与可运行面对齐，内部专属能力标注「内部」（verify: 能力表逐条核验记录）

## 4. P1 · 双域验证与判官校准

- [ ] 4.1 判官结构性误读修复（对照 `docs/evaluation-system.md` 自认缺陷清单）（verify: 修后判官在既有 gold 上校准，结构性误读用例清零，all_pass 回到合理区间）
- [ ] 4.2 judge 校准运行机器：按置信分档的准确率矩阵 + 单调性，随模型+提示词版本留痕（verify: 对现行判官产出校准报告落库可查）
- [ ] 4.3 gold 信号源声明闸：未通过校准的 judge 不得被域包声明为 gold 信号源（verify: 声明被拒路径测试，拒绝信息指明「judge 未通过校准」）
- [ ] 4.4 政务域包：gov 语料适配器 + zhengxin 接入 + KG 车道验收判据迁入 + rubric 包（verify: gov 知识单元 入库→评测→复核 全链真跑记录）
- [ ] 4.5 金融数据域包：fd-sentiment gold-v9 尺子迁入 + fd-data-quality baselines 接入 + 首批数据 QA 金集（从 dashboards 对账/finalize 判据改写）（verify: 数据通道真跑——对账判据与 QA 金集评测出分且落库）
- [ ] 4.6 双域等价复核：迁入的尺子与原仓对同输入双跑零漂移（verify: 双跑对比记录零差异）

## 5. P2 · 柏讯贯通

- [ ] 5.1 wire 实体/关系单向拉取同步：wire 主键源、知验台零身份存储（verify: 同步后身份键与 wire 全等；重复同步幂等无新增行）
- [ ] 5.2 升格流水线（bronze 机器预标注 → silver → gold 人工核验）接入复核工作流（verify: 真实 wire 实体抽样走完全流程，审核人留痕可查）
- [ ] 5.3 gold 回写带档（sensitivity/tier），幂等键 = wire 实体键（verify: 回写成功路径 + 注入失败路径（网络断），知验台侧状态如实不误标「已回写」）
- [ ] 5.4 图谱展示接线：工厂内视图在 bench 工作台，客户面归 wire 控制台（verify: 两端同源抽样对账口径一致）

## 6. P3 · 全生态秤与飞轮

- [ ] 6.1 fd-text-core 检索评测迁入为 eval-suite（verify: 双指纹趋势在新址产出，与旧址最后基线一致）
- [ ] 6.2 KG 车道验收判据与市场发布门迁入（verify: 迁移后发布门读数与迁移前一致）
- [ ] 6.3 meta-eval 常态化：季度漂移检测入调度（verify: 漂移检测作业真跑一次并落库）
- [ ] 6.4 微调飞轮按域包导出 Judge/Drafter 数据集（verify: 导出物四层 tier 抽检合规；守卫拒绝用例仍被拒）

## 7. 收口

- [ ] 7.1 三域冒烟：法律 + 政务 + 金融各跑一轮 评测→复核→（法律）组装 全链（verify: 三域冒烟记录留档）
- [ ] 7.2 specs 对账：逐 Requirement 核对其 Scenario 有对应已完成任务且验证证据在案（verify: 对账记录，防「实现了却没勾」档案教训）
