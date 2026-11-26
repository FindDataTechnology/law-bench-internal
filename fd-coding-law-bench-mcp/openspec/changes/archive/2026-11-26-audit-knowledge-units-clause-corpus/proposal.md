# Proposal

## Why

条款语料已迁入 `knowledge_units`（law_bench 生产库，`kind='clause'` 5386 条 raw + 1 条 silver，cheap 共享 postgres），成为 `search_clauses` → library_index/Qdrant 的 RAG 语料源。前任 change `clause-library-audit-optimization` 于 2026-11-25 归档作废（b65280d）：其三大前提（6433 条 clauses 表、region/slot 缺陷分布、39/43 复评基线）全部失效，且归档头部明示「若将来要对 knowledge_units 做同类审计，应新立 change 并重做测量」。本 change 就是那个新 change：对现库**先重测、再治理**，把质量治理接到新存储形状上。

## What Changes

- **NEW Phase 0 真实数据测量（先于一切规则）**：对 5386 条 `kind='clause'` unit 跑确定性扫描（region_lint 正则、slot 占位计数、`external_key` 内 `body_hash` 去重、血统字段完整性），产出缺陷分布报告。**只有实测会触发的缺陷类才进入后续治理任务**；实测为 0 的类别显式关闭并留证（constraint: criterion-must-fire-on-real-data）。
- **NEW 消费方测绘**：实测定 Who 消费 kind='clause'（search_clauses/library_index/Qdrant 链已证实；contract 生成面初查不直接读，需在 Phase 0 落证）。审计深度与优先级按消费方爆炸半径定。
- **NEW 多模型审计管线（按 Phase 0 实测收窄）**：沿用 classify（kimi-k3/glm-5.2/deepseek-v3 三模型多数决）→ 单模型 rewrite → 异模型 verify 三段结构，存储层新写 knowledge_units 适配器（替换旧 clauses/tag_review 形状）。
- **NEW 语料重嵌入闸**：改写落库后，受影响的 corpus_chunks/Qdrant 索引必须重嵌入或标脏，否则 RAG 面继续吐旧文本——这是前任 change 不存在的新闭环要求（新消费形状）。
- **MODIFIED** src/bench/store.py 生态：新增审计写入通道（不改 `provenance`/`derived_from` 血缘字段，不改 `(kind, namespace, external_key)` upsert 身份）。

## Capabilities

### New Capabilities
- `knowledge-corpus-audit`: 对 knowledge_units 语料的测量→审计→改写→验证→重嵌入闭环能力，含确定性 lint 门（region_lint/等价去重）与可回滚写入纪律

### Modified Capabilities
<!-- 无：本 change 不修改既有主 spec 的行为 -->

## Impact

- **Code**: 新 `src/bench/audit.py`（classify/rewrite/verify prompt 复用 src/clauses/audit.py + knowledge_units 适配）、新 `scripts/audit_knowledge_units.py`（driver，镜像 scripts/audit_clauses.py 结构）、`src/search/library_index.py` 不改但需提供脏标记对接
- **Database**: `knowledge_units` 表 body/attrs 更新（预计少量行，以 Phase 0 实测为准）；NO schema change；`corpus_chunks` 重嵌入
- **APIs**: 无 MCP 工具变更
- **Dependencies**: 3 LLM judge endpoints（同 relay 12 并发上限）
- **Cost**: Phase 0 确定性扫描零 LLM 成本；LLM 阶段按实测命中数定价（前任 3378 条全量的教训——本 change 默认只审命中集）
- **Rollback**: 原文全文保留于 `output/audit-ku/<unit_id>.json`，可按 unit 粒度还原；写入前先落审计文件
