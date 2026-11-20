# Acceptance — add-typed-publications

> 判据逐条取自 `specs/asset-publication/spec.md` 与 `tasks.md`。每条写**判据**（怎么判）
> 与**读数**（实际结果）。真库读数未做的行如实写「待跑」，不写成通过。

## 0. 基线：本体契约未被改动（判据 = 真实行）

生产库 `postgres/law_bench`（`kubectl exec -n postgres postgres-0 -- psql -U app -d law_bench`），
2026-11-20 读取：

```sql
SELECT d.key, p.version, p.digest, p.published_at
  FROM ontology_publications p JOIN domains d ON d.id = p.domain_id
 ORDER BY d.key, p.version;
```

| key | version | digest | published_at |
|---|---|---|---|
| legal | 1 | `3586552a01b041b777db3dc6c5252b5a275c2c138395d6c4088c6025d4674203` | 2026-11-06 03:25:44Z |
| legal | 2 | `5897354d82a83f525de00d9581dd759386aa9e686ac9acb9f0340c9794e4a726` | 2026-11-12 05:31:02Z |

**判据**：本变更实施后，同一查询必须返回**逐字节相同**的两行（digest 与
`published_at` 都不变）。任何差异即回归，不得接受。

## 1. 种类注册与投影

| # | 判据 | 读数 |
|---|---|---|
| 1.1 | `publication_kinds.list_kinds()` 在导入 `packs.legal.asset_catalog` 后为 `('rubric','sample')` | 本地实跑：`('rubric', 'sample')` ✓ |
| 1.2 | 未注册种类在发布与拉取两处都被拒且列出已注册种类；不返回空清单 | `tests/test_typed_publications_kernel.py::test_unregistered_kind_is_refused_naming_the_registered_ones`、`tests/test_typed_publications_web.py::test_unregistered_kind_is_400_naming_the_registered_kinds` — **待跑（执行通道待定）** |
| 1.3 | `packs/legal/asset_catalog.py` 为 `rubric`/`sample` 声明发布投影（键 + 名称 + 内容摘要） | 已实现：`PUBLICATION_KINDS`，`sample` 排除 `superseded_at IS NOT NULL`；两条 relation 在本地 PG 上 `PREPARE` 解析通过（真实 rubrics/criteria/contract_artifacts 列名） ✓ |
| 1.4 | 内核纯度：`src/bench/publication_kinds.py` 无行业字符串；未装 pack 时进程正常启动且 `list_kinds()` 为空 | 本地实跑：`scripts/check_kernel_domain_free.py` → `OK (41 files)`；子进程 `list_kinds()` → `[]` ✓ |

## 2. 发布

| # | 判据 | 读数 |
|---|---|---|
| 2.1 | `publish_asset_kind` 存在：投影 → `canonical_digest()` → 版本单调 → 幂等 → changelog | 已实现 `src/bench/distribution.py` |
| 2.2 | 同一内容经发布入口与直接调规范序列化，digest 逐字节相等 | `test_publish_digest_is_the_shared_canonical_digest` — **待跑** |
| 2.3 | `shape_version` 不进 digest：只改形状版本时 digest 不变、载荷内不声明它 | `test_shape_version_is_outside_the_payload_and_the_digest` — **待跑** |
| 2.4 | 空内容发布被拒且不产生行 | `test_empty_kind_cannot_be_published` — **待跑** |
| 2.5 | 同内容重复发布返回既有版本、行数不变 | `test_republish_is_idempotent_and_changes_produce_a_changelog` — **待跑** |
| 2.6 | changelog：新增/删除/变更（字段级 before/after）；首版为初始清单 | 同上（断言 added + changed.summary before/after） — **待跑** |
| 2.7 | 发布前后 `domain_assets` 行与归属域集合不变；解除归属后已发布版本仍可取 | `test_publishing_never_changes_ownership` — **待跑** |

## 3. 拉取面

| # | 判据 | 读数 |
|---|---|---|
| 3.1 | `GET /api/v1/distribution/{domain}/{kind}`；`ontology` 映射回既有 handler | 已实现，路由注册于所有固定路径之后 |
| 3.2 | 三态鉴权复用 `_authenticate_consumer`（401 / 403 未登记或吊销 / 403 越域） | 复用同一函数，未复制 |
| 3.3 | 仅成功拉取写 `asset_pull_events` | 已实现（足迹写失败不改变响应） |
| 3.4 | 成功留足迹 / 越域 403 不留 / 吊销 403 不留 / 未注册 400 列可用种类 | `tests/test_typed_publications_web.py` 五条 — **待跑** |
| 3.5 | `GET .../ontology` 字段集合与 digest 与基线逐字节一致 | `test_ontology_still_answers_with_unchanged_fields_and_digest` — **待跑**；另有 `.`/`/rulers` 遮蔽回归 `test_existing_fixed_routes_are_not_shadowed_by_the_kind_route` |

## 4. 控制台

