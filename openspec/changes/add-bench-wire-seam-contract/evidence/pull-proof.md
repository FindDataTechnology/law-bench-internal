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
