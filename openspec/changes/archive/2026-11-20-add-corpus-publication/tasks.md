# Tasks: add-corpus-publication

> 依赖：无阻塞依赖。`add-typed-publications` 已上产（`sha-ffaf866`），本变更复用它的
> 「digest 只有一份实现」「足迹只增」「表进 `_REQUIRED_TABLES`」三条纪律。
> 铁律：`shared-corpus-library` 的登记/订阅语义与 `GET /api/v1/distribution/{domain}/{kind}`
> 的既有行为**一行不改**；不写外部后端。

## 0. 前置取证

- [x] 0.1 生产实测：`law-library` 七个源各自的文档数、块数与总正文体积，记成基线表
      （判据＝真实行；用于后面核对投影有没有漏源）
- [x] 0.2 核实 `ingest_rule.document.id` 在七个源内确实唯一（`law_id` 重复即数据损坏）；
      把重复样例与判定 SQL 写进 `docs/corpus-publication-contract.md`
- [x] 0.3 实测一次全量 scroll 的耗时与 pod 峰值内存，确认 512 Mi 下可行；不可行则把
      发布动作定为一次性 Job（契约不变，只换执行宿主）

## 1. 读取与投影

- [x] 1.1 `src/search/library_index.py` 增「按源枚举文档」的只读读取：逐页 scroll，
      `with_payload` 取 `document.id/title/text/order`，`with_vector=false`，
      每页上限与总时长上限显式可见
- [x] 1.2 逐文档流式投影：按 `doc_key` 分组、按 `order` 拼正文、读完即算 digest 并丢弃正文
      （常驻内存只与单部法规有关）
- [x] 1.3 空文档、缺 `doc_key`、`doc_key` 重复三类损坏数据分别报错并指明源与键，
      MUST NOT 静默跳过或截断
- [x] 1.4 超出总时长/页数上限时整体失败并报明，MUST NOT 产出「看起来成功」的半份清单

## 2. 两层 digest 与发布

- [x] 2.1 `src/bench/corpus_publication.py`：`doc_digest()` 与 `version_digest()`，
      两者都调用既有 `canonical_digest`（不新增第二份序列化实现）
- [x] 2.2 单测：同一部法规经投影与直接调规范序列化，doc digest 逐字节相等
- [x] 2.3 单测：只改 `shape_version` 时两层 digest 均不变；`chunk_count` 不参与任何一层 digest
      （改变切分块的表达方式后 digest 不变）
- [x] 2.4 `publish_library()`：版本单调 + 同 digest 幂等（返回既有版本、行数不变）+
      空库拒绝 + changelog（新增/移除/变更，变更带新旧 doc digest）
- [x] 2.5 发布只读断言：单测里让后端读取被代理记录，发布全程零写入调用

## 3. 数据与迁移

- [x] 3.1 DDL：`corpus_publications`（`library_id`, `version`, `digest`, `shape_version`,
      `manifest`（文档清单）, `changelog`, `doc_count`, `chunk_count`, `published_by`,
      `published_at`；唯一 `(library_id, version)` 与 `(library_id, digest)`，append-only）
      与 `corpus_pull_events`（消费者、库、版本、时间）；进 `ensure_schema`
- [x] 3.2 两表加入 `_REQUIRED_TABLES`（DDL 没落地时不得声明 schema ready）
- [x] 3.3 `tests/test_boot_schema.py` 扩：空库跑 boot 后两表就位、重复执行幂等

## 4. 拉取面

- [x] 4.1 `GET /api/v1/distribution/libraries/{library_key}/{kind}`：清单分页
      （`cursor` + `limit` 上限 + `next_cursor` + `total_docs`），`?version=N` 钉住历史版本
- [x] 4.2 `GET /api/v1/distribution/libraries/{library_key}/{kind}/{doc_key}`：单文档正文 +
      其 `doc_digest`；文档不在该版本时明确报错，不返回空正文
- [x] 4.3 三态鉴权复用既有 `_authenticate_consumer`（先鉴权再解析库），不复制一份
- [x] 4.4 足迹：仅成功解析到版本才写 `corpus_pull_events`；403/404 不写
- [x] 4.5 回归断言：既有 `GET /api/v1/distribution/{domain}/ontology` 与 `/rulers`、
      `/crosswalks` 的响应与状态码逐字节不变（`libraries/` 前缀不得遮蔽它们）
- [x] 4.6 单测：清单分页翻页不漏不重、末页 `next_cursor` 为 null、越权 403 不留足迹

## 5. 控制台与文档

- [x] 5.1 库管理面显示每个库的发布历史（版本、总 digest、文档数、块数、发布时间）
- [x] 5.2 `docs/corpus-publication-contract.md`：两层 digest 配方、清单形状、分页协议、
      单文档核对步骤、已知限制（只支持 qdrant 后端）
- [x] 5.3 蓝图 §八 Change 台账补本行

## 6. 验收

- [x] 6.1 生产对 `law-library` 发布一版：记录版本号、总 digest、文档数、块数与实测耗时
- [x] 6.2 用已登记消费者拉清单分页至末页，抽样 3 部法规取正文并逐字核对 `doc_digest`
- [x] 6.3 回归：本体发布/拉取、typed publication 发布/拉取四条既有场景全绿
- [x] 6.4 `openspec validate add-corpus-publication --strict` 绿
- [x] 6.5 `acceptance.md`：逐条判据 + 真库读数（未达标的如实写，不造绿）

## 7. 挂账

- [x] 7.1 另两种后端的文档身份映射 —— **已把「缺什么」变成可读清单**（`publish_corpus.py --check`）。
      生产实测：`law-library` 7/7 源可发布；`text-library` 0/4（`gov` 缺 order，`news`/`papers`/`screenplay` 四个角色全缺）；
      `case-library` 0/1（`columns` 形状缺 order）。**具体的文档身份必须由语料方定义**，代码无法猜——清单交给来人即可。
- [x] 7.2 库级 owner —— 已做：`libraries.owner`（NULL=仅平台管理员，与加列前行为一致）；
      命名后可不受 admin scope 发布本库；控制台可设；`may_publish()` 对未知库 fail-closed。
- [x] 7.3 发布迁独立执行宿主 —— **结论已按两次实测 OOM 修正**：不是「换个进程」而是「换个 Pod」。
     exec 进应用 pod 的进程与 web 进程**共享同一 cgroup**（512 Mi），实测两次 exit 137：
     一次请求内联、一次 pod 内 exec。正确宿主=`jobs/corpus-publish-job.yaml` 的独立 Pod
     （自带内存上限）。路由已改 409 并指名脚本；中途被杀不留半条记录（两次 OOM 后 `corpus_publications` 均 0 行）。
