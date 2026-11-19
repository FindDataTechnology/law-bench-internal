# 生产拉取验证（2026-11-19）

任务 3.1–3.2 的执行记录。**值不在本文件**：令牌只经 env/Secret，本文只记指纹与结果。

## 0. 轮换前的判定

`fd-wire` 消费者登记（bench 生产，`distribution_consumers`）只存 `sha256`，明文已丢失。
本机、`secrets/`、两个 `.env`、prod `fd-wire-env` 均无明文。

paas 生产用的 `BENCH_CONSUMER_TOKEN` 是**另一枚**令牌——实测摘要指纹对比：

```
fd-wire 登记   sha256[:12] = 1379364b3901
paas 那枚令牌  sha256[:12] = 27a208f93c08   (不同)
```

结论：无法复用，走轮换（路径 A）。

## 1. 轮换（bench 生产写）

```
BEFORE: (id=1, name='fd-wire', domains=['legal'], kind='machine', revoked_at=None, token_hash[:12]='1379364b3901')
AFTER : (id=1, name='fd-wire', domains=['legal'], kind='machine', revoked_at=None, token_hash[:12]='fb0e2ac1e8e8')
```

身份键（id/name/domains/kind）零变化，只有凭据摘要移动——这正是
`rotate_consumer_token` 的契约（「同一 id、同一 name、同一 domains、同一 kind；
只有 digest 变」）。

**旧令牌确实是死的**：`bench_pull_log` 里那条 `ok=False` 的错误摘要是「对端拒绝：令牌未登记」，
说明在轮换之前旧明文就已经失效（登记摘要与任何现存明文都对不上）。

## 2. Secret 写入（wire 生产写）

```
kubectl patch secret fd-wire-env -n fd-prod --type merge -p <data.bench_consumer_token = b64(new token)>
secret/fd-wire-env patched
bench_consumer_token present: True
```

`optional: true` 是刻意的：键不在时 pod 照常起，拉取报 503 指名缺哪个 env——
「键没建」不该变成 pod 起不来。

## 3. 手动拉取（开关仍为 false，先验后开）

pod `fd-wire-api-864797449f-ks6md`（ns `fd-prod`）内直接调 `pull_and_store`：

```
PULLED version=2 digest=5897354d
```

库内核对：

```
SNAPSHOTS: [('legal', 1, '3586552a', 2026-11-06 04:06:55+00),
            ('legal', 2, '5897354d', 2026-11-19 10:20:22+00)]
PULL_LOG:  [('legal', True, 1, ''),
            ('legal', True, 1, ''),
            ('legal', False, None, '对端拒绝：令牌未登记'),
            ('legal', True, 2, '')]
```

- 新增一行 `ok=True`、version=2 —— 判据成立；
- v1 的 2026-11-06 历史行原样保留（append-only，未被覆盖）；
- digest `5897354d` 与 bench 侧 `ontology_publications` 的 v2 逐字相同，也与官网锚点一致。

**回答 design 的 open question ①**：那条 legal v1 快照确实还在，所以本轮是「再次成功」，
不是「首次成功」。

## 4. 翻开关

`deploy/k8s/fd-wire-api.yaml`：`BENCH_PULL_ENABLED` `"false"` → `"true"`。
回滚 = 改回 `"false"`。

## 5. 上产与实弹验证（2026-11-19）

出片 → 滚 tag → pod 验证，全链走完：

| 步 | 结果 |
|---|---|
| 出片通道 | 通用池 `testaction002/build-pool`（fd-wire 私有仓 Actions 额度耗尽，4-5s 即败） |
| 镜像 | `hkccr.ccs.tencentyun.com/fd-wire/api:sha-74468b9`，digest `sha256:974cef54…` |
| 内容闸门 | 铸出不可变 tag（内容确实变了） |
| smoke gate | boot 模式通过（`/health` 200） |
| ArgoCD | `Synced / Healthy / phase=Succeeded`，revision `5ae6e41` |
| pod | `fd-wire-api-669f68f85d-rcjqr` 1/1 Running，镜像 `sha-74468b9` |

### pod 内实测

```
BENCH_PULL_URL / BENCH_PULL_DOMAINS / BENCH_PULL_ENABLED /
BENCH_CONSUMER_TOKEN / BENCH_PULL_INTERVAL_SECONDS   —— 五项全部在

openapi paths:
  /api/v1/console/bench-ontology          <- 新面（登录态只读）
  /api/v1/internal/bench-ontology/{domains,versions,entities,relationships,pull}

snapshot_overview():
  [{'domain_key': 'legal', 'version': 2,
    'digest': '5897354d82a8…a726',
    'entity_count': 5117, 'relationship_count': 25,
    'pulled_at': '2026-11-19T10:20:22.987904+00:00'}]

pull_and_store(domain_key='legal')  ->  version 2
bench_pull_log: [('legal',True,1), ('legal',True,1), ('legal',False,None,'令牌未登记'),
                 ('legal',True,2), ('legal',True,2)]
```

### 鉴权边界（公网实测）

