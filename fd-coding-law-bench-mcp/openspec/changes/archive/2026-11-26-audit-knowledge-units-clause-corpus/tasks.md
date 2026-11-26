# Tasks — audit-knowledge-units-clause-corpus

> 范围纪律：Phase 0（任务 1-3）是范围锁——后续 LLM 任务的开关由其报告驱动；
> 实测为零的类别对应任务显式标「关闭（实测=0）」并留证据，不硬造工作量。
> constraint: criterion-must-fire-on-real-data。

> **Phase 0 结论（2026-11-26 实测，4986 条在用 `kind='clause'`）改写了本 change 的形态**：
> 现库是**法条正文**（`<law>#第N条`），不是合同模板。四类缺陷只有一类在真实数据上触发。
> 且消费方测绘证明 `knowledge_units` 是 Qdrant `law-library` 的**下游快照**——没有
> `knowledge_units → Qdrant` 的反向重嵌路径，`search_clauses` 读的是 Qdrant 原件，不是本表。
> 因此 LLM classify→rewrite→verify 段（原 2.1/2.2/3.1/3.2/3.3）**无成本动因**（三类命中=0）
> 且**无可观测下游**（无消费方、无重嵌路径），按 design 自述的收敛出口
> （「测量完成、无需治理、管线留存」）关闭；唯一触发的抽取伪影类改由**确定性**修复。

## 1. Phase 0 — 真实数据测量（零 LLM）

- [x] 1.1 建 `scripts/measure_knowledge_corpus.py`：对全部 `kind='clause'` unit 跑确定性扫描——region_lint（含 attribution/legit_region 分类：SAR 跨域引述与来源页脚单列）、`{{slot}}` 占位计数、body 规范化后 hash 分组去重统计、namespace/tier 分布、body 空文本与异常长度清点、PDF 换行伪影计数
- [x] 1.2 消费方测绘（grep 留证进 `notes/phase0-measurement.json` `consumers` 字段）：谁读 kind='clause'——search_clauses/library_index 链、corpus_chunks→Qdrant 发布链、contract 面是否间接消费；每条证据带 file:line
- [x] 1.3 重嵌入口径调研：结论=**无反向重嵌路径**（knowledge_units 是 Qdrant 下游副本；本地 corpus_chunks=0 行；改写不会回流 Qdrant）。详见报告 `consumers.reembed_path`
- [x] 1.4 报告落 `notes/phase0-measurement.json` + `notes/phase0-summary.md`（scope 锁）；零命中类别在此刻显式关闭。实测：region 内容级泄漏=0 / slot=0 / 等价重复=0 / 抽取伪影=3462（确定性命中 body，其中 1210 有行断特征、全量 3462 有内部换行）

## 2. 治理（按 Phase 0 实测收窄为确定性修复）

- [x] 2.1 ~~建 `src/bench/audit.py` LLM 审计适配器~~ — **关闭（实测三类命中=0 + 无活消费方）**。理由见「Phase 0 结论」；design 收敛出口明示不复制前任 3378 全量 LLM 模式。
- [x] 2.2 ~~建 `scripts/audit_knowledge_units.py` LLM driver~~ — **关闭（同上）**
- [x] 2.3 去重任务：**关闭（实测在用冗余=0）**。注意 400 组「重复」全是 (1 在用 + 1 软删 legacy-prefix 墓碑) 对——不是在用重复；报告 `deleted_twin_groups` 单列留证。
- [x] 2.4 确定性修复落地：`normalize_pdf_linebreaks`（`src/bench/corpus_catalog.py`）在**摄入边界** `split_clauses` 接线（未来 adopt 不再带断行）+ 既有行回填 `scripts/repair_clause_linebreaks.py`（原文先落 `output/audit-ku/`，仅改 body/updated_at，血统字段不动，可 `--revert`）。

## 3. 验证（按 Phase 0 命中集）

- [x] 3.1 ~~dry-run 命中集全量 + 人工过目 LLM rewrite 样例~~ — **关闭（无 LLM 段）**；确定性修复的 before/after 抽样已在 driver `--dry-run` 输出。
- [x] 3.2 应用确定性修复：3462 条在用正文落库（`repair_clause_linebreaks.py`），原文逐条落 `output/audit-ku/<id>.json`，可逐条回滚。
- [x] 3.3 ~~改写集重嵌入闭环（改写→重嵌→search_clauses 返回新文本）~~ — **关闭（架构上不可满足：无 knowledge_units→Qdrant 反向路径；search 读 Qdrant 原件）**。留证见报告 `consumers.reembed_path`。
- [x] 3.4 批后终值报告：重跑 `measure_knowledge_corpus.py`；content 类残留=0，伪影类降为 0。

## 4. 收尾

- [x] 4.1 完成报告：Phase 0 终值 vs apply 后终值、确定性修复计数、逐类关闭证据、可回滚清单位置（`notes/completion-report.md`）
- [x] 4.2 fd-memory 落页：knowledge_units 语料审计结果 + 与前任 change 的对照结论
- [x] 4.3 openspec validate 通过 → 归档本 change（sync specs：delta spec 按实测收敛为测量+确定性修复能力）
