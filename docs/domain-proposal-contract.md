# 域提案箱提交契约（`POST /api/d/{domain_key}/proposals`）

> 面向本平台自己的自动化（本体舰队的提案岗）与域内专家。C5（`add-domain-first-workbench`）
> 的提交面；P2 起取代「把本体草案塞进下游动作审批队列」的老路。
> 判据不是「代码里删了旧调用」，而是一轮真跑后**两侧计数对照**（见文末）。

## 一句话

一条草案 = 一个**可核对的属性主张**。它进的是这个域的提案箱，等域负责人确认；
确认后经内核唯一写入路径落进 `knowledge_units`。起草者不是确认者。

## 请求

```
POST /api/d/{domain_key}/proposals
Content-Type: application/json
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `source` | 是 | 提交方的稳定身份，跨轮不变。舰队岗位用 `fleet:<fleet_id>/<post_id>`；域内专家可用自己的用户名。**它和 `external_key` 一起构成幂等身份** |
| `kind` | 是 | 必须在**该域锚定的模板版本词表**内（实体类或关系类）。出表一律 400，不会「先收下再看看」 |
| `external_key` | 是 | 实体的业务键。关系类按 `{from_key}->{kind}:{to_key}` 约定；URL 里要百分号编码 |
| `body` | 是 | 条目正文（给人和检索看的自然语言） |
| `evidence` | 是 | **确认时的唯一判断材料**。非空字符串，或非空 JSON 对象/数组。`null`/空串/`{}`/`[]` 一律拒绝 |
| `impact` | 否 | 影响说明，给人读的补充 |
| `submitted_by` | 否 | 提交者署名；缺省取调用身份（`email` 或 `name` 或 `sub`）。**自提自确认禁令按它判** |

`evidence` 可以是任意形状（URL、摘录、结构化字段），本层不解释内容，只在两种场合用它：
给人看，以及算**规范化摘要**——`sha256(JSON, sort_keys=True, separators=(",",":"), ensure_ascii=False)`。
所以键顺序不影响判定，两个月后另一个进程算出来的「同一份依据」和今天一致。

**关系类提案的额外要求**：提案行没有独立的端点列，`from_key` / `to_key` 随 `evidence` 一起进来
（也接受 `from` / `to` 简写），确认时内核据此派生关系键。缺任一端点 → 400
`relationship 提案的 evidence 缺少非空的 from_key/to_key 端点`；`evidence` 不是对象 →
`relationship 提案的 evidence 必须是对象并携带 from_key/to_key`。实体类提案没有这条约束。

## 响应

```json
{"id": 42, "state": "pending", "external_key": "ai-corp", "evidence_digest": "9f2c…"}
```

- `200` —— 新建，或命中同键已存在的 pending 行（**幂等命中**：返回既有行，不新增、不报错）。
- `400` —— 语义拒绝，`detail` 是中文原话，直接可以进报告：
  - `提案必须携带依据` —— 缺 `evidence` 或给了空容器
  - `kind '<k>' 不在模板 v<n> 词表内：entity_types=[…], relationship_kinds=[…]` —— 出表 kind
  - `同键已驳回，需新证据` —— 该键被驳回过，且这次的 `evidence_digest` 与上次相同
- `403` —— `missing scope: content:write`（平台权限不足）或 `无该域权限`（不是本域 expert）。
- `401` —— 没有身份。
- `422` —— 请求体不是 JSON 对象。

## 谁能提交

两道闸按顺序执行：`require_scope("content:write")`（Logto 平台权限）→ `require_domain_role("expert")`
（本域成员，且角色 ≥ expert）。平台 `admin`/`*` 绕过域闸。

**给舰队接线时的硬要求**：提交凭据的身份必须在目标域里是 expert。`X-API-Key` 或 Bearer 都能用，
但它们只解决「平台权限」那一闸，域成员关系仍以 `domain_members` 为准 —— 换凭据不换成员关系。

## 幂等与重试纪律

- 幂等身份 = `(domain, source, external_key, state='pending')`，由部分唯一索引兜底。
  同一身份重复提交**只有一行**，后到的请求拿到同一行。
- 被驳回的行是**历史**，不是身份：同键可以重提，但**必须换依据**（digest 不同）。
  同依据重提是 400 —— 换不换证据是人的判断，不该由轮次机械地重试。
- 对端 401/403/5xx/超时：调用方记失败、草案留在本地产物里等下一轮，**不得**记成「已提交」。

## 确认与驳回（同域负责人）

- `POST /d/{domain_key}/inbox/{id}/confirm` —— lead 及以上。写入走 `authoring.upsert_knowledge_unit`，
  同时写 `domain_proposal_events`（pending→confirmed）。**重复确认幂等**。
- `POST /d/{domain_key}/inbox/{id}/reject` —— lead 及以上，理由必填（缺理由 400 `驳回必须写明理由`）；
  写事件（pending→rejected）。
- 自提自确认：`submitted_by == 当前操作身份` 时确认 403。平台 admin 例外，但事件 note 会明确写上
  `[admin-override] confirmed by admin over the submitter '<sub>'` —— 豁免留痕，不是静默放行。

## 两侧计数对照（切换判据）

舰队提案岗切到本提交面后，一轮真跑必须同时满足：

1. 知验台 `legal` 域提案箱新增 N 条 `pending`（或按幂等命中少于 N），且控制台 `/d/legal/inbox` 可见；
2. 下游动作审批队列的本体类提案**增量为 0**（与切换前基线比）。

历史行不迁移、不删除：已确认的历史提案是审计记录。

## 不做什么

- 不提供「按内容自动选域」：域 key 来自岗位配置（`BENCH_PROPOSAL_DOMAIN`），猜错域是最难发现的一类错误。
- 不做双写（既进本提案箱又进下游队列）：双写会让「谁的确认算数」永远悬着。
- 提案本身不执行任何动作，因此不携带动作类字段（`tool_risk`、账号/工作区目标等）。
