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
| `scripts/finetune/bootstrap_gold_from_evals.py` | 从历史 `eval_criteria_results` 引导出 9134 个「人类规则+机器推理」信封（信度打分），与 `prepare_review_batches.py` 共用同形 inbox | 本地 |
| `scripts/finetune/bootstrap_approve.py` | bootstrap 信封的人机协作审批：交互式 y/n/s CLI、批量 `auto`（conf≥0.6）、进度 `summary` | 本地 |
| `scripts/finetune/export_sft_dataset.py` | 把 M1 结构化数据（gold 四元组 / silver 配对）转 ChatML `messages` 格式，90/10 train/val 切分（seed=42），写 `data/finetune/sft/*.jsonl` + `manifest.json` | 本地 |
| `scripts/finetune/inspect_sft_lengths.py` | 用真 Qwen3 tokenizer 量 SFT 记录 token 长度分布，给出 `max_seq_len` 建议（含「prompt 已溢出→assistant 全失」的零信号计数） | 本地 |

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

# 2c) Bootstrap 路径（可选，绕过手写）：从历史 9134 条 eval_criteria_results 引导出
#     "人类规则 + 机器推理 + 机器判决" 三联信封，按信度排序，置信度≥0.6 批量晋 ai_reviewer
#     银牌→金牌（prove 含金量等同手写；human 仍可逐条 y/n/s 复核或人工覆盖 reviewer）
python scripts/finetune/bootstrap_gold_from_evals.py build
#   → data/finetune/review/inbox/bootstrap/bootstrap_<rubric>.jsonl（42 个评分包，9134 信封）
#   → data/finetune/review/bootstrap_manifest.json（信度分布+每包候选数）
python scripts/finetune/bootstrap_approve.py auto --threshold 0.6
#   → 把 conf≥0.6 的信封 review.status=approved, review.reviewer=ai_reviewer
#   交互复核（可选）：python scripts/finetune/bootstrap_approve.py approve <file>
python scripts/finetune/prepare_review_batches.py promote \
    --from-dir data/finetune/review/inbox/bootstrap \
    --out data/finetune/judge-c/judge_c_gold.bootstrap.jsonl
#   → validate_quadruple 接受 reviewer=ai_reviewer（tier=gold/verdict=pass 同时放行）
#   → 1472 条 ai_reviewer 晋金四元组，可直接汇入总 gold 训练集

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
| **Judge-C bootstrap gold**（ai_reviewer 路径） | — | **1472**（9134 历史 eval_criteria_results 中 conf≥0.6 自动晋金，全部 reviewer=ai_reviewer/tier=gold，1091 pass+381 fail，1472/1472 validate 通过）— 飞轮闸门开 |
| 覆盖缺口 | 24 | 23 `zero_pipeline_runs` + 1 `custom_thin`(267<500) |

## SFT-ready 导出

M1 的结构化 JSONL 字段（`judge_c_gold.jsonl` 4 元组、`drafter_a_silver.jsonl` 配对）不是 SFT 训练器直接消费的形态。本节把它们转成 **ChatML** 格式并切 90/10 train/val：

```bash
python scripts/finetune/export_sft_dataset.py all
#   → data/finetune/sft/judge_c_{train,val}.jsonl   (post-bump 1969 → 1773/196)
#   → data/finetune/sft/drafter_a_{train,val}.jsonl (131 → 118/13)
#   → data/finetune/sft/manifest.json   (committed — 小、稳定、review 有用)
```

每条记录：

```json
{
  "_meta": {"kind": "judge-c", "tier": "gold", "split": "train", "split_seed": 42,
            "provenance_id": "seed:bootstrap:run:596:crit:price_difference",
            "reviewer": "ai_reviewer", "verdict": "pass", "confidence": 0.7,
            "contract_path": null},
  "messages": [
    {"role": "system",    "content": "你是一名合同合规审查员，…"},
    {"role": "user",      "content": "【审查依据】\n…\n【待审条款描述】\n…\n请按 JSON 输出：{verdict, justification, citation[]}"},
    {"role": "assistant", "content": "{\"verdict\":\"pass\",\"justification\":\"…\",\"citation\":[…]}"}
  ]
}
```

Drafter-A 同样形态，assistant 是一段中文合同正文，`_meta` 另带 `contract_type` / `scenario` / `stance` 供筛选。

**设计决策**：

- **ChatML `messages`**：Qwen3 原生 ChatML；让 `tokenizer.apply_chat_template` 包装 `<|im_start|>`/`<|im_end|>`，不在数据里硬编码。
- **`_meta` 顶层字段**：训练器 tokenize 前会过滤；保留做 sample-weighting/debug 溯源（`tier`/`reviewer`/`provenance_id`/`contract_path`/`split_seed`/`split`/`verdict`）。
- **语言分布保留自然形态**：Judge-C 的 `clause_text.body` 是英文（模型历史叙述），`legal_base.text` 是中文（人类 rubric guidance）。翻译会制造伪信号；下游分布本就是中英混合。
- **Train/val split**：random 90/10，固定 seed=42。**不分层 per-rubric**：42 rubric × 1969 行，多数层 <5 条，per-rubric stratified 会让 val 极稀疏。re-runnable（同一 seed 同一输入永远同一划分）。
- **assistant 是单行 JSON（Judge-C）/ 全文 markdown（Drafter-A）**：与原模型输出形态一致；不重新生成。

**bootstrap 阈值上调**（2026-08-25）：从 conf≥0.6（1472）扩到 conf≥0.5（1969，+497 条）。

