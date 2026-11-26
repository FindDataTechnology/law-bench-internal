# Phase 0 测量 — kind='clause' 语料

> 由 `scripts/measure_knowledge_corpus.py` 生成（零 LLM，只读）。scope 锁：下面非零缺陷类才进后续治理。

## 总量
- 行数 5387 / 在用 4986 / 软删 401
- namespace×tier：legal/raw=4985，legal/silver=1

## Scope 开关（实测命中数）
- region 内容级泄漏（真缺陷）：**0**
- region 归属引述（非缺陷，法条引用/发布机构）：6
- `{{slot}}` 占位正文数：**0**
- 等价重复冗余行：**0**
- 抽取伪影（PDF 换行断裂）正文数：**1210**
- 空正文：0 / 过短(<10)：6

## 消费方测绘（task 1.2）
- **search_clauses_tool**：fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/rag.py:127 → src.search.library_index.search (library_index.py:230 ranks corpus_chunks)
- **search_never_reads_ku**：src/search/ has 0 references to knowledge_units (grep -rn knowledge_units src/search → empty)
- **serving_backend**：src/bench/libraries.py:1 — law-library backend=qdrant collection=law_chunks_v2 (~364k external chunks) is what search_clauses serves
- **local_corpus_empty**：corpus_chunks table = 0 rows (live query); no local ingest feeds search from knowledge_units
- **only_direct_clause_reader**：src/bench/grounding.py:41 (kind='clause'); its entry ground_concepts (grounding.py:106) has NO caller in src/ or scripts/
- **kernel_not_a_reader**：src/bench/kernel_ports.py:700 clause_kinds=('clause',) → fd_ontology_kernel/kernel.py:207 _require_clause_parent (write-path invariant, not retrieval)
- **mcp_browse_surface**：tools/domain.py:188 domain_units — lists units with a 200-char preview (browse, not retrieval)
- **legacy_clauses_separate**：src/clauses/store.py / assemble.py:35 read the legacy `clauses` table (186 rows), NOT knowledge_units
- **adoption_direction**：scripts/adopt_code.py:64,72 COPY from law-library Qdrant → knowledge_units (corpus_catalog.py:676); the original stays in Qdrant and this is a downstream snapshot
- **reembed_path**：NONE backwards: knowledge_units is a DOWNSTREAM copy of the Qdrant law-library; there is no knowledge_units→corpus_chunks→Qdrant ingest. A knowledge_units body rewrite is NOT visible to search_clauses unless pushed back into the canonical Qdrant collection — the spec's rewrite→re-embed→search loop is architecturally unsatisfiable against this corpus.

## 结论（scope 判定）
- region_leak 审计：**关闭（实测内容级=0）** — 命中的全是法定跨域引述/发布机构。
- missing_slot 审计：**关闭（实测=0）** — 现库是法条正文，无合同占位符，前任 change 的 missing_slot 前提在此形状下不存在。
- duplicate 去重：**关闭（实测冗余=0）** — 无等价重复正文。
- extraction_artifact 正规化：**开启** — 1210 条正文含 PDF 换行断裂，可确定性修复（非 LLM）。