| # | 判据 | 读数 |
|---|---|---|
| 4.1 | 发布区列三类（本体 / 尺子 / 金集），各自版本、digest、发布时间、历史；缺数据显示自己的空态 | 已实现 `domain_console_publish.html`「按种类的发布」区 + `ledger.typed_publication_layer`；zh/en 两套模板在桩上下文下渲染通过 ✓ |
| 4.2 | 发布按钮按种类分开，不一次发布三类 | `POST /d/{key}/publish/{kind}`，一类一按钮 |
| 4.3 | 消费层显示按种类的最近拉取足迹 | `ledger.typed_pull_layer`，模板每块显示「最近拉取」 |

## 5. 验收

**上产**：镜像 `sha-ffaf866`（GHA image.yml：test job 全量套件绿 → hkccr → relay → ccr），
GitOps tag 在 `fd-infra-deploy@ad21961`，ArgoCD synced/Healthy，pod `law-bench-6b7c8dc65c-sk8jc`
`1/1`、`restarts=0`。boot 的 `ensure_schema` 自动建表——**上产前**两表实测不存在，**上产后**
`to_regclass` 均返回表名。

| # | 判据 | 读数（真库，2026-11-20 06:0xZ） |
|---|---|---|
| 5.1 | 真库：legal 域发布 `rubric` 一版，用已登记消费者拉取，比对 digest | ✅ `domain_assets.assign(legal, rubric, contract_bailment_v1)` → `publish_asset_kind` 得 **v1 · digest `5a2bb76613a946f1411b91bd809b14ed54587444282d8bf430cd022fd819d699` · shape_version 1 · entries 1 · changelog initial**；经 `http://127.0.0.1:8010/api/v1/distribution/legal/rubric`（`X-Consumer-Token`）拉取 **HTTP 200**，digest **逐字节相同**；`asset_pull_events` 恰好 1 行（legal/rubric/v1）。演练后已 `unassign` 书架归属 + 吊销演练消费者（见下「演练残留」）。 |
| 5.2 | 回归：本体发布/拉取/幂等/换底 digest 五条既有场景全绿 | ✅ 生产 `ontology_publications` 两行 digest 与 `published_at` **与上产前逐字节一致**（`3586552a…` / `5897354d…`）；`/api/v1/distribution/legal/ontology` 实探 200，字段集合仍为 `{domain, template_name, template_version, publication_version, digest, entities, relationships, changelog}`。CI 里 `tests/test_distribution_kernel.py` + `test_distribution_web.py` 全绿（image workflow test job）。 |
| 5.3 | `openspec validate add-typed-publications --strict` 绿 | 实跑：`Change 'add-typed-publications' is valid` ✓ |
| 5.4 | 本文件 | 本文件 |

### 生产实探的附加判据（防「路由被遮蔽」这类静默回归）

在 pod 内用同一凭证打四条路径：

| 路径 | 期望 | 实得 |
|---|---|---|
| `/legal/ontology` | 200，字段集合不变 | 200，8 字段 ✓ |
| `/legal/rulers` | 走它自己的舰队校验（403 非 fleet） | 403「只有舰队登记可以调用该接口」✓ **未被 `/{kind}` 遮蔽** |
| `/legal/crosswalks` | 200 | 200 ✓ |
| `/legal/prompt` | 400 列出可用种类 | 400 `asset_kind must be one of ['rubric', 'sample']` ✓ |

pod 内路由注册序实测：`[ontology, runs, work-orders, proposals/outcomes, verdicts, verdicts/{run_id}, rulers, crosswalks, {kind}]` —— 通配段在最后。

### 演练残留（如实记录）

- `asset_publications` 留 **1 行**（legal / rubric / v1 / `5a2bb766…`）：不可变发布按设计不可删；
  它正是 5.1 的证据，且书架归属已解除，不影响任何域的内容。
- `asset_pull_events` 留 **1 行**（append-only 足迹）。
- `distribution_consumers` 多一条 **已吊销** 登记 `drill-typed-publication-5-1`（审计行）。
- `domain_assets` 复原为 0 行（与上产前一致）。

## 6. 挂账（明确不做，理由见 proposal 末节与 design D1）

- **6.1** RAG 语料发布（蓝图第三类）——体积与生命周期都不同，另立。
- **6.2** 跨域合并发布——无业务需求。
- **6.3** 把 `ontology_publications` 统一进 `asset_publications`——明确不做：wire 在生产按
  `.../ontology` 拉取且持有 digest `5897354d…`，搬表重算等于作废一条已上产的分发链。

## 已知风险

- **路由遮蔽**：`/{kind}` 与 `/rulers`、`/crosswalks`、`/verdicts`、`/runs`、`/work-orders`、
  `/proposals` 同形，靠**注册顺序**取胜。挪动本文件里的路由顺序会静默改掉那些在跑的路由的
  行为；`test_existing_fixed_routes_are_not_shadowed_by_the_kind_route` 是防它的判据。
- **两张表两处版本序列**：`ontology_publications` 与 `asset_publications` 各自单调，
  不承诺跨种类可比；界面不合并计数。