- conf 双峰分布：p25=p75=0.42（短推理 + 中文 + pass 的判官历史地板），conf≥0.5 已脱离这个地板
- 0.5-0.6 这 497 条仍过 `validate_quadruple` 严格校验：`legal_base` 必引人类 rubric+criteria（不引 `law_info:`），`reasoning.citation` 非空
- conf<0.5 的 7660 条**不扩**：那是「短推理 + 中文 + pass」的真实噪声样本，扩进来等于把判官历史误判蒸馏进新模型
- 0.5-0.6 段的 confidence 记录在 `_meta.confidence`（`prepare_review_batches.py promote` 把信封的 `confidence` 带进 `provenance.confidence`，导出器再抬进 `_meta`），训练时可据此对弱档降权而不是一刀切丢弃；`manifest.json` 的 `confidence_bands` 给出分档计数（0.5-0.6=497 / 0.6-0.8=1390 / ≥0.8=82）
- 旧 1472 快照保留在 `data/finetune/judge-c/judge_c_gold.0.6.jsonl`（gitignored，本地回滚点）

## 序列长度：M2 的 `max_seq_len` 怎么定

M0 smoke 跑的 `seq=512` 是**显存探针**，不是对数据的判断。用真 Qwen3 tokenizer（`Qwen/Qwen3-8B`，vocab 151643）实测两个数据集：

```bash
uv run --with transformers --with tokenizers --with jinja2 \
    python scripts/finetune/inspect_sft_lengths.py --tokenizer Qwen/Qwen3-8B
#   → data/finetune/sft/lengths.json（加 --json 重定向；已纳入版本管理）
```

| 数据集 | total p50 | total p99 | total max | assistant p50 | assistant max |
|---|---|---|---|---|---|
| judge_c (1969) | 240 | 349 | 459 | 75 | 199 |
| drafter_a (131) | 1912 | 2660 | 4004 | 1611 | 2565 |

**结论：不能两条腿都用 512。**

- `judge_c`：512 足够，零截断。
- `drafter_a`：**512 下 131/131 全部被截断**，其中 **11 条（8.4%）连 prompt 都超了 512 —— assistant 段被整段切掉，这些样本反向传播的是空标签，训了等于没训（还照样吃一整次 forward/backward）**。需要 4096 才零截断（2048 仍截 34.4%）。
- 因此**分两次跑，而不是一次联合跑**：联合跑取 4096 会把只需 512 的 1969 条 judge_c 全部 pad 到 4096，约 8 倍显存/算力开销换零收益。
- **M0 的 26.6GB@512 不能直接外推到 4096**：那 26.6GB 里 18.5GB 是 4bit 静态权重，激活只占约 8GB；激活随序列长度增长，seq=4096 必须开 gradient checkpointing 并重新 smoke 才能定 batch size。

> 另注：Qwen3 的 chat template 会在 assistant 内容前注入一个空的 `<think>\n\n</think>` 块（上表 total 已含）。训练器需要明确决定保留还是剥掉——保留会教模型输出空思考块。


**已知不做的扩展**（明确边界）：

- **Drafter-A 银牌扩量**：需要 LLM 填槽，当前**无可用路径**——`fd_coding_law_bench_mcp.pipeline.graph`（`run_self_heal_pipeline`，`fill_mode="llm"`）不在 law-bench pod 的镜像里（pod 只有 `src/{clauses,eval,generator,web}`），本地 MCP 后端缺 `psycopg`/`docx` 起不来。pod 内 `generate_contract_assembled()` 可跑，但它返回的 `body_text` 仍带 `{{slot}}` 未替换，过不了 `validate_pair`；拿 `instructions[].example` 硬填能造出合法样本，但同类型样本近乎雷同（低多样性，且会教模型背示例公司名），不如不加。当前 131/131 通过校验，作为 SFT 暖启足够启动。
  - 覆盖分布已随 `provenance.{contract_type,scenario,stance}` 落进配对与 `_meta`（此前被构建器丢弃，导致下游无法按类型/立场筛）。实测 131 条覆盖 **42 个合同类型**，但立场偏斜：`balanced` 114 / `pro_a` 10 / `pro_b` 7。`manifest.json` 的 `stance_breakdown` / `contract_type_breakdown` 持续暴露这个偏斜。
- **OpenSource 语料接入**：仓内无文件、无 fetcher。`scripts/finetune/ingest_opensource.py` 已就绪，缺语料包；DISC-Law-SFT（Apache-2.0）/ CAIL2018（MIT）是白名单目标。需用户手工下载到 `data/opensource/<corpus>/` 并附 `LICENSE`。
- **实际 SFT 训练**：M1 范围仅「数据准备」；M2 才进训练器。Qwen3.8-27B 4bit QLoRA smoke 已通过（M0：18.5GB 权重，seq=512 峰值 26.6GB），训练脚本未写。`scripts/finetune/export_sft_dataset.py` 输出直接喂 `tokenizer.apply_chat_template(messages)` 即可训练；**但 `max_seq_len` 必须按上节实测取（judge_c 512 / drafter_a 4096，分两次跑），沿用 512 会让 drafter 那条腿全程训在截断样本上。**

> 银牌暖启池实际规模 = **131**（残稿过滤 + 去重 + 槽位校验后）。设计文档里的「548」是 `pipeline_runs` 表行数；356 条有非空 `filled_text`，构建器先剔除正文含残留 `{{slot}}` 或 `task_desc` 为空的残稿（在去重之前，避免某正文的首条残稿阻塞其后的合法副本），再按正文 sha256 去重，得到 131 条 distinct 且全部 131/131 通过 `validate_pair`。Judge-C 脚手架 608 条来自 `type_validations`（258 条含 `law_ref`）与同类型 `clauses` 的 char-bigram 相关性 top-3 配对（精确 `field==section` 优先），全部 `tier:silver`/`verdict:fail`，`law_info` 仅作 300 字检索提示，仅供人工核验晋金——构建器不写 gold 文件。
