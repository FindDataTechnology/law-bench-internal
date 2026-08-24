## 1. 宽表只读抽取扩展

- [ ] 1.1 在 `scripts/finetune/common.py` 的 `TIER_BY_TABLE` 增 5 张附加表分层：`type_validations`→gold、`core_clauses`→gold、`industry_standard_references`→gold、`contract_artifacts`→raw、`law_info`→bronze
- [ ] 1.2 在 `scripts/finetune/extract_warehouse.py` 的 `TABLES` 增上述 5 张表，保持 `SELECT * FROM {table} ORDER BY id` 只读路径不变
- [ ] 1.3 在 pod 内重跑 `extract_warehouse.py`，产出 `data/finetune/warehouse/{type_validations,law_info,contract_artifacts,core_clauses,industry_standard_references}.jsonl`，全量行数对账：275/86/362/22/22
- [ ] 1.4 验证幂等：同库连跑两次，11 张表物料清单逐字节相同；SQL 全为 SELECT，既有表零写入

## 2. 新表分层路由与守卫

- [ ] 2.1 验证附加表物料各带 `provenance`/`source: warehouse`/`tier`，分层标签与 §1.1 一致
- [ ] 2.2 验证 `law_info`(bronze) 被既有 `filter_by_tier(floor='gold')` 排除在 ground-truth 集合外；`assert_not_ground_truth('bronze')` 对 law_info 物料触发拒绝
- [ ] 2.3 验证 `contract_artifacts`(raw) 不进入任何 gold/silver 输出集

## 3. 银牌配对去重

- [ ] 3.1 在 `scripts/finetune/export_dataset.py` 的 `_build_silver_pairs` 按正文 `filled_text` 逐字节去重，仅保留首条 distinct 配对
- [ ] 3.2 去重审计：返回并打印「去重前 N / 去重后 M distinct」，对账 363→151
- [ ] 3.3 验证被保留配对的 `tier:silver`/`source:warehouse`/`provenance` 字段未因去重丢失
- [ ] 3.4 验证去重后银牌池仍被 `load_drafter_reward_positive` 排除在 reward 正样本外（silver 不进 gold 集，守卫未放宽）

## 4. Judge-C 候选四元组脚手架构建器

- [ ] 4.1 在 `scripts/finetune/export_dataset.py` 增 `judge-c-scaffold` 子命令：按 `contract_type` 把 `type_validations`（含 `law_ref`/`message`）× `clauses` 正文 × `law_info` 法条摘要交叉配对，产出候选四元组
- [ ] 4.2 候选标 `tier:silver`、`provenance: scaffold:machine:<type_validations:id>`、`annotated_by: machine_self_eval`、`verdict` 默认 `fail`；`legal_base.source` 标 `law_info:<llm_source>`
- [ ] 4.3 候选过既有 `quadruple.schema.json` + `validate_quadruple` 校验；不过的候选丢弃并记入缺口
- [ ] 4.4 产出落 `data/finetune/judge-c/judge_c_scaffold.jsonl`（silver）；构建器不直接写 `judge_c_gold.jsonl`

## 5. 脚手架人工核验晋金路径

- [ ] 5.1 确认晋升路径：人工核验产出文件经导出器校验后落 `judge_c_gold.jsonl`，构建器自身不写 gold
- [ ] 5.2 验证 gold 四元组标 `tier:gold`/`annotated_by:human_annotated`/`reviewer:human`；`verdict=pass` 含 ≥1 `citation`；机器 pass 降级规则适用
- [ ] 5.3 验证 `flywheel_gate()` 检测到 `judge_c_gold.jsonl` 非空时放行 Drafter-A reward modeling（闸门可开）

## 6. law_info 机器生成降级约束

- [ ] 6.1 验证脚手架候选引用 `law_info` 文本时 `legal_base.source` 标 `law_info:<llm_source>`（deepseek/doubao），且候选 `tier` 仍为 silver
- [ ] 6.2 验证 law_info 物料不因被脚手架引用而晋升 gold；人工核验采纳 law_info 表述时须改标权威来源（如 `民法典§509`），不保留 `law_info:<llm_source>`

## 7. 文档与校验收尾

- [ ] 7.1 更新 `docs/finetune-data.md`：表/分层地图扩到 11 张、银牌真实数 151、`type_validations` 脚手架流程、law_info bronze 告示
- [ ] 7.2 `openspec validate --change expand-finetune-data-sources` 通过
- [ ] 7.3 全套脚本幂等重跑（抽取/去重/脚手架/校验），既有表与运行时零影响
