# Design — audit-knowledge-units-clause-corpus

## Context

条款语料现状（2026-11-26 实测）：`knowledge_units` 表 `kind='clause'` 5386 条 raw + 1 条 silver（cheap 共享 postgres `postgres.postgres.svc:5432/law_bench`，public schema）。upsert 身份 `(kind, namespace, external_key)`；seed-clause 的 `external_key` = `source_path/section/body_hash` 三元串——**body_hash 内嵌于键中，等价去重的键天然存在**，无需加列。血统字段 `provenance`/`derived_from` 不可破坏。

消费面（初查，Phase 0 需落证）：`search_clauses` → `src/search/library_index.py` → Qdrant collection（经 `libraries`/`library_sources`/`corpus_chunks`）；`src/contracts|clauses|generator` 初查不直接读 knowledge_units。**前任 change 的教训是本设计的硬约束**：其三大前提全部失效后整条 change 作废，所以本 change 的范围必须由 Phase 0 实测产出，而不是预先写死。

可复用资产：`src/clauses/audit.py` 的三段 prompt（classify/rewrite/verify）与 `region_lint` 正则（da61ebf 已修「委」缩写，16 回归用例绿）——prompt 与语种域知识与存储无关，直接复用；存储访问层全新（旧 `src/clauses/store.py` 绑定 clauses 表形状）。

## Goals / Non-Goals

**Goals**
- Phase 0 测量脚本零 LLM、幂等、产出可提交的报告文件
- 审计管线只触达 Phase 0 命中集 + 消费方测绘确认活着的 unit
- 写入可按 unit 回滚；重嵌入闭环闭合

**Non-Goals**
- 不做全量 5386 条 LLM 审计（前任 3378 全量模式不复制——先证会触发）
- 不改 knowledge_units DDL / 不加列（body_hash 在 external_key 里够用）
- 不动 Qdrant 基础设施本身（只复用现有重嵌入口径/入口）
- 不重建 39/43 复评基线（那套 self-iterate 管线属于旧 clauses 形状；新库的质量门是 lint + verify + 重嵌入闭环，跨库复评若 Phase 0 证明需要则另立 change）

## Decisions

### D1 — 适配器放 `src/bench/audit.py`，prompt 复用不做继承式重构
新模块直接 import `src.clauses.audit` 的 prompt 常量与 `region_lint`（它们只吃 body 字符串）。不复用 `audit_one_clause`（其签名携带旧 store 形状）。避免为复用而改旧模块接口——旧模块服务于退役管线，保持原样。

### D2 — Phase 0 报告是 change 的 scope 锁
`scripts/measure_knowledge_corpus.py` 产出 `openspec/changes/audit-knowledge-units-clause-corpus/notes/phase0-measurement.json` + 人读摘要。后续任务的开关由报告字段驱动（region_content_leaks>0 才开 LLM 阶段等）。报告进 commit——这是 criterion-must-fire-on-real-data 的留痕形态。

### D3 — 消费方测绘落 Phase 0 报告，不靠记忆
grep 证据（哪些模块 import bench.store / library_index 读 kind='clause'、corpus_chunks 的 namespace 分布）写入报告 `consumers` 字段。rewrite 只允许打在 consumers 非空的 unit 上。

### D4 — 去重 = demote，不删行
按 `external_key` 的 body_hash 分组（同 namespace），canonical = 最低 unit id；非 canonical 的处置机制由消费方测绘决定（初判：从 library_sources/published corpus 排除——因为 DDL 无 status 列，"rejected" 概念在形状里不存在）。绝不 DELETE 行、绝不改 external_key（会破 upsert 身份、再造重复）。

### D5 — 重嵌入对接 = 现有 corpus 发布链，不发明新通道
corpus_chunks/Qdrant 的刷新沿用 11-11 建的 library_index/发布链。审计 driver 只负责：(a) 改写后标记受影响 chunk 集；(b) 调既有重嵌入口径或输出 pending-reembed 清单。若调研发现"改写后重嵌"缺口（很可能——审计管线是新写入者），把缺口修复作为独立任务，不塞进 audit.py。

### D6 — 并发与限流沿用前任实测参数
relay 12 并发上限（4 外层 × 3 内层）不变；LLM 阶段默认只跑命中集（预计 ≪5386），时长以命中数计。

## Risks / Trade-offs

- **Phase 0 实测可能全零** → 概率低但存在；届时 change 以「测量完成、无需治理、管线留存」收尾，不硬造工作量。
- **消费方测绘发现知识单元尚无活消费者** → rewrite 全部 defer，change 收敛为测量 + 去重 + 管线留存；避免给没人读的语料花 LLM 钱。
- **重嵌入链若不支持按 unit 粒度** → 按库粒度重嵌（小库成本可接受），报告里记粒度选择。
- **Qdrant 里的旧向量在重嵌前继续被搜到** → 可接受（旧文本=content-remediation 后状态，非缺陷重灾区）；pending-reembed 报告保证闭环可追踪。

## Migration Plan

1. Phase 0 测量 + 消费方测绘（零风险，只读）→ 报告入 change notes
2. 按报告开 LLM 审计阶段（命中集）→ 审计文件先行，DB 写入在后
3. 去重 demote（如实测有重复）
4. 重嵌入闭环验证（挑 1 条改写 unit 端到端：改写 → 重嵌 → search_clauses 返回新文本）
5. 完成：报告 + lint 终值 + pending-reembed=0

## Open Questions

- knowledge_units 的 namespace 取值分布（Phase 0 顺带测）——决定去重分组与审计批的粒度
- corpus_chunks→Qdrant 的重嵌入口径是按 unit 还是按 library（Phase 0 查 publish 链代码后定）
