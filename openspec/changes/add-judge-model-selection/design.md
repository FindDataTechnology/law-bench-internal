# 设计：判官置信通道选型与分层校准门

对应 `add-judge-misread-remediation` 4.1 的收口路径。前置事实全部来自 run 8（2026-11-06，108 对 live 校准，`/tmp/calib_full.json` 存档）与 11-03 校准存档。

## D1 数据事实（设计输入）

| 事实 | 数值 | 含义 |
|---|---|---|
| CONFIDENCE token 缺失 | 105/108（tail=3, mid=0, none=105） | 自报通道无信号可解析，宽容化被否决 |
| prompt 遵从率 | 3/108 ≈3%，两轮复现 | prompt 迭代路径证伪 |
| 混淆矩阵 | human=94 过/14 不过；judge=51 过/57 不过；TP=51 FN=42 TN=14 FP=0 | 判官系统性过严：specificity=1.0、sensitivity≈0.55 |
| 全局 agree | 65/108=0.602 | 主成分是 FN，不是置信缺失 |
| no-confidence 桶 | 106/108 | 旧分桶门整体失能、单调性空转 |

推论：换尺必须同时解决两件事——置信来源（通道）与门对类不平衡的免疫力（分层矩阵）。只换通道不换门，42 个 FN 仍把 agree 压在 0.6 以下且看不出偏置方向。

## D2 置信通道选型（三选一取舍）

| 通道 | 机制 | 取舍 |
|---|---|---|
| **采样一致率（选）** | 同一判分独立 k 次（temperature>0），confidence=多数票占比 | 不依赖模型自觉；任意 OpenAI 兼容端点可用；成本 k×n；已有多判官投票代码（`evaluate_with_multi_judge` 的 vote 语义）证明该信号形态在库内先例 |
| 原生 logprob/置信 | 端点返回 token 概率 | relay 链（token.finddatatech.cloud→deepseek）不保证透传 `logprobs`，GEval/deepeval 也不暴露——依赖两端都改，不可控 |
| 自报 token（弃） | prompt 尾标 | 两轮数据证伪；保留 `parse_confidence` 仅作 legacy 解析与 invalid 判定输入 |

降级纪律：通道声明了就必须产出或显式报无效；`confidence_source` 逐条留痕（`vote_share` / `none`），禁止未声明回落。

## D3 分层校准门（换尺不换阈值）

- 新增纯函数层（与既有 `bucket_accuracy`/`monotonicity` 同层）：`confusion_matrix(records)` → TP/FP/FN/TN + sensitivity/specificity/balanced_accuracy/kappa；门 = balanced_accuracy ≥ `CALIBRATION_MIN_AGREE`（0.70，用户既裁，语义从「全局 agree」迁为「类平衡 agree」）**且** 置信分桶单调（桶改用通道置信）。
- 旧字段 `agree_rate`、旧自报分桶保留为诊断输出，不参与门；`no-confidence` 桶不得充当通过证据。
- 单调容忍度沿既有 `MONOTONIC_TOLERANCE`。
- 门不通过时 run 记 fail，报告如实——沿「宁无效不假绿」纪律。

## D4 bake-off 协议与落库

- gold 集固定：`/tmp/gold_validity_pilot.json`（108 对，双标注 QC 过）不得改动，保证跨候选可比。
- 候选 = 通道 × 模型端点 组合；每候选一轮完整校准，落既有 eval_runs meta 通道，run 记录带 `candidate` 标识、k、调用数、分层矩阵、无效率、（可得时）成本。首轮至少：①现行 judge + 采样通道（k=5）；②11-03 四模型基线中表现最优者 + 采样通道（凭据可用性定，不可用则如实记录跑不动的候选）。
- 预算：540 调用/候选（108×5）；relay 实测 108 调用零错误，量级可承受；线程池并发沿 driver 既有实现。
- 选型结论以 run id 为证据写回本文件附录；生产 `EVAL_MODEL` 切换是显式运维动作，不在本 change 内执行。

## D5 风险

- **采样不稀释系统性偏置**：判官过严是判定口径问题，k 次重复只会稳定地错——分层矩阵独立暴露（sensitivity 低→门 fail），两把尺互补而非冗余。
- **k 偏大成本失控**：k 缺省 5、上限 9；k=1 等价于无置信（显式标记），不冒充通道。
- **并发/限速**：沿 driver 既有 ThreadPoolExecutor + 重试；relay 429 时退避重试，仍失败如实计入 call_error。
- **gold 泄漏风险**：gold 集不得因任何候选结果回改；发现标注错误另行走人工流程，不在校准轮内修。
- **兼容**：校准报告消费方（`is_calibrated` 解析、web 展示）读旧字段仍工作；新字段纯增量。