```
GET https://wire.finddatatech.cloud/api/v1/console/bench-ontology         -> 401
GET https://wire.finddatatech.cloud/api/v1/internal/bench-ontology/domains -> 401
```

两条都不带凭据时各自 401，且由不同的依赖拒绝（console 登录 vs
`X-Internal-Token`）——两套信任边界没有被合并。

## 6. 途中撞到并修掉的一个真缺陷

首次同步 **ArgoCD Failed**：

```
Deployment.apps "fd-wire-api" is invalid:
spec.template.spec.nodeSelector: Invalid value: "the node"
```

真因：提交 `f21a9e5 chore: public-readiness`（公开化消毒）把节点名**全局**
替换成占位符「the node」，连 `kubernetes.io/hostname` 的取值也一起换了。
label 值只允许 alphanumerics/-/_/.，所以 apply 直接被拒。

为什么此前没暴露：`f21a9e5` 从未到过 gitee（ArgoCD 源），而它之前的所有
提交里 ArgoCD 读到的都是 `cheap-6`。本次滚 tag 把这一串一起推上去才炸。
**表面上 `Synced/Healthy` 但新片根本没进去**——旧 ReplicaSet 在跑。

修：`5ae6e41` 把值恢复成 `cheap-6`（卷与 hostPath 都在该节点），注释同理
恢复并记下这个坑。渲染后的 YAML 已扫描确认无其它 apply-breaking 占位符
（剩余 `the node` 只在注释里）。

**这条要记**：公开化消毒会连 k8s 清单里的**取值**一起改，而注释与取值在
同一个文件里长得一样。消毒后必须渲染一遍 YAML 再应用，不能只看 diff。

## 7. 前端上产（2026-11-19）

只出 api 不出 web 等于没做完——读面在 web bundle 里：

| 步 | 结果 |
|---|---|
| 镜像 | `fd-wire/web:sha-e859390`，digest `sha256:face7dc7…`，smoke 通过 |
| 滚 tag | `6609629` → ArgoCD `Synced/Healthy/Succeeded` |
| pod | `fd-wire-web-67dcd7c8bc-7kfng` 1/1 Running |
| 公网 bundle | `assets/index-CGY6gOOZ.js` 含「标准本体」与 `console/bench-ontology` |

## 8. 跨仓 digest 对照（任务 5.4）

两侧各取一次读数，**逐字相等**：

```
bench  ontology_publications  : legal v2 5897354d82a83f525de00d9581dd759386aa9e686ac9acb9f0340c9794e4a726
wire   bench_ontology_snapshots: legal v2 5897354d82a83f525de00d9581dd759386aa9e686ac9acb9f0340c9794e4a726
```

这是「同一域、两侧各自查一次、逐字段一致」判据的成立形态——不是单侧自证。

## 9. 调度器自跑（任务 3.3，2026-11-19）

**不是手动的**——pod 启动 60 分钟后 `_loop()` 自己 tick 的：

```
pod started      : 2026-11-19T11:02:17Z
bench_pull_log 6 : 2026-11-19T12:02:49Z  legal ok=True v2   （间隔 60m32s ≈ 3600s 配置值）
```

完整拉取史（id 1-6）：

```
1  legal True  v1  2026-11-06 04:06:56   （C3 联调）
2  legal True  v1  2026-11-06 04:06:56   （幂等二拉）
3  legal False —   2026-11-06 04:07:28   对端拒绝：令牌未登记   <- 旧令牌死于此
4  legal True  v2  2026-11-19 10:20:26   （轮换后手动验证）
5  legal True  v2  2026-11-19 11:06:18   （pod 内路由调用）
6  legal True  v2  2026-11-19 12:02:49   <- 调度器自跑
```

无新增失败行。那唯一一条 `ok=False` 是轮换前的历史，恰好证明「轮换是必须的」。

## 10. 测试证据（任务 5.3）

**在 GitHub CI 跑，不在本机**（用户明令）。公开镜像仓 `scs001/fd-wire-images`
（先 `scripts/sync-public-mirror.sh --push` 同步源码到 6609629，再 dispatch
`build.yml`）：

| 作业 | 结果 |
|---|---|
| `api-gate`（阻塞闸：收集即判据 ≥1500 + 导入环用例） | **success** |
| `api-full-advisory`（全量，非阻塞） | 8 failed / 1984 passed / 14 skipped |
| 其余（build-push ×3、connector ×5、connector-test、connector-promote） | 全部 success |

**基线对照**（我的改动之前，run 44487074661 @ 08:26）：
**17 failed / 1964 passed**。

失败数 17 → 8（下降），通过数 1964 → 1984（+20，含本 change 新增的 5 条
`test_bench_ontology_pull` 用例）。8 条失败全在 `test_artifact_marketplace` /
`test_pipeline_graph` / `test_provenance_routes`，与 `bench_pull` 无关——
是既有的 CI 专属闪现场景（`build.yml` 里早有注释：全量走 advisory 不阻塞，
正是因为这个）。

**没有证据表明我引入了回归。**

## 11. 任务 5.2 的判定方式（没有跑 pytest）

