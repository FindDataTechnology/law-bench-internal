# 完成报告 — audit-knowledge-units-clause-corpus

> 2026-11-26。本 change 由 Phase 0 实测**收窄**为「测量 + 确定性修复」，未建 LLM 审计管线。
> 理由与逐类关闭证据见下；实现细节见 `notes/phase0-measurement.json`。

## 一句话结论

现库 `kind='clause'`（4986 条在用，全是**法条正文** `<law>#第N条`，非合同模板）在真实数据上
只有**一类**缺陷触发——PDF 抽取换行断裂。另三类（region 内容泄漏 / missing_slot / 等价重复）
实测**全为 0**；且本表是 Qdrant `law-library` 的**下游快照**，`search_clauses` 读 Qdrant 原件、
无反向重嵌路径，所以 LLM 改写**既无命中对象也无下游可观测**。据此按 design 自述的收敛出口执行。

## Phase 0 终值 vs 修复后终值

| 缺陷类 | Phase 0（修复前） | 修复后终值 | 处置 |
|---|---|---|---|
| region 内容级泄漏 | **0** | 0 | 关闭（实测=0）。6 个正则命中全为合法：4× `台湾地区` 跨域引述 + 2× 来源页脚/发布机构 |
| missing_slot（`{{slot}}`） | **0** | 0 | 关闭（实测=0，法条正文无合同占位符） |
| 等价重复（在用） | **0** | 0 | 关闭（实测=0）。400 组「重复」全是 (1 在用 + 1 软删墓碑) 对 |
| PDF 换行伪影 | **1210 有行断特征 / 3462 有内部换行** | **0** | 确定性修复（见下） |
| 空正文 | 0 | 0 | — |
| 过短（<10 字） | 6（宪法修正案条文引用，"宪法第四条第一款"，合法） | 6 | 保留 |

## 做了什么

1. **`scripts/measure_knowledge_corpus.py`** — 零 LLM 确定性测量（只读）：region_lint（分 内容/legit_region/attribution）、slot 计数、规范化 hash 去重、namespace/tier 分布、长度普查、换行伪影计数、消费方测绘。产出 `notes/phase0-measurement.json` + `notes/phase0-summary.md`（scope 锁）。
2. **`normalize_pdf_linebreaks`**（`src/bench/corpus_catalog.py`）— 单段法条正文的换行归一：内部换行=PDF 折行→合并；条文号与正文间的全角空格行→单空格。**只动空白，不丢任何 CJK 字符**。已接入**摄入边界** `split_clauses`，未来 adopt 不再带断行（durable，不被 `ON CONFLICT DO UPDATE` 覆盖）。
3. **`scripts/repair_clause_linebreaks.py`** — 对既有行回填：原文先落 `output/audit-ku/<id>.json`（3462 份），仅 `UPDATE body, updated_at`；血统字段（provenance/derived_from/attrs/tags/tier/external_key）永不出现在 UPDATE 语句。`--dry-run` / `--revert` 齐备。
4. **单测** — `tests/test_corpus_catalog.py` 新增换行归一用例（断行合并、条文号不粘连、字符守恒）；`-k split` 7 passed。

## 逐类关闭证据（constraint: criterion-must-fire-on-real-data）

- **region 内容级=0**：6 命中逐条人读确认合法（`电信条例#58/64/79`、`企业所得税法实施条例#131` 的 `台湾地区` 是跨域条款主语；`飞行基本规则#124`、`税收征管法实施细则#113` 是来源页脚/施行署名）。留证在报告 `region_lint.rows`。
- **slot=0**：4986 条在用正文 `{{slot}}` 命中 0——现库是法条，不是合同模板，前任 change 的 missing_slot 前提在此形状下不存在。
- **重复=0（在用）**：规范化 hash 分组下，在用正文两两不同；400 组是 adopt_code `--clean-legacy-prefix` 留下的墓碑对。
- **LLM 段关闭**：design「Risks」明示「消费方测绘发现知识单元尚无活消费者 → rewrite 全部 defer」。实测坐实：`src/search/` 对 `knowledge_units` 0 引用；唯一直接读者 `grounding.py:41` 无调用方；`corpus_chunks`=0 行。

## 架构不可满足项（留证，非本 change 缺陷）

- **任务 3.3（改写→重嵌→search_clauses 返回新文本）不可满足**：`search_clauses` 经 `library_index.search` 读 Qdrant `law_chunks_v2`（外部 ~364k chunks），`knowledge_units` 是 `adopt_code.py` 从该库拷入的下游快照，**无 knowledge_units→Qdrant 反向路径**。即使改写本表正文也不影响检索。若要对用户实际检索的语料做质量治理，须另立 change 面向 Qdrant 原件（design 的 Non-Goal，本 change 不做）。

## 回滚

- 原文全文在 `output/audit-ku/<id>.json`（3462 份，gitignored）。
- `python scripts/repair_clause_linebreaks.py --revert` 逐条还原 body。
- 摄入侧改动（`split_clauses` 接线）随代码回退即复原。

## pending-reembed

- **N/A**：本 change 不做检索面重嵌（无反向路径，见上）。不遗留待重嵌项。

## 消费方测绘（file:line 摘要）

- `search_clauses` 工具 → `tools/rag.py:127` → `library_index.search`（读 `corpus_chunks`/Qdrant，`library_index.py:230`）
- `src/search/` 对 `knowledge_units` **0** 引用
- 服务后端 = `libraries.backend=qdrant`, `collection=law_chunks_v2`（`src/bench/libraries.py`）
- 唯一直接 `kind='clause'` 读者 = `grounding.py:41`，其入口 `ground_concepts`（`grounding.py:106`）**无调用方**
- 内核 `clause_kinds=('clause',)`（`kernel_ports.py:700`）= 写入期不变量（`kernel.py:207`），非检索消费者
- 旧 `clauses` 表（186 行）才是 `clause_list`/装配读的表——与 `knowledge_units` 分离
