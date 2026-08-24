# 微调数据准备子系统（finetune-data-flywheel）

为**判官（Judge C）+ 起草（Drafter A）双飞轮微调**产出可溯源、分层、许可证合规的训练数据。本文件是数据准备子系统的顶层说明；需求见 `openspec/changes/add-finetune-data-flywheel/specs/finetune-data-flywheel/spec.md`，设计见同目录 `design.md`。仓内抽取从 6 张扩到 11 张表（expand-finetune-data-sources），新增 `type_validations`/`law_info`/`contract_artifacts`/`core_clauses`/`industry_standard_references`，并支持银牌配对去重与 Judge-C 脚手架候选构建。

## 一句话定位

law-bench 已有一条「LLM 自产自评」链路（`generate → fill → evaluate → check → improve → store`），产物落在 `pipeline_runs`（548）/`eval_runs`/`eval_criteria_results`（870）/`clauses`（6686）。这些产物是飞轮自身的输出，**不是监督信号**——判官 `all_pass` 仅 31% 且 `docs/evaluation-system.md` 自认结构性误读，起草 `filled_text` 是 LLM 草稿。本子系统读这些产物做**物料**，但把机器自评硬约束为**永不作 ground truth**，人工产出真正的判官四元组与起草配对。

## 目录结构

```
data/finetune/
├── warehouse/        # 仓内只读抽取物料（每表一个 JSONL，每条带 provenance/source/tier）
├── opensource/       # 经许可证闸门接入的开源语料
├── judge-c/          # Judge-C 四元组数据集 + quadruple.schema.json
├── drafter-a/        # Drafter-A 配对数据集 + pair.schema.json
└── manifests/
    ├── manifest.schema.json     # 溯源清单记录 schema
    ├── warehouse_manifest.jsonl # 仓内物料溯源索引（瘦记录）
    ├── rejected_sources.jsonl   # 被许可证闸门拒绝的语料
    └── coverage_gaps.jsonl      # 覆盖缺口清单（零-pipeline 类型 / custom 偏薄）
```

每条物料（无论仓内/开源/人工）的溯源记录字段：`dataset`、`source`、`license`、`tier`、`provenance`（`<table>:<id>` 或 `<repo>:<ref>`）、`row_ref`（指向数据文件位置）。

## 数据分层（金/银/铜/原料）

四层**互斥**，每条物料恰好属一层，由 `tier` 字段标记：

| 层 | 来源 | 用途 | 守卫 |
|---|---|---|---|
| **gold** | 人工 rubric+criteria；人工核验合规正文 | 直接作 ground truth / reward | — |
| **silver** | `pipeline_runs.filled_text`（LLM 草稿） | **仅 SFT 暖启** | 不得作 reward 正样本 |
| **bronze** | `eval_criteria_results.verdict`（机器自评） | **仅供失败分析** | **永不作 ground truth**（见下） |
| **raw** | `clauses` 条款正文 + `eval_runs` 运行信封 | 结构骨干 + 判官输入池 | 无标签语义 |

> ⚠️ **BRONZE 永不作 ground truth。** `eval_criteria_results.verdict` 是当前判官（kimi-k3）的机器自评，仓内 `all_pass` 仅 31%、`docs/evaluation-system.md` 自认判官存在结构性误读（混淆合同正文与评分项、在合同里索要 PASS/FAIL 标记）。把 bronze 当 pass/fail 标签蒸馏 = 把这些系统性误判固化进新判官。**守卫在导出器单点实现**（`scripts/finetune/common.py::assert_not_ground_truth`）：任何下游按 ground-truth/reward 用途取 bronze 物料即报错拒绝。直接读 `eval_criteria_results` 原表绕过守卫是已知风险——不要这么做；根因治理（修判官）在后续变更。
>
> silver 同理：`filled_text` 是 kimi-k3 草稿，只作 SFT 暖启，**不作 reward 正样本**（守卫同一单点）。

按层过滤语义（加载器单点 `filter_by_tier`）：

- 「gold 及以上」→ 只返 gold（ground-truth 集合）。
- 「silver 及以上」→ 返 gold + silver（暖启池），**永不返 bronze / raw**。

## 飞轮顺序约束（判官先于起草）

判官是起草 reward modeling 的信号源。**Drafter-A 的 reward/DPO 脚本在启动时检查 Judge-C gold 四元组数据集文件存在且非空，否则报错「Judge-C 数据集未就绪」并拒绝运行**（代码闸门，非文档约定）。闸门只要求「存在且非空」，不要求规模达标——pilot 50 条即可放行 Drafter 暖启。