`src/bench/promotion.py` 的改动只有 docstring。用 AST 剥掉所有 docstring 后
比对语法树：

```python
ast.dump(strip_docstrings(old)) == ast.dump(strip_docstrings(new))   # True
```

零代码路径变化 ⇒ 无回归可跑。规格侧 `openspec validate --strict` 两个 change
均绿。这是比「跑一遍看绿」更强的判据：它证明的是**不可能变**，不是**这次没变**。

## 12. 「拉取于」缺陷与修复上产（2026-11-19 晚）

### 缺陷

上一片的读面把快照行的 `pulled_at` 直接当「什么时候拉的」显示。但快照表按
`(domain, digest)` 幂等——**同一版本每小时重拉都命中既有行、不写新行**，于是
这个时间永久停在「该版本首次落库」。

实撞：调度器 `12:02:49Z` 刚拉过，读面仍显示 `10:20:22Z`。而这个页面存在的
唯一理由就是确认「同步还活着吗」——它给出的答案恰好是错的。

### 修法（`13a47c9`）

两个问题分开答，因为合并过一次就出错过：

| 字段 | 含义 | 来源 |
|---|---|---|
| `pulled_at` | 最近一次**成功**拉取（含幂等命中） | `bench_pull_log`（失败行不参与） |
| `version_pulled_at` | 这一版首次落库 | 快照行（不可变，此值不动） |

前端两者不同时都显示：主时间答「同步活着吗」，括注答「这版哪天进来」。

### 上产过程的一次事故（如实记录）

第一次滚 tag **滚早了**：镜像还在 hkccr、relay 尚未回灌到 ccr 就改了 tag。
ArgoCD 立刻同步 → `ErrImagePull`；该 Deployment 是 `maxSurge: 0 /
maxUnavailable: 1`（零余量）→ 零副本 → `https://wire.finddatatech.cloud/health`
**503 约 2 分钟**。回滚 `sha-74468b9` 后恢复。

重来时先证 ccr 可拉（cheap9 `crictl pull` → `sha256:88098bcd…`），再滚
`3eb415d`。本次滚动 `/health` 全程 200。

**教训**（已入长期记忆）：出片链 hkccr → cheap9 relay（5 分钟一轮）→ ccr，
`build-push` 的「已铸 tag」指 hkccr，不是 ccr；零余量 Deployment 下任何镜像
风险都是全断，且 ArgoCD 对 ErrImagePull 仍报 `Synced`。

### 修复上产后的实测

```
pod: fd-wire-api-d5db779d7-pswq7   1/1 Running   image sha-9ac53d6
pulled_at         = 2026-11-19T13:02:56.602085+00:00   <- 最近成功拉取
version_pulled_at = 2026-11-19T10:20:22.987904+00:00   <- 这一版何时落库
bench_pull_log    = [7 ok 13:02:56, 6 ok 12:02:49, ...]
```

两个时间不同且都正确——缺陷已修。

### 服务面复验

```
/health                                    200
/console                                   200
/api/v1/console/bench-ontology   (未登录)  401
/api/v1/internal/bench-ontology/domains    401
ArgoCD: Synced / Healthy / rev=3eb415d
```

### 调度器稳态（两个自动 tick）

```
pod 启动 11:02:17Z
tick 1   12:02:49Z   ok=True  v2   （+60m32s）
tick 2   13:02:56Z   ok=True  v2   （+60m07s）
```

非人工触发，无失败行。任务 3.3 的「持续新增 ok=True」成立。

### CI 验证（`FindDataTechnology/fd-wire`，仓已转 public）

此前我误以为 fd-wire 仍是私有仓（Actions 额度耗尽跑不起来），实际它已转
public，`build.yml` 一直在跑。这一轮 CI 的价值立刻兑现：**抓到一条我自己
写错的用例**。

```
FAILED test_console_overview_pulled_at_tracks_last_ok_pull
assert '2026-11-19T14:01:14.541125'.startswith('2026-11-19T12:20')
```

真因不是产品缺陷：`log_pull` 的 `pulled_at` 由 `default=_utcnow` 落**当前
时刻**，比用例钉的 `first`/`later` 都新；我只把最后一行 UPDATE 到 `later`，
前一行仍是「现在」，于是它赢了 `ORDER BY pulled_at DESC`。修法（`11b9a13`）
是把该域**所有**日志行钉到 `later`。

复跑结果（run 44541439133）：

| 作业 | 结果 |
|---|---|
| `api-gate`（阻塞闸） | **success** |
| `api-full-advisory` | **1 failed / 1993 passed / 14 skipped** |
| 其余 10 个（build-push ×3、connector ×5、connector-test、connector-promote） | 全部 success |

唯一失败 `test_sensitivity_closure_render_recheck_after_ancestor_change` 是
`build.yml` 注释里早就注明的 CI 专属闪现场景（"同一棵树同一版本在 CI 红、
本地 15/15 绿"），与 `bench_pull` 无关。

本修复的两条新用例**在 CI 上转绿**；此前「只有 py_compile」的说法作废。
