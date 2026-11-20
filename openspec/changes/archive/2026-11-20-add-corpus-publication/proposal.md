## Why

`docs/knowledge-platform-blueprint.md` §六 写下「本体 / RAG 语料 / 金集三类均可发布」，前两类今天才各自落地了一半：`knowledge-distribution` 发布本体，`add-typed-publications` 发布尺子与金集，**RAG 语料的发布一直只有一句话**。

后果同样具体。法规语料在 Qdrant `law_chunks_v2` 里已有 **365,938 块 / 32,251 部法规**，`law-library` 已登记、legal 与 gov 两个域已在订阅它。但「这个域能检索到哪些法规」是一个**会变的视图**：库重新摄取一次，同一个查询今天就可能命中昨天没有的条文。而 `eval-verdict-ledger` 已经把「baseline 可比性」立成了要求——两条结论只有在同一份被评对象（daiest 相同）时才可比。语料没有 digest，RAG 侧的任何结论都无法回答「你当时读的是哪一版语料」。

为什么现在做：尺子已经能发布了（`add-typed-publications` 上产），舰队能拿到不可变的评测标准；它接下来要读的**依据**却仍是活的。只把尺子钉住、不钉语料，等于只锁了一半的可比性。

## What Changes

- **发布单位是「库」，不是域**——沿 `shared-corpus-library` 的既有身份（库有稳定 `library_key`，域只是订阅者）。语料是「一次投入、多域取材」的共享物理层，把它塞进域目录语义会让同一份内容在两个域下发布出两份版本序列。
- **冻结粒度是「法规/文档」，不是块**——块的边界与序号会随切分器变化，按块冻结会让一次切分器升级作废所有历史 digest，且清单里全是机器序号、没有人能核对。
- **digest 分两层，复用同一个规范序列化内核**——每部法规用自己的 canonical JSON 取 digest（约 4.5 KB/法规，单条内存无忧），再对「按 `law_id` 排序的 `(law_id, per-law digest)` 清单」取总 digest。**MUST NOT 为语料写第二份 digest 实现**；也 MUST NOT 把 147 MB 全量投进一次 `json.dumps`（实测平台 pod 限 512 Mi）。
- **拉取面分两级**：清单端点给版本、总 digest 与每部法规的 `(law_id, title, digest, 块数)`（可分页），正文按法规取。MUST NOT 一次返回全部正文（单次响应会到 147 MB，等于把问题从发布挪到拉取）。
- **只读外部后端**：`law-library` 的后端是 `qdrant`（外部只读），本变更**只读**它，不写、不迁移、不改摄取口径。
- **非目标**：不动 `shared-corpus-library` 的订阅语义与检索路径；不做语料的增量回填/纠错（发布只描述现状）；不发布向量（向量是后端的实现细节，digest 只锚定正文与身份）。

## Capabilities

### New Capabilities

- `corpus-publication`: 语料库的版本化发布契约——以库为单位、以法规/文档为冻结粒度、两层 digest、清单式拉取与按文档取正文，以及「发布只读、不改订阅范围」的边界。

### Modified Capabilities

（无。`shared-corpus-library` 的登记/订阅/取材范围与 `knowledge-distribution` 的本体发布均不变；本变更不复用 `asset_publications`，因为它按 `(domain, kind)` 编号，而语料的归属单位是库。）

## Impact

- **代码（law-bench-internal）**：
  - `src/bench/corpus_publication.py`（新）：库级投影 + 两层 digest + 版本序列。
  - `src/bench/workspace_store.py`：新增 `corpus_publications`（`library_id`, `version`, `digest`, `shape_version`, `manifest_digest_map`, `changelog`, `doc_count`, `chunk_count`, `published_by`, `published_at`）与 `corpus_pull_events`（消费者、库、版本、时间）。
  - `src/search/library_index.py`：新增「按文档枚举正文」的只读读取（Qdrant scroll + 按 `law_id` 分组），供投影复用——**不新增第二份 Qdrant 客户端**。
  - `src/web/routes/distribution.py`：`GET /api/v1/distribution/libraries/{library_key}/{kind}`（清单，分页）与 `.../{library_key}/{kind}/{doc_key}`（单文档正文）。
  - 发布动作：`POST /admin/libraries/{library_key}/publish`（`admin` scope + 库级写入授权）。
- **文档**：新增 `docs/corpus-publication-contract.md`（两层 digest 配方、清单形状、分页协议）。
- **依赖**：无新增。读取沿用既有 `library_index` 的 Qdrant 访问路径（`QDRANT_URL` 环境变量已在生产 pod 内）。
- **风险**：① 32k 部法规的投影是一次长读（实测 scroll 全量约 37 页 × 10k 点）——必须限量与超时，不能拖垮 512 Mi 的 pod；② 清单端点可能被客户端当成「全量下载」——分页 + 显式上限必须写进契约；③ 库重新摄取会让 digest 变化，消费者必须能按版本号钉住旧版。
