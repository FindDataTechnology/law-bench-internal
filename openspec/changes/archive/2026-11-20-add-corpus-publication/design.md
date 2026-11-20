## Context

见 `proposal.md` — Why。设计相关的现状（2026-11-20 生产实测）：

- `libraries` 已登记三个库；`law-library`（id 1）`backend='qdrant'`，
  `location = {"url_env": "QDRANT_URL", "collection": "law_chunks_v2"}`，
  七个 `payload-filter` 源（statutes / administrative / judicial / local / departmental /
  amendment / unclassified），`ingest_rule.document` 已声明
  `id=law_id`、`title=title`、`text=chunk_text`、`order=chunk_no`、`unit_kind=law`。
- Qdrant 实测：**365,938 点 / 32,251 部法规**，块均 402 字符，最大 3,995；
  全量正文约 **147 MB** canonical JSON。
- 平台进程限制：`law-bench` 容器 `memory: 512Mi` / `cpu: 500m`；`QDRANT_URL` 已在 pod 环境内。
- 既有只读访问路径：`src/search/library_index.py` 的 `_qdrant_post` / `_count_qdrant` /
  `source_counts`，以及 `src/bench/libraries.py` 的 `resolve_location`、`EXTERNAL_BACKENDS`。
- 既有规范序列化内核：`distribution.canonical_digest()` → `fd_ontology_kernel.manifest.digest_of`
  （键序归一、排除时间戳）。`add-typed-publications` 已确立「digest 只有一份实现」的纪律。
- `shared-corpus-library` 已规定库的身份（`library_key` 不可变）与订阅语义，
  本变更不修改它们。

## Goals / Non-Goals

**Goals**
- 一次发布的内存占用与库的**法规部数**相关，与全库正文体积无关（512 Mi 下可完成）。
- 独立核对：消费者能拿单部法规的正文与 digest 验证它属于某版本，无需下载整库。
- 切分器升级、向量重建不改变已发布版本的 digest。
- 复用既有 Qdrant 读取与既有 digest 内核，不新增第二份实现。

**Non-Goals**
- 不发布向量本身（向量是后端的实现细节；digest 只锚定身份与正文）。
- 不做增量回填或语料纠错（发布只描述现状）。
- 不改订阅语义、不改检索路径、不迁移语料到平台库内。

## Decisions

### D1 发布单位 = 库，版本序列在库上

新表 `corpus_publications` 以 `library_id` 为键，而非 `domain_id`。

**为什么不复用 `asset_publications`**：它的唯一约束是 `(domain_id, asset_kind, version)` 与
`(domain_id, asset_kind, digest)`，版本序列绑在域上。语料是共享物理层——同一份 `law-library`
被 legal 与 gov 订阅，若按域发布就会产生两条内容相同、编号各异的序列，消费者拿到的 digest
取决于「谁发布的」，而 digest 唯一用途是跨方核对。

**替代方案**：给 `asset_publications` 加可空 `library_id` 并放宽唯一约束 —— 否决。那会让一张表
承载两种身份语义，读侧每次都要先判「这行是域的还是库的」，正是 `add-typed-publications` D1
拒绝过的形状。

### D2 冻结粒度 = 文档（法规），身份取 `ingest_rule.document.id`

每部法规一个条目：`doc_key`（源内的文档身份，即 `law_id`）、`title`、`chunk_count`、
`doc_digest`。

**为什么不用块**：块的序号与边界由切分器决定。按块冻结意味着一次切分策略调整会改动
32k × N 条记录、作废全部历史 digest，而正文一个字都没变。以文档为单位则切分自由变化。

**为什么身份取 `law_id` 而非 Qdrant 点 id**：点 id 是摄取批次生成的整数（实测
`7340032`），重建集合就会变；`law_id` 是源数据自己的稳定标识，`ingest_rule` 已声明它就是
`document.id`。**前提**：同一 `law_id` 在一个源内唯一——由 `ingest_rule.document.id` 的语义保证，
实现期要在投影时做一次重复检测并报错而不是静默合并。

### D3 digest 两层：逐文档 → 清单

```
doc_digest(doc) = digest_of(canonical_entries_of_one_doc)       # 约 4.5 KB 输入
version_digest  = digest_of([{doc_key, doc_digest}, ...sorted by doc_key])
```

两层都调用既有 `digest_of`，没有任何新的序列化规则。

**为什么不是全量一次 sha256**：147 MB 的 `json.dumps` 在 512 Mi 的进程里是真实风险，且
`sort_keys=True` 的中间表示需要同时持有原对象与序列化结果。两层方案下，常驻内存只有
**一部法规**的正文加一份 32k 条 `(key, digest)` 清单（约 3 MB）。

**为什么清单 digest 不包含块数**：块数是切分器的产物，进 digest 就把切分器钉死进契约。
块数作为**清单字段返回**（便于消费者判断切分是否变了），但不参与任何一层 digest。