```
        仓内（只读 SELECT）              开源（许可证闸门）
        clauses ───── raw ─┐            DISC-Law-SFT(Apache) ─ silver ─┐
        pipeline_runs ─ silver          CAIL2018(MIT) ─ gold ───────────┤
        eval_criteria ─ bronze          SAMR 模板 ─ raw ────────────────┤
        rubrics/criteria ─ gold         ChatLaw(AGPL) ✗ LaWGPT(GPL) ✗   │
                                       ▼                                ▼
                            data/finetune/{warehouse,opensource}/  (tier-tagged)
                                       │
                  ┌────────────────────┴────────────────────┐
                  ▼                                          ▼
          Judge-C 四元组                            Drafter-A 配对
          (legal_base,clause,verdict,reasoning)     (task_desc/slots, body)
          machine pass→fail                         silver 暖启（去重+校验后 131）
          human pass 须引≥1法条→gold                 gold=人工核验正文
                  │
                  ▼  D4 闸门：Judge-C gold 非空 ──▶ 放行 Drafter reward
```

## 覆盖缺口（已知，不在本变更补）

抽取脚本末尾刷新 `data/finetune/manifests/coverage_gaps.jsonl`，记录两类缺口供后续 curation：

- `zero_pipeline_runs`：有 base 条款但 `pipeline_runs` 零行的合同类型（约 22 个，如 nda/divorce/mortgage/will）。
- `custom_thin`：`clauses.tags.source = custom` 的立场条款行数 < 500（当前 267）。

缺口清单**不阻塞** Judge-C / Drafter-A 数据集构建；刷新幂等、不产生重复条目。

## 脚本

| 脚本 | 作用 | 运行处 |
|---|---|---|
| `scripts/finetune/common.py` | 共享：分层/守卫/许可证/JSONL | 本地 + pod |
| `scripts/finetune/extract_warehouse.py` | 仓内只读抽取（纯 SELECT + 落盘） | law-bench pod（kubectl-exec） |
| `scripts/finetune/ingest_opensource.py` | 开源语料接入 + 许可证闸门 | 本地（离线） |
| `scripts/finetune/export_dataset.py` | bronze 守卫 + 分层加载 + 四元组/配对 schema 校验 + 飞轮闸门 | 本地 |
| `scripts/finetune/prepare_review_batches.py` | scaffold 按类型切人工核验批（prepare）+ 批准信封晋金（promote，拒绝 law_info 引用） | 本地 + pod |

仓内抽取复用已验证的 kubectl-exec + `psycopg.connect(os.environ['database_url'])` 模式：在 pod 内运行，复用 pod 环境里已有的 `database_url`，凭证不外泄、不在脚本里硬编码，零写入既有表。扩展后从 6 张扩到 11 张（clauses/pipeline_runs/eval_runs/eval_criteria_results/rubrics/criteria/type_validations/law_info/contract_artifacts/core_clauses/industry_standard_references）。

## 运行方式

```bash
# 1) 仓内抽取（在 pod 内，只读 SELECT + 落盘；幂等可重跑）
kubectl -n law-bench exec deployment/law-bench -- \
    python scripts/finetune/extract_warehouse.py
#   → data/finetune/warehouse/<table>.jsonl × 11（含 type_validations/law_info/contract_artifacts/core_clauses/industry_standard_references）
#   → data/finetune/manifests/warehouse_manifest.jsonl（溯源索引，expand-finetune-data-sources）
#   → data/finetune/manifests/coverage_gaps.jsonl（覆盖缺口）

# 2) Judge-C scaffold 构建（本地/pod 均可）
python scripts/finetune/export_dataset.py judge-c-scaffold
#   → data/finetune/judge-c/judge_c_scaffold.jsonl（silver 脚手架候选，待人工核验→晋金）

# 2b) 人工核验批处理：把 608 条 scaffold 按合同类型切成可审信封
python scripts/finetune/prepare_review_batches.py prepare
#   → data/finetune/review/inbox/p{1,2}_<type>.jsonl（39 类，按候选量排序）
#   人工：把待审文件移入 review/done/，逐条改 review.status=approved/rejected，
#         修正 verdict/legal_base/reasoning（权威法条来源，不得保留 law_info:*/[retrieval hint]）
python scripts/finetune/prepare_review_batches.py promote
#   → data/finetune/judge-c/judge_c_gold.review.jsonl（approved 信封强制 tier=gold/reviewer=human；
#     仍引用 law_info 的候选被拒绝）；inbox/ 可由 prepare 重生成，done/ 是人工产出，纳入版本管理

# 3) 开源语料接入（本地，逐语料包跑许可证闸门）
python scripts/finetune/ingest_opensource.py <corpus_dir> --tier silver
#   → data/finetune/opensource/<corpus>_index.json（接受）
#   → data/finetune/manifests/rejected_sources.jsonl（拒绝，幂等不重复）

# 4) 数据集导出 + schema 校验（本地/pod 均可）
python scripts/finetune/export_dataset.py judge-c   [--gold <human_gold.jsonl>]
python scripts/finetune/export_dataset.py drafter-a [--gold <human_gold.jsonl>]
python scripts/finetune/export_dataset.py validate judge-c   --file data/finetune/judge-c/judge_c_bronze.jsonl
python scripts/finetune/export_dataset.py validate drafter-a --file data/finetune/drafter-a/drafter_a_silver.jsonl

# 5) 飞轮顺序闸门（Drafter reward/DPO 启动前必跑）
python scripts/finetune/export_dataset.py gate
#   Judge-C gold 空 → rc=1「未就绪」阻断；就绪 → rc=0 放行
```

