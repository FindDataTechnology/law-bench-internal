# 语料发布契约（`corpus_publications` / `GET /api/v1/distribution/libraries/...`）

> 变更 `add-corpus-publication`。蓝图 §六 承诺三类可发布资产；本体走
> `knowledge-distribution`，尺子与金集走 `add-typed-publications`
> （见 `docs/asset-publication-contract.md`），这份写**第三类：RAG 语料**。
>
> 判据不是「接口通了」，而是**消费者能拿单部法规的正文与 digest 逐字核对**。

## 一句话

发布 = 把「这个库今天有哪些法规」冻结成带 digest 的不可变版本。只有快照可比，
检索侧与评测侧的结论才能回答「当时读的是哪一版语料」。

## 为什么单位是「库」不是「域」

语料是共享物理层（`shared-corpus-library`：「一次投入、多域取材」）。同一份
`law-library` 被 legal 与 gov 订阅。若按域编号，两个消费者对**同一份未变的语料**
会拿到两个 digest —— 而 digest 的唯一用途就是跨方核对。

所以版本序列挂在 `library_id` 上，消费者按**域订阅**获得授权：

```
消费者令牌绑定的域  →  该域是否订阅了这个库  →  是则授权
```

授权范围取该域的**有效源集合**（父域继承 + 只收窄），与检索路径用同一个
`libraries.effective_sources` —— 只有一处定义「这个域能读什么」。

## 为什么粒度是「文档」不是「块」

块的序号与边界是**切分器的产物**。按块冻结意味着切分策略一调，32k 部法规的
历史 digest 全部作废，而正文一个字都没变。

清单项：`doc_key`（即 `ingest_rule.document.id`，生产上是 `law_id`）、`title`、
`source_key`、`chunk_count`、`doc_digest`。

**`chunk_count` 进清单但不进任何 digest** —— 它让消费者看得出「重新切过块」，
但不会因为重新切块而改 digest。

## digest 两层

```
doc_digest(doc)   = canonical_digest({"title": 标题, "body": 该法规全部块按 order 拼接})
version_digest    = canonical_digest({"documents": [{doc_key, doc_digest}, ... 按 doc_key 排序]})
```

两层都调 `src.bench.distribution.canonical_digest`（→ 内核 `digest_of`）。
**不写第二份实现**：两份实现对「同一内容」判定不一致时，跨方核对就失去意义。

为什么不是全量一次 sha256：全库正文约 **147 MB** canonical JSON，而平台进程限
**512 Mi**。实测单遍枚举 19.5 s、峰值 RSS **35 MB**；两层方案下常驻内存是
「一部法规 + 一份 32k 条清单（≈3 MB）」，与库的正文体积无关。

**`shape_version` 在载荷之外**，不参与任何一层 digest —— 升形状不作废已发出的 digest。

### 前提（实测，2026-11-20）

- 相邻块**无重叠**、`chunk_no` 连续（抽查 25 部法规：零重叠、零跳号）。
  因此「拼接全部块」就是「该法规的正文」。
- 若将来切分器改成滑动窗口重叠，拼接会重新依赖切分器 —— 那时应改为对
  **有序块列表**取 digest（仍不进块号，只进块内容与次序）。

## 发布

`publish_library(conn, *, library_key, published_by)`

1. 枚举（只读外部后端）→ 逐文档取正文算 `doc_digest` → 清单 → `version_digest`。
2. 该 `(library_id, digest)` 已存在 → 返回既有行，**不新增**（幂等）。
3. 否则版本 `max+1`，changelog 对上一版 diff：`added` / `removed` 为 `doc_key` 列表，
   `changed` 给出**新旧 doc_digest**（消费者据此知道是哪部法规变了）。
4. 空库拒绝，不产生空版本。

**只读铁律**：发布不写外部后端、不重新摄取、不改 `ingest_rule`。测试里用
`library_index._qdrant_post` 接缝断言全程零写入调用。

**失败即整体失败**：枚举超页数/超时长、正文触到分页上限、同一 `doc_key` 出现在
两个源、块缺 `law_id` —— 一律报错，MUST NOT 产出「看起来成功」的半份清单。
截断的 manifest 会让 digest 描述一份不存在的语料。

## 拉取面

```
GET /api/v1/distribution/libraries/{library_key}/{kind}?version=N&cursor=..&limit=..
GET /api/v1/distribution/libraries/{library_key}/{kind}/{doc_key}?version=N
X-Consumer-Token: <登记时一次性给出的明文>
```

`kind` ∈ `corpus` / `documents`（同义，保留两个名字是为了让调用方读起来自然）。

清单响应：

```json
{
  "library": "law-library", "kind": "corpus",
  "publication_version": 1,
  "digest": "<version digest>",
  "shape_version": 1,
  "total_docs": 32251, "total_chunks": 365938,
  "documents": [{"doc_key":"7","title":"常州市地下管线管理条例","source_key":"local",
                 "chunk_count":21,"doc_digest":"<sha256>"}],
  "next_cursor": "7",        // null = 末页
  "changelog": {"initial": true, "counts": {"documents": 32251, "chunks": 365938}}
}
```

- **分页必填**：`limit` 默认 200、上限 1000；`next_cursor` 是上一页最后一个
  `doc_key`。未知 cursor 返回 400 —— 静默从头开始会让客户端无限循环第一页。
- **清单不带正文**：一次返回全部正文≈147 MB，那是把体积问题从服务端挪到客户端。

单文档响应：

```json
{"library":"law-library","doc_key":"7","title":"…","chunk_count":21,
 "doc_digest":"<清单里的值>",
 "body_matches": true,        // 刚读到的正文是否仍哈希到清单里的 digest
 "body":"…"}
```

`body_matches: false` 表示外部后端在版本发布之后被改过 —— **版本仍是真相**，
后端不再匹配它；调用方必须知道这一点，而不是拿到一份悄悄变了的内容。

鉴权沿用既有的三态（401 / 403 未登记或吊销 / 403 越界），**先鉴权再解析库**：
匿名调用方不该从错误信息里得知这台部署有哪些库。

## 足迹

`corpus_pull_events`（消费者、库、种类、版本、时间），只增；只有成功解析到版本的
拉取才落一行，403/404 不落。

## 控制台

`/admin/libraries` 每个库下方是发布历史（版本、digest 全文、文档数、块数、发布人）
与「发布新版本」按钮。发布是 `admin` 平台权限：库独立于域树存在，把发布权绑到某个
订阅域的 lead 上，等于让一个域决定所有订阅者读到的版本。

## 已知限制

- **只支持 `qdrant` 后端**。`pgvector-external` / `text-table`（`text-library` /
  `case-library`）的文档身份映射尚未核实，另立。
- 发布是同步长操作（生产实测 32,251 部 / 365,938 块 ≈ 30 s）。目前够用；
  若库再大一个数量级，应迁到一次性 Job（契约不变，只换执行宿主）。
- 外部后端不可达时发布失败（报错而非发空版）；已发布版本不受影响。