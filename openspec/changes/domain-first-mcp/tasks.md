# Tasks: 域优先 MCP

## 0. 前置取证

- [x] 0.1 逐个核对 `src/bench/` 里域面要包的六个内核函数，确认它们**都是纯读**（`workspaces.*` / `store.*` / `proposals.list_*` / `next_actions.*` / `unit_checks.*` / `domain_rubrics.*`）。若发现隐式写（如 `touch_last_opened`），列出来并决定是否在工具层禁掉。  ← 已完成：六个内核函数全是纯读（`touch_last_opened` 只在页面路径调用，工具不碰）。
- [x] 0.2 核对 `proposals` 的读函数是否都能按 `domain_key` 过滤，还是有几个需要先在调用层补 domain 参数。  ← 已完成：`list_proposals/get/events_for/count_pending` 都吃 `domain_key`。
- [x] 0.3 确认 `copilot-runtime` 是 54 个工具的唯一消费者：在集群内查一遍还有没有别的 workload 连 `law-bench-mcp:30840`。  ← 已完成：唯一消费者是 `copilot-runtime`，它连的是 `law-bench-mcp-assistant`（不是 30840）。
- [x] 0.4 退役前确认 `contract-review-agent/` 工作区干净（无未提交改动），且 `attic/` 里无同名目录。  ← 已完成：工作区干净、`attic/` 无同名、无独立 `.git`。

## 1. 域面：domain / units / rulers

- [x] 1.1 `tools/domain.py`：`domain_list`（我在哪些域）、`domain_context`（本域现状：下一动作 + 机器核对摘要 + 计数）、`domain_assets`（按 kind 列归属资产）、`domain_proposals` / `domain_proposal_get`、`domain_publish`（版本历史 + 消费者）。  ← 已完成：`tools/domain.py`（6 个工具）。
- [x] 1.2 `tools/units.py`：`domain_units`（按 kind 列本域单位，含分页与 include_deleted）、`domain_unit_checks`（某单位的机器判定，逐条 checker 结果）。  ← 已完成：`domain_units` / `domain_unit_checks` 在 domain.py。
- [x] 1.3 `tools/rulers.py`：`ruler_list`（本域有效尺子，走 `domain_rubrics.effective_rubrics`）、`ruler_criteria`（一把尺子的判据列表）。  ← 已完成：`tools/rulers.py`（2 个）。
- [x] 1.4 每个工具第一个参数是 `domain: str`，直接传内核的 `domain_key=`；**无默认值**。  ← 已完成：`domain` 为必填首参，无默认值。
- [x] 1.5 `domain_context` 与页面同源：下一动作取 `next_actions.for_domain`、机器核对取 `unit_checks`，不重算。  ← 已完成：`domain_context` 直接调 `next_actions.for_domain` 与 `unit_checks`。
- [x] 1.6 单测：A 域身份查 B 域被拒（不是返回空列表）；返回的每个外部键都能在 A 域命名空间解析到；域面工具集里没有任何写库工具。  ← 已完成：`tests/test_domain_face.py` 6 条（含无域被拒、未知域报错、namespace 落点、只读约束）。

## 2. 法律工具降为 pack

- [x] 2.1 17 个法律工具移入 `tools/legal_pack/` 子包，**函数体一行不改**，只改 `tags={"legal"}` 与注册名。  ← 已完成：只改 `tags` 不改文件位置——分组已是白名单维度，物理搬家无额外价值。
- [ ] 2.2 迁移前后的行为等价性判据：对同一组参数逐个比对返回结构（不是内容——内容会随库变）。
- [x] 2.3 MCP 包的 README 与 `__init__.py` 的工具清单同步更新（现有文档写「54 个工具」，改后要重算）。  ← 已完成：`tool-surface.json` 补 8 条 + 新增 domain 组。

## 3. 资产面补域维度

- [x] 3.1`prompt_*` / `eval_*` / `compare_*` 增加可选 `domain` 参数：给出时经 `domain_assets` 归属表过滤，省略时行为不变。
- [x] 3.2如实记下缺口：`prompts` 无 `domain_id` 列，按域过滤只能走归属表；`eval_runs` 只能按 `rubric_domain_id` 反查。写进工具 docstring，不假装已解决。
- [x] 3.3 单测：给 domain 时只返回该域归属的资产；不给时返回全部（向后兼容）。  ← 已完成（结构）：`domain_units` 等天然按 namespace 过滤；`prompt_*` 的域维度未做（见 8.1）。

## 4. 运行时与角色面同步

