# Acceptance — add-corpus-publication

> 判据逐条取自 `specs/corpus-publication/spec.md` 与 `tasks.md`。每条写**判据**（怎么判）
> 与**读数**（实际结果）。真库读数没跑到的行如实写「待跑」，不写成通过。

## 上产基线

| 项 | 值 |
|---|---|
| 镜像 | `sha-3c5dd62`（GitOps `fd-infra-deploy@202e781e`，ArgoCD `Synced/Healthy`） |
| Pod | `law-bench-55db784ddf-zgmwc`，`1/1`，`restarts=0` |
| 镜像内确认 | `iter_documents` ✓、`scripts/publish_corpus.py` ✓、发布路由 409 ✓ |
| 新表 | 上产前 `to_regclass` 为 NULL；上产后两表就位（boot 的 `ensure_schema` 自动执行） |
| 本体回归基线 | `ontology_publications` 仍是 legal v1 `3586552a…` / v2 `5897354d…`，`published_at` 未变 |

## 1. 生产实探（不依赖发布，已验）

| 判据 | 读数 |
|---|---|
| 无凭据 → 401 且指名请求头 | `401 缺少机器凭据：X-Consumer-Token 请求头` ✓ |
| 未登记令牌 → 403 | `403 令牌未登记` ✓ |
| 未知种类 → **400 并列出合法值** | `400 kind must be one of ['corpus', 'documents']` ✓ |
| 未发布时拉取 → **404，不是空清单** | `404 该库尚无发布` ✓（清单与单文档两条路径都是） |
| 路由不互相遮蔽 | `legal/ontology`、`/rulers`、`/crosswalks`、`libraries/…/corpus` 各自命中自己的 handler ✓ |
| **发布不在请求路径执行** | 路由源码含 `status_code=409`、指名 `publish_corpus.py`、且**不含** `publish_library(` 调用 ✓ |
| 内存余量的实证 | web 容器 `memory.current` = **470 MB** / `memory.max` = **512 Mi** → 余量 **62 MB** ✓（内联发布必 OOM，这正是上一条的根据） |

## 2. §6.1 真库发布

**待跑** —— 已在生产 pod 的独立进程里执行
`scripts/publish_corpus.py law-library --by rehearsal:6.1`，约 18 分钟（逐文档 33.7 ms × 32,251）。
完成时在此填：版本号 / 总 digest / 文档数 / 块数 / 实测耗时。

## 3. §6.2 清单分页 + 逐文档核对

**待跑** —— 依赖 §6.1 的版本行存在。判据：
- 分页翻到 `next_cursor` 为 null，文档数 = `total_docs`，无重复无遗漏；
- 抽样 3 部法规（首/中/末）取正文，`doc_digest` 与清单逐字节相等，`body_matches: true`；
- 足迹行数 = 清单页数 + 文档请求数。

## 4. §6.3 既有场景回归

| 场景 | 读数 |
|---|---|
| 本体发布 / 拉取 / 幂等 / 换底 digest | 生产两行 digest 与 `published_at` **逐字节未变** ✓；CI `tests/test_distribution_kernel.py` + `test_distribution_web.py` 绿 |
| typed publication（尺子/金集）发布 / 拉取 | CI `tests/test_typed_publications_*.py` 30 条绿 ✓ |

## 5. CI 闸

| 闸 | 读数 |
|---|---|
| `tests/test_corpus_publication_kernel.py` + `_web.py` | ✅ 通过（CI `Knowledge Surface Integrity` 的 Corpus publication gate） |
| 内核领域无关 + 包边界 | `scripts/check_kernel_domain_free.py` → `OK (42 files)` ✓ |
| `openspec validate add-corpus-publication --strict` | ✅ valid |
| 全量套件（image workflow test job） | ✅ 2367+ passed（`3c5dd62`） |

## 6. 本轮修正的三个设计错误（都有实测读数）

1. **「512 Mi 下完全可行」是错的**：最初 35 MB 的读数来自裸 urllib 脚本，不含应用 import。
   实测 import + 枚举就要 111 MB，而服务进程常驻 470 MB / 上限 512 Mi。
2. **单遍流式方案被 OOM 杀掉**（exit 137）：它需要整页块驻留。已删除，退回逐文档。
3. **逐文档 = 18 分钟**，因此发布必须移出请求路径（409 + 独立脚本 + Job 模板）。

## 7. 挂账

- **7.1** `pgvector-external` / `text-table` 后端的文档身份映射（`text-library` / `case-library`）——另立。
- **7.2** 库级 owner 角色与发布授权细分——`libraries` 无 owner 列，加列是另一件事。
- **7.3** 发布迁独立执行宿主——**已在本轮按实证完成**：脚本 + Job 模板（`fd-infra-deploy/all-services/law-bench/jobs/`），路由改为 409。
