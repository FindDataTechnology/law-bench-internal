# Tasks: 域优先 MCP

## 0. 前置取证

- [ ] 0.1 逐个核对 `src/bench/` 里域面要包的六个内核函数，确认它们**都是纯读**（`workspaces.*` / `store.*` / `proposals.list_*` / `next_actions.*` / `unit_checks.*` / `domain_rubrics.*`）。若发现隐式写（如 `touch_last_opened`），列出来并决定是否在工具层禁掉。
- [ ] 0.2 核对 `proposals` 的读函数是否都能按 `domain_key` 过滤，还是有几个需要先在调用层补 domain 参数。
- [ ] 0.3 确认 `copilot-runtime` 是 54 个工具的唯一消费者：在集群内查一遍还有没有别的 workload 连 `law-bench-mcp:30840`。
- [ ] 0.4 退役前确认 `contract-review-agent/` 工作区干净（无未提交改动），且 `attic/` 里无同名目录。

## 1. 域面：domain / units / rulers

- [ ] 1.1 `tools/domain.py`：`domain_list`（我在哪些域）、`domain_context`（本域现状：下一动作 + 机器核对摘要 + 计数）、`domain_assets`（按 kind 列归属资产）、`domain_proposals` / `domain_proposal_get`、`domain_publish`（版本历史 + 消费者）。
- [ ] 1.2 `tools/units.py`：`domain_units`（按 kind 列本域单位，含分页与 include_deleted）、`domain_unit_checks`（某单位的机器判定，逐条 checker 结果）。
- [ ] 1.3 `tools/rulers.py`：`ruler_list`（本域有效尺子，走 `domain_rubrics.effective_rubrics`）、`ruler_criteria`（一把尺子的判据列表）。
- [ ] 1.4 每个工具第一个参数是 `domain: str`，直接传内核的 `domain_key=`；**无默认值**。
- [ ] 1.5 `domain_context` 与页面同源：下一动作取 `next_actions.for_domain`、机器核对取 `unit_checks`，不重算。
- [ ] 1.6 单测：A 域身份查 B 域被拒（不是返回空列表）；返回的每个外部键都能在 A 域命名空间解析到；域面工具集里没有任何写库工具。

## 2. 法律工具降为 pack

- [ ] 2.1 17 个法律工具移入 `tools/legal_pack/` 子包，**函数体一行不改**，只改 `tags={"legal"}` 与注册名。
- [ ] 2.2 迁移前后的行为等价性判据：对同一组参数逐个比对返回结构（不是内容——内容会随库变）。
- [ ] 2.3 MCP 包的 README 与 `__init__.py` 的工具清单同步更新（现有文档写「54 个工具」，改后要重算）。

## 3. 资产面补域维度

- [ ] 3.1 `prompt_*` / `eval_*` / `compare_*` 增加可选 `domain` 参数：给出时经 `domain_assets` 归属表过滤，省略时行为不变。
- [ ] 3.2 如实记下缺口：`prompts` 无 `domain_id` 列，按域过滤只能走归属表；`eval_runs` 只能按 `rubric_domain_id` 反查。写进工具 docstring，不假装已解决。
- [ ] 3.3 单测：给 domain 时只返回该域归属的资产；不给时返回全部（向后兼容）。

## 4. 运行时与角色面同步

- [ ] 4.1 `copilot-runtime/server.mjs`：`READ_GROUPS` / `WRITE_TOOLS` / `LEAD_TOOLS` 按新组名（`domain` / `units` / `rulers` / `legal`）重写。
- [ ] 4.2 自检脚本加一条：旧组名（`contracts` / `law` / `clauses`）不再出现在白名单里——否则「改名了但白名单还是旧的」会静默放行一堆工具。
- [ ] 4.3 `MCP_TOOL_DENYLIST`（assistant 实例）里的四个删除工具名随改名同步。

## 5. 退役 contract-review-agent

- [ ] 5.1 `git mv contract-review-agent attic/contract-review-agent`；同批删 `Dockerfile.review-backend`。
- [ ] 5.2 MCP 的 `api/routes/agent_runs.py` 与其 `schemas.py` 段落：摘除，或在文件顶部写明「为已退役的 review-agent 保留，无消费者」——二选一在实现时定，但**不能留一个没人调又没人说明的端点**。
- [ ] 5.3 在本仓 `IDENTITY.md` 与 `admin-assistant-web` spec 里写明：`contract-review-agent` 不是平台的一部分。

## 6. 验收判据（必须在真数据上开火）

- [ ] 6.1 浮岛问「这个域有哪些单位」→ 返回的是 `knowledge_units` 的计数（5,833 量级），不是 `clauses` 的 186。
- [ ] 6.2 浮岛问「这个域该做什么」→ 与 `/d/{key}` 页面上的下一动作逐字一致。
- [ ] 6.3 以 A 域身份调用 `domain_units(domain="B")` → 拒绝，且拒绝原因可分辨（不是空列表）。
- [ ] 6.4 外部 agent 直连 `law-bench-mcp:30840` 调 `legal_pack_*` → 行为与改名前的 `contract_*` 一致。
- [ ] 6.5 `openspec validate domain-first-mcp --strict` 绿；`scripts/smoke_prod.sh` 绿。

## 7. 上产与回滚

- [ ] 7.1 先滚 `law-bench-mcp-assistant`（只有浮岛在用），验证 6.1–6.3 后滚 `law-bench-mcp`。
- [ ] 7.2 `copilot-runtime` 与 MCP 同批滚，否则工具名对不上会全空。
- [ ] 7.3 回滚演练：回退 MCP 镜像 tag → 确认旧工具名恢复可用。

## 8. 挂账（本 change 不做，仅登记）

- [ ] 8.1 `prompts` / `eval_runs` 补 `domain_id` 列——本 change 用间接方式凑合，真需求出现再立。
- [ ] 8.2 域面写工具（升格 / 确认提案 / 发布）——需先解决「机器身份没有会话身份」这个身份模型问题。
- [ ] 8.3 外部 agent 是否该拿到域面——本 change 先全开，发现越权再收。
- [ ] 8.4 合同线是否正式下线（数据归档 / 工具删除）——本 change 只降级不删除。

## Workflow follow-up

- 归档前跑 `openspec validate --strict`，并确认 §5 的退役已随本 change 落到主 specs。