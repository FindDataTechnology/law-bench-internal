# 域优先 MCP（Domain-First MCP）

## Why

`fd-coding-law-bench-mcp` 是为**识律合同评测**做的，不是为**知验台**做的。这个错位现在有了可量的代价：

**一、MCP 面向的表和平台面向的表是两批。**

```
老法线表（MCP 全在这边）          新平台线表（域控制台全在这边）
clauses            186            knowledge_units      5,833
rubrics             92            domains                  6
criteria           871            authoring_events     9,130
eval_runs           22            domain_proposals       100
prompts              0            ontology_publications    5
compare_runs         0            domain_assets          105
```

54 个工具里**零个** import 过 `knowledge_units` / `domains` / `proposals` / `next_actions` / `unit_checks`。唯一带 `domain` 参数的是 `search_clauses`——它查的是 RAG 语料，不是本体。

**二、合同线已经停了，却仍是 MCP 的主干。**

| 证据（生产实测 2026-11-24） | 值 |
|---|---|
| `generation_jobs` | **0**（从未跑过） |
| `compare_runs` | **0** |
| `prompts` | **0** |
| `contract_artifacts` | 7（全部 2026-11-11 一天） |
| `eval_runs` | 22（其中 16 条在 11-10/11，6 条是回归闸自动跑的） |

而新平台线每天都在动。MCP 的组织维度（`contract_type`）在平台里**不是组织单位**——平台的组织单位是 `domain`，`contract_type` 连 `knowledge_units.kind` 的一种取值都算不上。

**三、这个错位让副驾驶不可用。**

`scope-assistant-to-domain` 里有三项做不到，根因都是这一条：跨域隔离加不出来（工具不认域）、注入的下一动作与页面无法一致（MCP 没有 `next_actions` 工具）、助手能调的只有 186 条老合同条款而不是域里的 5,833 条。

## What Changes

**BREAKING（机器面契约）**：MCP 的工具面按域模型重写。域是第一维度，法律降为一个 pack。

- **域面成为主干**：新增 `domain_*` / `unit_*`  / `ruler_*` 三组工具，直接读写 `knowledge_units` / `domains` / `domain_proposals` / `authoring_*`。这组工具**天然带域参数**，跨域隔离是结构性的，不靠提示词。
- **资产面去 `contract_type` 化**：`prompt_*` / `eval_*` / `compare_*` 增加 `domain` 维度。`rubrics` 表已有 `domain_id`，其余补齐访问方式（**不改表结构**）。
- **法律专属工具降为 pack 面**：现有 17 个法律/合同工具（`contract_*` / `law_*` / `clause_*` / `search_clauses`）保留行为，改名进 `legal_pack_*` 分组，声明它们是「legal pack 装的工具」，不是 MCP 的普遍能力。
- **两类 clause 不合并**：法条（5,386，在 `knowledge_units`，kind=clause）与合同条款（186，在 `clauses`，含 `{{slot}}` 装配素材）是两类资产，各有各的工具前缀与归属。合并会同时毁掉本体与装配线。
- **`contract-review-agent` 退役**：未部署、前端已弃 CopilotKit、无独立 git/CI/spec；它与 C7 智能体团队的 `domain_agent_runs` 是同一概念的两次发明。移入 `attic/`，本仓 spec 写明它不是平台的一部分。

## Capabilities

### New Capabilities

- `domain-mcp-face`: 知验台 MCP 的域面契约——域/单位/尺子三类只读工具、角色收敛的边界、跨域隔离的结构性保证，以及「两套数据模型各自归属」的划分规则。

### Modified Capabilities

- `law-bench-mcp`: 工具面的组织维度由 `contract_type` 改为 `domain`；法律专属工具降为 `legal_pack_*` 分组；新增「MCP 服务的是知验台而不是某条业务线」这一表述性需求。

## Impact

**代码（law-bench-internal）**

- `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/`：新增 `domain.py` / `units.py` / `rulers.py`；现有 17 个法律工具迁入 `legal_pack/` 子包并改名。
- `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/api/`：`agent_runs` 端点随 review-agent 退役一并摘除或标注保留原因。
- `copilot-runtime/server.mjs`：工具面白名单按新分组更新（`READ_GROUPS` 等）。
- `packs/legal/`：声明它装的是 `legal_pack_*` 这组工具（pack 与 MCP 工具面的对应关系第一次显式化）。

**数据**：**零 schema 变更**。不改表、不迁数据；改的是访问方式与工具命名。

**部署**：`law-bench-mcp` 与 `law-bench-mcp-assistant` 两个 workload 的镜像重出。`copilot-runtime` 的 `MCP_TOOL_DENYLIST` 与角色白名单需同步新工具名。

**不做什么**

- 不合并 `clauses` 与 `knowledge_units`。
- 不给域面加写工具（`domain_promote` 等仍走页面；写面要单独立 change，理由见 `scope-assistant-to-domain` §8.2）。
- 不重构 `src/clauses/` 与 `src/contracts/`（85 个文件引用 `clauses`，但那是 pack 内部实现，不是 MCP 契约的一部分）。

**风险**

- **BREAKING**：改名后旧工具名失效。生产唯一调用方是 `copilot-runtime`（54 个工具没有第二个消费者），它与本 change 同批更新；但没有版本化兼容层——外部若有人直接连 MCP，会立刻失败。这是有意的：一个「叫拉」的兼容层会让两代工具面长期并存，正是本次要消灭的东西。
- **合同线虽停但未删**：7 条 artifact 与 22 条 eval_run 是历史证据，保留。任何人要复活合同装配，`legal_pack_*` 那组工具仍在。