## 开源语料许可证清单（已核实）

| 语料 | 许可证 | 闸门 | 用途 |
|---|---|---|---|
| DISC-Law-SFT (FudanDISC) | Apache-2.0 | ✅ 入池 | 法律推理 SFT 暖启（tier=silver） |
| CAIL2018 (china-ai-law-challenge) | MIT | ✅ 入池 | 裁判推理（tier=silver） |
| SAMR 模板 | — | ✅ 入池 | 起草结构骨架（tier=raw） |
| ChatLaw (PKU-YuanGroup) | AGPL-3.0 | ❌ 拒绝 | 传染性 copyleft，不入商业微调池 |
| LaWGPT (pengxiao-song) | GPL-3.0 | ❌ 拒绝 | 严禁商业，不入池 |

白名单只放宽不改收紧（design D6）；缺 `LICENSE` 的包按「缺少许可证声明」拒绝。

## 实仓校验产物规模（2026-08-24 活库）

| 物料 | 表行数 | 校验后入池 |
|---|---|---|
| clauses (raw) | 6686 | 6686 |
| pipeline_runs (silver) | 548 | 非空 filled_text 356 |
| Drafter-A silver 配对 | — | **131**（356 非空 → 先挡下 `{{slot}}` 未替换/空 `task_desc` 残稿 → 正文 sha256 去重，131 distinct 且 131/131 通过校验） |
| eval_criteria_results (bronze) | 9134 | 9134（全部降级 fail，机器 pass→fail） |
| Judge-C bronze 四元组 | — | **9134/9134 校验通过** |
| type_validations (gold scaffold) | 275（258 含 law_ref） | 脚手架规则源 |
| law_info (bronze) | 86 | 检索提示（doubao/deepseek LLM 生成，非权威） |
| contract_artifacts (raw) | 401 | 含 `{{slot}}` 起草骨架 |
| core_clauses / industry_standard_references (gold) | 22 / 22 | 强制条款清单 / 成文法指针 |
| Judge-C scaffold 四元组 | — | **608**（208 规则命中 × top-3 相关条款，50 规则零重叠跳过；silver，待人工核验→晋金） |
| rubrics/criteria (gold) | 131 / 1275 | — |
| Judge-C gold 四元组 | — | 0（待人工标注，飞轮闸门当前关闭）。`prepare_review_batches.py` 已把 608 条 scaffold 切成 39 类核验批（`review/inbox/`），phase-1 按实际候选量取前 5 类：employment(36)/lease(24)/will(19)/bailment(18)/brokerage(18)，共 115 条；人工批准后 `promote` 落 gold |
| 覆盖缺口 | 24 | 23 `zero_pipeline_runs` + 1 `custom_thin`(267<500) |

> 银牌暖启池实际规模 = **131**（残稿过滤 + 去重 + 槽位校验后）。设计文档里的「548」是 `pipeline_runs` 表行数；356 条有非空 `filled_text`，构建器先剔除正文含残留 `{{slot}}` 或 `task_desc` 为空的残稿（在去重之前，避免某正文的首条残稿阻塞其后的合法副本），再按正文 sha256 去重，得到 131 条 distinct 且全部 131/131 通过 `validate_pair`。Judge-C 脚手架 608 条来自 `type_validations`（258 条含 `law_ref`）与同类型 `clauses` 的 char-bigram 相关性 top-3 配对（精确 `field==section` 优先），全部 `tier:silver`/`verdict:fail`，`law_info` 仅作 300 字检索提示，仅供人工核验晋金——构建器不写 gold 文件。
