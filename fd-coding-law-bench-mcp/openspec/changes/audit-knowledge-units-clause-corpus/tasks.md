# Tasks — audit-knowledge-units-clause-corpus

> 范围纪律：Phase 0（任务 1-3）是范围锁——后续 LLM 任务的开关由其报告驱动；
> 实测为零的类别对应任务显式标「关闭（实测=0）」并留证据，不硬造工作量。
> constraint: criterion-must-fire-on-real-data。

## 1. Phase 0 — 真实数据测量（零 LLM）

- [ ] 1.1 建 `scripts/measure_knowledge_corpus.py`：对全部 `kind='clause'` unit 跑确定性扫描——region_lint（含 attribution 分类：法条尾部源头署名单列）、`{{slot}}` 占位计数、`external_key` body_hash 分组去重统计、namespace/tier 分布、body 空文本与异常长度清点
- [ ] 1.2 消费方测绘（grep 留证进报告 `consumers` 字段）：谁读 kind='clause'——search_clauses/library_index 链、corpus_chunks→Qdrant 发布链、contract 面是否间接消费；每条证据带 file:line
- [ ] 1.3 重嵌入口径调研：corpus_chunks→Qdrant 的刷新入口按 unit 还是按 library；改写后脏标记怎么落（确认现状是缺口还是有机制）
- [ ] 1.4 报告落 `notes/phase0-measurement.json` + 人读摘要，commit 进 change（scope 锁）；零命中类别在此刻显式关闭

## 2. 审计管线构建（复用 + 适配）

- [ ] 2.1 建 `src/bench/audit.py`：import 复用 `src.clauses.audit` 的 classify/rewrite/verify prompt 常量与 `region_lint`；新增 knowledge_units 适配（list/读 body/写 body 均走 upsert 身份，不碰 provenance/derived_from）
- [ ] 2.2 建 `scripts/audit_knowledge_units.py` driver：`--dry-run`（只出 verdict/rewrite 不落库）、`--type <namespace>`、审计结果文件先行（`output/audit-ku/<unit_ref>.json` 存原文+verdict+模型意见）、resume-safe（已存在结果文件的 unit 跳过）、relay 4×3=12 并发上限
- [ ] 2.3 去重任务（按 Phase 0 实测）：同 namespace 同 body_hash 分组，canonical=最低 id，非 canonical 按 D4 demote（机制依测绘结论），零 LLM；实测=0 则本任务标「关闭（实测=0）」
- [ ] 2.4 管线单测：适配器 CRUD 不碰血统字段（断言 provenance/derived_from/external_key 写前写后不变）、dry-run 零 DB 写、resume 语义、去重分组逻辑——全部跑 fakes，不打真 LLM/DB（constraint: 本机不跑全量，单文件跑）

## 3. 审计执行（按 Phase 0 命中集）

- [ ] 3.1 dry-run 命中集全量（先出 verdict 分布，人工过目 rewrite 样例 ≥10 条再放行 apply）
- [ ] 3.2 apply：verify 通过的改写落库；verify 失败保留原文并记 `output/audit-ku/`；逐条可回滚
- [ ] 3.3 改写集重嵌入闭环：按 1.3 调研结论标记/执行；端到端抽验 1 条——改写 → 重嵌 → `search_clauses` 返回新文本
- [ ] 3.4 批后 region_lint 终值报告：attribution 类与 content 类分列；content 类残留应降为 0（或留证说明为何保留）

## 4. 收尾

- [ ] 4.1 完成报告：Phase 0 终值 vs apply 后终值、改写数/拒绝数/uncertain 数、pending-reembed（须为 0 或带 owner 的显式挂账）、可回滚清单位置
- [ ] 4.2 fd-memory 落页：knowledge_units 语料审计结果 + 与前任 change 的对照结论
- [ ] 4.3 openspec validate 通过 → 归档本 change（sync specs）
