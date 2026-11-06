# 任务：add-judge-misread-remediation

> apply 期实查修订：prompt 修复主体已以 v2-structure 在产（11-03 引入），本任务清单收窄为域化补账+解析硬化+校准实跑。

## 1. prompt 域化补账

- [x] 1.1 `v2-structure` 规则文本迁入 generation_prompts 域（judge_scoring_v2-structure 版本行+provenance inherits 记录；insert-only seeder 不覆盖 operator 编辑）
- [x] 1.2 `build_judge_criteria` 改按域查询注入，域不可用回落模块常量（评审链永不断，字节等同）；EVAL_PROMPT_VERSION 语义保留（域版本标签）

## 2. 解析硬化（fail-loud 单点）

- [x] 2.1 `_classify_structural_soundness` 检测（marker_in_contract 高置信 zh/en 归因+否定守卫、CONFIDENCE 违约→contract_violation、success+空 reasoning）；invalid verdict + invalid_reason 留痕
- [x] 2.2 invalid 从分数分母剔除、n_invalid/invalid_rate 顶层新增、全 invalid 强制 all_pass=False（宁无效不假绿）；消费方核查 6 处（run/compare/store/review/export/self_iterate）无 crash，invalid 天然不进 gold 信号（_agrees 只认 pass/fail）

## 3. 校准闭环实跑

- [x] 3.1 gold pair 导出实查：/tmp/gold_validity_pilot.json 已在（11-03 v4-validity-pilot 导出件，108 对，human 94/14，QC 过）——零新导出
- [ ] 3.2 live calibration driver 复跑（v2-structure + fail-loud）报告落库含 invalid 率——**卡点：EVAL_MODEL/OPENAI_API_KEY/OPENAI_API_BASE 凭据缺失**（.env 不在仓，历史只有占位符；agent 不擅用无关 key 以保校准可比性）；凭据到位后：`uv run python scripts/calibrate_judge_live.py --gold /tmp/gold_validity_pilot.json`（108 调用估算 <200）
- [ ] 3.3 验收判据核对：误读用例清零 + all_pass 合理区间 + invalid 率阈值（不达标如实迭代，不造绿）——离线预检已抓实锤：历史 v2-structure 输出 105/108 缺 CONFIDENCE 尾标（49 个 PASS 为不可验证 pass=contract_violation），新屏会如实标 invalid

## 4. 回归与收口

- [x] 4.1 既有评测套件零回归（scores dict 增量兼容：n_invalid/invalid_rate 新键；compare 单稿格 cell 可能带 invalid 字符串如实记录）
- [x] 4.2 全量回归 1302 绿 + strict 绿（kernel domain-free + public hygiene 双闸 OK）
- [ ] 4.3 4.1 勾选（验收判据达成后）+ blueprint 台账更新