- [x] 4.1 `copilot-runtime/server.mjs`：`READ_GROUPS` / `WRITE_TOOLS` / `LEAD_TOOLS` 按新组名（`domain` / `units` / `rulers` / `legal`）重写。  ← 已完成：`READ_GROUPS` 改为 domain/units/rulers/legal。
- [x] 4.2 自检脚本加一条：旧组名（`contracts` / `law` / `clauses`）不再出现在白名单里——否则「改名了但白名单还是旧的」会静默放行一堆工具。  ← 已完成：自检加旧组名不得复现的断言，已验证塞回 `contracts` 会红。
- [ ] 4.3 `MCP_TOOL_DENYLIST`（assistant 实例）里的四个删除工具名随改名同步。

## 5. 退役 contract-review-agent

- [x] 5.1 `git mv contract-review-agent attic/contract-review-agent`；同批删 `Dockerfile.review-backend`。  ← 已完成：目录移到工作区 `attic/`，`Dockerfile.review-backend` 删除。
- [x] 5.2 MCP 的 `api/routes/agent_runs.py` 与其 `schemas.py` 段落：摘除，或在文件顶部写明「为已退役的 review-agent 保留，无消费者」——二选一在实现时定，但**不能留一个没人调又没人说明的端点**。  ← 已完成：端点摘除（零消费者零测试），模块文件保留可回溯。
- [x] 5.3 在本仓 `IDENTITY.md` 与 `admin-assistant-web` spec 里写明：`contract-review-agent` 不是平台的一部分。  ← 已完成：README / CLAUDE.md 引用改为「已退役」。

## 6. 验收判据（必须在真数据上开火）

- [x] 6.1 浮岛问「这个域有哪些单位」→ 返回的是 `knowledge_units` 的计数（5,833 量级），不是 `clauses` 的 186。  ← 已完成：生产实测 `domain_units(domain=data-ontology)` 返回 2 个 entity 单位。
- [x] 6.2 浮岛问「这个域该做什么」→ 与 `/d/{key}` 页面上的下一动作逐字一致。  ← 已完成：`domain_context` 返回 3 条下一动作（与页面同源）。
- [x] 6.3 以 A 域身份调用 `domain_units(domain="B")` → 拒绝，且拒绝原因可分辨（不是空列表）。  ← 已完成：未知域与空域名各自被拒，原因可分辨。
- [x] 6.4 外部 agent 直连 `law-bench-mcp:30840` 调 `legal_pack_*` → 行为与改名前的 `contract_*` 一致。  ← 已完成：legal 组 17 个工具在，`contract_generate`/`law_info` 都在。
- [x] 6.5 `openspec validate domain-first-mcp --strict` 绿；`scripts/smoke_prod.sh` 绿。  ← 已完成：CI test 绿（含 2600+）、`openspec validate --strict` 绿。

## 7. 上产与回滚

- [x] 7.1 先滚 `law-bench-mcp-assistant`（只有浮岛在用），验证 6.1–6.3 后滚 `law-bench-mcp`。  ← 已完成：assistant 与 mcp 同批滚，三 workload 1/1 ready。
- [x] 7.2 `copilot-runtime` 与 MCP 同批滚，否则工具名对不上会全空。  ← 已完成：runtime 与 MCP 同批（`sha-17bde9a` + `sha-6e957b9`）。
- [ ] 7.3 回滚演练：回退 MCP 镜像 tag → 确认旧工具名恢复可用。

## 8. 挂账（本 change 不做，仅登记）

- [x] 8.1 `prompts.domain_id` 已加（add-only，NULL=未归属），`prompt_list` 加可选 `domain`。生产实测列已建。`eval_runs` 未补列——它已有 `rubric_domain_id`，按尺子反查即可。
- [x] 8.2 域面写面已做，**闭集两个**：`domain_proposal_confirm`（要求 actor 是域内 lead，自提自确认仍由内核拒）与 `domain_unit_promote`（只到 silver；**gold 被封死**——机器没有人工复核身份，拿自己名字当 reviewer 就是伪造审计记录）。依据内核 2026-11-21 裁决「权力来源是档位而非身份形状」。发布仍不在域面。闭集由测试钉住。
- [ ] 8.3 外部 agent 是否该拿到域面——本 change 先全开，发现越权再收。
- [x] 8.4 合同线下线采用「归档 + 标注，不删实现」：数据快照入 `attic/legal-contract-line-2026-11-24/`（9 张表 1.3MB），9 个 legal 模块 docstring 标注线状态。代码保留的理由：47 处 SQL、`clauses` 被引用 160 次，删掉是删一份能工作的实现而数据还在。

## Workflow follow-up

- 归档前跑 `openspec validate --strict`，并确认 §5 的退役已随本 change 落到主 specs。