### D4 拉取面：清单分页 + 按文档取正文

```
GET /api/v1/distribution/libraries/{library_key}/{kind}?version=N&cursor=...&limit=...
GET /api/v1/distribution/libraries/{library_key}/{kind}/{doc_key}?version=N
```

清单项：`{doc_key, title, doc_digest, chunk_count}`；响应带 `next_cursor`（null 表示结束）。
正文端点返回 `{doc_key, title, doc_digest, chunks: [...]}`。

**为什么分两种端点**：单次返回全部正文≈147 MB，任何客户端都会超时/爆内存——那是把体积问题
从服务端挪到客户端，不是解决。

**为什么路径带 `libraries/` 段**：既有 `/api/v1/distribution/{domain_key}/{kind}` 的第二段已经是
域键；把库键塞进去会让「legal」既可能是域也可能是库，且与 `add-typed-publications` 的
`{kind}` 通配路由直接冲突（`libraries` 会被解析成域键）。显式前缀让两条路径空间不相交，
也一并避免遮蔽问题。

**分页用 cursor 而非 offset**：外部后端的点在发布投影时被一次性读出、按其 `doc_key` 排序后
再切页，offset 在同一版本内其实是稳定的；但 cursor（上一页最后一个 `doc_key`）不依赖总数，
后端数据在两次请求之间变化也不会错位。

### D5 投影读取：复用 `library_index` 的 Qdrant 访问，不新增客户端

投影按源遍历（七个 `payload-filter` 源各自带 `match` 规则），对每个源 scroll
`with_payload=[document.id, document.title, document.text, document.order]`、`with_vector=false`，
按 `doc_key` 分组、按 `order` 排序拼正文。

**必须带的护栏**（写进实现判据）：
- scroll 显式 `limit`（每页 2000）+ 总时长上限，超限即失败并报明，MUST NOT 静默截断
  （截断的 manifest 会让 digest 描述一份不存在的语料）。
- 逐文档流式处理：读完一部法规立即算 `doc_digest` 并丢弃正文，常驻只有一部法规。
- 无 `doc_key` 的点是数据损坏，报错而非跳过。

**替代方案**：用 Qdrant 的 `facet` 一次拿到全部 `law_id` —— 否决：facet 拿不到正文与顺序，
仍需逐文档回读；而全量 scroll 已经在既有 `source_counts` 里用过同一路径。

### D6 发布动作的授权

`POST /admin/libraries/{library_key}/publish`，`require_scope("admin")`。

**为什么不复用域 lead 门**：库不属于任何域（`shared-corpus-library` 明确库独立于域树存在），
把发布权绑到某个域的 lead 上等于让订阅者之一决定全库的版本。

**替代方案**：库级 owner 角色 —— 本轮不做（`libraries` 表没有 owner 列，加列是另一件事），
先由平台管理员发布。

## Risks / Trade-offs

- [32k 部法规的投影是一次长读] → 每页 2000 点、逐源处理、总时长上限；失败不落半版。
  预估 37 页 × 7 源的重叠需实测，实现期记录真实耗时。
- [清单端点被当成「全量下载」] → 分页 + 显式 `limit` 上限（如 1000）+ 响应里给出
  `total_docs`，让调用方知道还剩多少。
- [库重新摄取后 digest 变化] → 这正是发布的意义；消费者用 `?version=N` 钉住旧版，
  历史版本不可变。
- [`law_id` 在同一源内重复] → 投影期做重复检测并报错（D2）。
- [外部后端不可达时发布失败] → 报错而非发空版；已发布版本不受影响（不可变）。
- [在 512 Mi 的 pod 内做发布] → 两层 digest + 逐文档流式；若实测仍超内存，
  发布动作可迁到一次性 Job（设计已允许，不影响契约）。

## Migration Plan

1. 建两表 `corpus_publications` / `corpus_pull_events`（`ensure_schema`，纯新增），
   并把它们加入 `_REQUIRED_TABLES`（与 `add-typed-publications` 同一条纪律：
   DDL 没落地时不得声明 schema ready）。
2. 实现投影与两层 digest，先在**只读副本/测试库**对一个源跑通。
3. 挂拉取路由（`libraries/` 前缀，与既有通配路由路径空间不相交）。
4. 生产对 `law-library` 发布一版，用已登记消费者拉清单 + 取单文档正文，比对 `doc_digest`。
5. 回退：路由与表可留在原地（纯新增、无消费方即无影响）；不从库读取即可停用发布。

## Open Questions

- 清单是否也要覆盖 `pgvector-external` / `text-table` 后端（`text-library` / `case-library`）？
  本轮只做 `qdrant`；`ingest_rule.document` 在另外两种后端上的对应字段尚未核实，
  留待它们真的需要发布时再定——不影响本变更的契约（契约只要求「文档身份 + 正文 + 顺序」三者可由
  库的摄取口径给出）。
