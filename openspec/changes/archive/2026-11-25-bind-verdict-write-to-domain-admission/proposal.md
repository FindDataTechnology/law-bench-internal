# Proposal

## Why

壹座已经在往知验台写判定，但**对端没有任何一条路由能把它落下来**。这条边断在知验台这一侧，且断法是静默的：

- 客户端 `lib/bench-ops-client.js` 拼好 `body.verdict`（全有或全无校验，注释写得很认真）并 `POST {domain}/runs`；
- `src/web/routes/distribution.py` 的 `record_run` 处理器里 `verdict` 出现 **0 次**；
- 同一文件 verdict 台账段的注释白纸黑字写着：**「no route here creates a verdict」**。

于是「一次回合干得好不好」在知验台没有落点：写面不存在，读面孤悬。而 `domain_agent_runs.verdict_run_ids` 与 `verdicts.baseline_run_id` 这条在进程内已经闭环的链，对外部进程完全不可达。

同时，「把不同 agents 或客户加入某个同类定义域」这件事今天有三道门（`domain_members` / `consumers.domains[]` / `agent:<role>@<domain>` 前缀），三套判据。判定写面一旦开放，必问「谁在这个域、凭什么用这把尺子」——三处判定会让新写门成为第四个分叉点。

## What Changes

- **verdict 写路由**：新增一条机器面写路由，让已登记的消费者（fleet）与域成员（人/agent）能把一条完整评测结论落到台账。**只追加，没有任何 UPDATE 路径。**
- **写入三道门**：`① 身份`（凭据派生的身份，不取自请求体自称）× `② 尺子可见性`（尺子必须在该被评域的有效标准里可见）× `③ 层级`（模板标准只读；域 fork 需本域 expert 及以上；机器身份上限 expert）。任一不过即拒，拒因可分辨。
- **判定记层级**：`eval_runs` 增 `ruling_domain_path` 与 `ruler_derived_from`，使「按平台模板判的」与「按本域自维护标准判的」在读数上可分且可回溯 fork 血统。
- **接纳抽象**：`admitPrincipal({domain, kind, ref, role})` / `listPrincipals(domain, role?)` 成为「把某主体加入某同类定义域」的唯一写入口与读面；`kind ∈ {user, agent, fleet}` 是数据而非代码分支，背后复用既有 `domain_members` 与 `consumers.domains[]`，**存量零迁移**。
- **模板数据与结论的资格门写成可判条件**：改模板标准、改域标准、写结论 三种动作各有明确主体集合；任何主体不得改已写结论（写面本身不存在 UPDATE）。
- **BREAKING（仅机器面契约）**：`POST {domain}/runs` 回执增加结论段；只带运行的回写形状不变。

## Capabilities

### New Capabilities

- `domain-admission`: 「把某主体加入某同类定义域」的抽象——主体种类闭集、三类成员的统一读面、准入的资格判据与留痕，以及「同类」由所锚定模板版本表达。

### Modified Capabilities

- `evaluation-rules`: 判定必须记明所依据标准的层级与 fork 血统；判定只追加，不可改写。
- `domain-workspace`: 成员的读面 SHALL 覆盖机器主体（`agent:` / `fleet:`），与人对齐同一个「谁在这个域里」的答案。
- `knowledge-distribution`: 消费者写面从「只管运行台账」扩展为「运行台账 + 评测结论」，且回执区分运行入账与结论入账。

## Impact

- **代码（law-bench）**：`src/web/routes/distribution.py`（新写路由，与既有 `record_run` 同族）、`src/bench/verdicts.py`（层级校验进闭集判定）、`src/eval/store.py`（`store_result` 增两列）、`src/bench/workspaces.py`（`admitPrincipal` / `listPrincipals`）、`src/bench/distribution.py`（消费者读面补 kind 维度）。
- **数据库（Postgres，全部 additive）**：`eval_runs.ruling_domain_path TEXT`、`eval_runs.ruler_derived_from BIGINT`；无回填、无迁移。
- **代码（paas）**：零改动；由 companion change `bind-fleet-turn-to-bench-verdict` 消费本面。
- **既有行为**：会话面（`POST /api/d/{domain}/proposals` 等人面）零变化；`domain_members` / `consumers` 存量行零迁移。
- **测试**：三道门逐条负向（不在域内的尺子 / 改模板 / 机器身份改结论 / 自报身份冒充）；只追加（无 UPDATE 路径的机制断言）；接纳抽象的 kind 闭集与既有两张表的一致性。

## 依赖

- paas 侧 `bind-fleet-turn-to-bench-verdict`（回合地址为主语、回执四态）；本面落地前它应以 `verdict_state=dropped` 如实记账。
