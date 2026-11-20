# 按种类的资产发布契约（`asset_publications` / `GET /api/v1/distribution/{domain}/{kind}`）

> 变更 `add-typed-publications`。`docs/knowledge-platform-blueprint.md` §六 承诺三类可发布资产
> （本体 / 尺子 / 金集），其中**只有本体**有不可变发布版本。这份文档写的是另外两类走的那条
> 契约：种类怎么注册、条目怎么投影、digest 从哪来、拉取面长什么样。
>
> 本体不走这条路：它的契约是 `knowledge-distribution`（`GET .../ontology`），
> 载荷与 digest 配方**一行不改**——生产上 `legal` 的 v2 digest `5897354d…` 已被消费方持有。

## 一句话

发布 = 把「这个域书架上某一类的条目」冻结成一版**带 digest 的不可变快照**。
只有快照可比，两次评测的分数才有意义；「当前生效的尺子」是会变的视图，不能当判据。

## 种类由 pack 注册，内核不认识行业

内核（`src/bench/publication_kinds.py`）只提供注册表和投影机制。一个域 pack 在
`asset_catalog.py` 里声明自己有哪些种类可发布：

```python
PUBLICATION_KINDS = {
    "rubric": {
        "relation": "<自包含 SELECT：asset_key, name, summary 三列>",
        "label_key": "bench_catalog.kind.rubric",   # console 展示名
        "sort_key": "name",                          # 条目排序键（summary 亦可）
        "shape_version": 1,                          # 投影形状版本
    },
}
register_kinds(PUBLICATION_KINDS)
```

| 字段 | 语义 |
|---|---|
| `relation` | 自包含 `SELECT`，**恰好三列**：`asset_key`（条目身份）、`name`（展示）、`summary`（内容摘要，进 digest） |
| `label_key` | i18n 键；内核只转发，不解释 |
| `sort_key` | 排序所用列名；条目按 `(sort_key, asset_key)` 排序，因此 payload 是内容的纯函数 |
| `shape_version` | 正整数。**位于载荷之外**——改它不改 digest |

未注册的种类在发布与拉取两处都被**拒绝并列出已注册种类**；不返回空清单冒充成功。

## 条目投影

投影只读这个域的**书架**（`domain_assets`），不读别的域，也不读未归属的池子：

```sql
SELECT a.asset_key, a.name, a.summary
FROM domain_assets da
JOIN (<relation>) a ON a.asset_key = da.asset_key
WHERE da.domain_id = %s AND da.asset_kind = %s
```

- 条目规范成固定键集 `{asset_key, name, summary}`；缺值为 `""`（不是 `null`），
  这样后加的列不会造出幻影 diff。
- 重复 `asset_key` = 内容损坏，发布**报错**而不是静默合并。
- 零条目 = 「无可发布内容」，**拒绝**，不产生空版本。

## digest 只有一份实现

投影结果交给既有的 `distribution.canonical_digest()`（内核
`fd_ontology_kernel.manifest.digest_of`：键序归一、排除生成时间戳）。**不为新种类写第二份
digest**——两份实现对「同一内容」判定不一致时，跨面比对就失去意义。

`digest = sha256(canonical_json({"asset_kind": …, "entries": [...]}))`，`shape_version` 不在其中。

推论（都是特性，不是缺陷）：

- 同一份尺子被两个域各发布一版，digest 相同——它本来就是同一把尺子。
- 只升 `shape_version`：digest 不变，发布走幂等路径，返回既有版本。

## 发布（`distribution.publish_asset_kind`）

```
publish_asset_kind(conn, *, domain_key, asset_kind, published_by) -> publication
```

1. 未注册种类 / 未知域 / 空投影 → `ValueError`（web 面转成失败 flash / 400）。
2. 该 `(domain, kind, digest)` 已存在 → 原样返回既有行，**不新增行**（幂等）。
3. 否则版本 `max(version)+1`，changelog 是对同 `(domain, kind)` 上一版的 diff：
   - 首版：`{"initial": true, "counts": {"entries": N}}`
   - 其后：`{"added": [...], "removed": [...], "changed": [{"key", "fields": {f: {before, after}}}], "counts": {...}}`
4. 发布**不改归属**：`domain_assets` 一行不动；解除归属也不影响已发布版本的可用性与 digest。

`asset_publications` 是 append-only：没有 UPDATE/DELETE 代码路径。

## 拉取面

```
GET /api/v1/distribution/{domain_key}/{kind}[?version=N]
X-Consumer-Token: <登记时一次性给出的明文>
```

鉴权沿用既有的**三态**实现（`_authenticate_consumer`，不复制一份）。**顺序是先鉴权、再解析种类**：
匿名调用拿到的是 401，而不是「这台部署发布了哪些种类」的清单。

| 情形 | 状态 | detail |
|---|---|---|
| 无请求头 | 401 | `缺少机器凭据：X-Consumer-Token 请求头` |
| 令牌未登记 | 403 | `令牌未登记` |
| 令牌已吊销 | 403 | `令牌已吊销` |
| 域不在绑定范围 | 403 | `该域不在绑定范围` |
| 未注册种类 | **400** | 列出已注册种类（不是 404——404 会说「路径写错了」） |
| 无该种类发布 / 无该版本 | 404 | `该域尚无 {kind} 发布` / `该域无 {kind} 版本 v{N}` |

`kind=ontology` 映射回既有 handler，载荷与 today's wire 拉取**逐字节一致**。

响应（JSON，插入序）：

```json
{
  "domain": "legal",
  "kind": "rubric",
  "publication_version": 1,
  "digest": "<sha256>",
  "shape_version": 1,
  "label_key": "bench_catalog.kind.rubric",
  "entries": [{"asset_key": "…", "name": "…", "summary": "…"}],
  "changelog": {"initial": true, "counts": {"entries": 2}}
}
```

**拉取足迹**：只有成功解析到版本才写 `asset_pull_events`（消费者、域、种类、版本、时间），
append-only；失败与未匹配不落行。写入失败不改变已算好的响应（不让足迹把一次成功拉取变成 500）。

## 控制台

`/d/{domain_key}/publish` 的「按种类的发布」区：每个种类一块，各自版本号、digest 全文、
形状版本、条目数、最近拉取足迹；缺数据的种类显示**自己的**空态。发布按钮**按种类分开**，
一次只发一类。版本号按 `(domain, kind)` 独立单调，界面不合并计数，也不承诺跨种类可比。

## 路由顺序（改这个文件前必读）

`/api/v1/distribution/{domain_key}/{kind}` 的通配段与既有的 `/ontology`、`/rulers`、
`/crosswalks`、`/verdicts`、`/runs`、`/work-orders`、`/proposals` **同形**。FastAPI 按注册
顺序匹配，所以这条通配路由必须注册在那些固定路径**之后**（它目前在
`src/web/routes/distribution.py` 末尾附近）。挪到前面就会静默遮蔽它们在跑的路由——
判据不是「新路由能通」，而是「旧路由仍返回它自己的 detail」。
