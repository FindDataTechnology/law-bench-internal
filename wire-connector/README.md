# wire-connector（骨架，P0）

柏讯（fd-wire）↔ 知验台 的内部连接器。**只住内部仓**：涉及客户数据集绑定关系与内部语料，永不进公共仓。

规划面（change add-knowledge-bench-platform P2，任务 5.1–5.4）：

1. `fetch_entities` — 单向拉取 fd-wire entity-layer 实体/关系声明（wire 是身份主键源，本仓不存第二份身份）
2. `promote` — 升格流水线：bronze（机器预标注）→ silver（带标签）→ gold（人工核验，经 bench 复核工作流）
3. `write_back_gold` — gold 回写 wire，载荷带 sensitivity/tier，幂等键=wire 实体键，失败不误标「已回写」

契约真源：公共仓 `openspec/changes/add-knowledge-bench-platform/specs/bench-platform/spec.md` 的「柏讯实体升格契约」要求。实现落地前此骨架只作占位，不写任何半成品逻辑。
