# 法规目录副本与引法审计 Runbook

`link-law-catalog-audit` 的操作手册：目录副本的刷新、名称解析的重跑、引法审计的产出，以及 web 复核队列的使用。设计与规格见 `openspec/changes/link-law-catalog-audit/`。

## 架构速览

```
法规库 PG (law_db.laws, 权威目录)  ──导出──▶ RustFS  ──下载──▶ law-bench PG
   id 即 Qdrant payload.law_id                              law_catalog.laws（只读副本）
                                                                    ▲
条款库 clauses.law_refs (《...》派生列, 只读) ──解析阶梯──▶ law_catalog.clause_law_refs
                                                            │
                                            审计报告 docs/law_citation_audit_report.md
                                            + web 复核队列 /law-catalog/review
```

- 解析结果存 `law_catalog.clause_law_refs`，**绝不写回 `clauses.law_refs`**（该列由条款体派生，编辑即重算）。
- 判定只用 `status` 列：`已废止`/`失效` → 引用已废法律；`已修改` → 单列；NULL/脏值 → 兜底。
- **`expiry` 列的实义是施行日期**（实测合同法 publish 1999-03-15 / expiry 1999-10-01），任何判定禁止使用。
- `law_id` 在 JSONL/Qdrant 里是字符串；本副本用 PG 原生 BIGINT，未来接 law-api 时在消费边界统一按字符串比较。

## 一次性准备

pg_trgm 扩展（trigram 解析档与相似度索引需要；缺失时解析降级——全部未命中进复核队列，其余功能不受影响）：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- 若 DATABASE_URL 用户无权限，由管理员执行一次
```

## 目录刷新（法规库侧有增量后）

1. **法规库侧导出**（在法规库 PG 上）：

   ```sql
   \copy (SELECT id,title,category,publish,expiry,status,src_db,content_status FROM laws ORDER BY id)
         TO '/tmp/laws_export.jsonl' WITH (FORMAT csv) CSV HEADER;
   ```

   （或任意能产出 JSON/JSONL 的方式；导入脚本两者都认。）

2. **上传 RustFS**：放 `laws-export` 桶，如 `catalog/laws_export-YYYYMMDD.jsonl`，经 `https://file.finddatatech.cloud` 可取。

3. **law-bench 侧导入**：

   ```bash
   python scripts/import_law_catalog.py --file /tmp/laws_export.jsonl --seed-aliases
   # imported 21746 laws (max_id=74584) ...
   ```

   全量替换语义：导入失败旧副本不动，成功则与导出完全一致。**基线对账**：首次导入应约 21,746 行 / max_id≈74,584（2026-09-24 快照，lawv2 13,930 / flk 3,239 / law 4,577）。
   不要从 `law_fixed.db`（SQLite 源）搬：行号 ≠ PG id，且缺 flk 增量。

## 解析与审计

```bash
# 全量解析（幂等，可随时重跑；不改条款任何字段）
python scripts/law_citation_audit.py --resolve-only

# 解析 + 报告（默认写 docs/law_citation_audit_report.md）
python scripts/law_citation_audit.py

# 只重渲染报告（不重跑解析）
python scripts/law_citation_audit.py --report-only
```

报告头带目录快照标识（行数/max_id/导入时间），可追溯；`resolved_via` 分 `exact/alias/trigram/unresolved`，模糊命中的可信度一眼可辨。连续两次运行、语料与目录未变时，结果与计数完全一致。

## 复核队列（web）

- `/law-catalog/audit`：审计总览 + 已废止/已修改明细（链接到条款）。
- `/law-catalog/review`：未解析名称 × 出现次数，附 trigm 候选；动作：
  - **确认映射**（候选按钮或手填 law_id）→ 写入别名表 `source='review'`，下次解析 `resolved_via=alias`；
  - **标记不匹配** → `source='non_match'`，移出复核队列，不伪造关联。
- 动作只写别名表，**不触碰条款正文与 `law_refs`**。写权限需 `content:write` scope。

## 已知边界

- 别名表冷启动：内置种子（`src/law_catalog/alias_seed.py`，九民纪要、各司法解释简称等）只兜常见写法；目录里不存在的目标标题会落到复核队列，不猜测。
- pg_trgm 缺失时 trigram 档降级为未解析（全部进复核队列），exact/alias 档不受影响。
- `law_catalog.laws` 是只读镜像，与法规库的同步是上面的人工刷新流程，不做自动同步。
