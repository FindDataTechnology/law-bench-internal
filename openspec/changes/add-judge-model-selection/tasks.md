# 任务：add-judge-model-selection

## 1. 分层校准门（calibration 内核）

- [ ] 1.1 `src/bench/calibration.py` 新增纯函数：confusion_matrix(records) → TP/FP/FN/TN + sensitivity/specificity/balanced_accuracy/kappa（空集/单类 gold 的边界显式处理，不抛不静默）
- [ ] 1.2 校准门改判：balanced_accuracy ≥ CALIBRATION_MIN_AGREE(0.70) 且通道置信分桶单调；旧 agree_rate/自报分桶降为诊断字段；报告串含新门片段（可被 `is_calibrated` 兼容解析或同步迁移并留兼容测试）
- [ ] 1.3 单测：退化解（全 fail 判官，specificity=1.0/balanced≈0.5）必须 fail；过门样例 pass；no-confidence 桶不得充当通过证据

## 2. 采样一致率通道（driver）

- [ ] 2.1 `scripts/calibrate_judge_live.py` 增 `--samples k`（缺省 5，k=1 显式标记无通道）与 `--candidate <label>`：同一对独立 k 次判分（temperature>0），confidence=多数票占比，记录 `confidence_source="vote_share"` + k 次原始判定
- [ ] 2.2 通道降级纪律：call_error/通道不可产出的记录显式 `confidence_source="none"`，不落伪装置信；run 落库带 candidate 标识、k、调用数、分层矩阵、无效率
- [ ] 2.3 单测/干跑：mock judge 下 k 次票聚合、无效率统计、落库字段形状（沿既有 meta 通道，零 schema 变更）

## 3. bake-off 实跑与选型留痕

- [ ] 3.1 候选①：现行 judge（deepseek-v4.1-flash relay）+ 采样通道 k=5，同一 gold 集（/tmp/gold_validity_pilot.json，108 对不改）完整一轮，run 落库
- [ ] 3.2 候选②：11-03 四模型基线最优者 + 采样通道（凭据可用为前提；不可用则如实记录跑不动的候选，不造数据）
- [ ] 3.3 对照判读：两候选 balanced_accuracy/kappa/无效率/成本并排；结论（含不过门的差距）写回 design.md 附录，引用 run id；生产 EVAL_MODEL 不动（切换另案运维动作）
- [ ] 3.4 `add-judge-misread-remediation` 4.1 注记联动：按 bake-off 结果回填（过门→勾选并注明通道与 run id；不过门→差距与候选信号如实挂账）

## 4. 回归与收口

- [ ] 4.1 全量回归绿（calibration 既有测试 + 新增；`is_calibrated` 消费方零回归）+ strict 绿
- [ ] 4.2 评分主链隔离核查：`src/eval/scoring.py` 求零 diff（或仅注释/导入不动行为），评分载荷形状不变
