# 生产核查（2026-11-19，只读）

只读核查，**未做任何生产写入**。用途：回答 design 的两个 open question，并为任务 3.1 的拉取验证准备判据。

## 一、wire 生产（pod `fd-wire-api-864797449f-ks6md`，ns `fd-prod`）

### BENCH_PULL_* env（pod 内实测）

```
BENCH_PULL_URL=<unset>
BENCH_CONSUMER_TOKEN=<unset>
BENCH_PULL_ENABLED=<unset>
BENCH_PULL_DOMAINS=<unset>
```

**结论：生产订阅确实是关的**，不只是清单里没写——pod 环境里一个都没有。

### `fd-wire-env` Secret 键清单（只列键名，未读值）

Unscoped 检查：**无 `bench_consumer_token` 键**。31 个键里没有与知验台相关的那一项。

### 快照与拉取史（wire 元数据库 `wire_platform` @ 100.64.0.12:5433）

```
SNAPSHOTS: [('legal', 1, '3586552a', '2026-11-06 04:06:55')]
PULL_LOG:  [('legal', True, 2), ('legal', False, 1)]
```

回答 design 的 open question ①：**2026-11-06 那条 legal v1 快照还在**（digest `3586552a`，正是蓝图台账记的联调冒烟版）。所以任务 3.1 的验证将是「再次成功」而不是「首次成功」——措辞按此调整，不影响任何步骤。

## 二、bench 生产（pod `law-bench-79d768694c-5q9n9`，ns `law-bench`）

```
CONSUMERS: [('fd-wire', ['legal'], 'machine', None, False),
            ('ontology-fleet-win', ['legal'], 'fleet', 'fleet_1794335712751_wfa3ww', False),
            ('ontology-fleet-i28xac', ['legal'], 'fleet', 'fleet_1793422472811_i28xac', False)]
DOMAINS:   [('legal',), ('archive-probe',), ('gov',), ('data-ontology',)]
PUBS:      [(domain_id=1, v1, '3586552a'), (domain_id=1, v2, '5897354d')]
```

三条结论：

1. **`fd-wire` 消费者登记存在且未吊销**（`kind=machine`，绑定域 `legal`）——任务 3.1 不需要新建登记，只需要令牌明文。
2. **回答 design 的 open question ②：生产里没有 `wire` 域**。四个域是 `legal` / `gov` / `archive-probe` / `data-ontology`。`archive-probe` 是域归档测试留下的（change `add-domain-archive`），不是业务域。
3. `legal` 域确有 v2 发布（`5897354d`），与官网锚点一致。

## 三、阻塞任务 3 的一件事实

`fd-wire` 登记只存 `sha256(token)` 摘要，明文**只在签发时展示一次**。本机与仓库内均无明文：

- `secrets/` 目录 16 个文件，无 BENCH_CONSUMER_TOKEN；
- `fd-wire/.env`、bench 私有仓的 `.env` 均无该键；
- paas 生产用同名 env 指向 `platform-secrets`，那是**另一枚**令牌（舰队提案面），不是 `fd-wire` 这条登记。

所以任务 3.1 有两条路径，需用户裁决（**这是唯一需要外部输入的一步**）：

| 路径 | 动作 | 代价 |
|---|---|---|
| **A. 轮换** | 用 `rotate_consumer_token` 给 `fd-wire` 登记换一枚新明文，写进 `fd-wire-env` 的 `bench_consumer_token` | 一次生产写（bench 读面 + wire Secret），旧令牌即刻失效；若别处有人在用旧令牌会断 |
| **B. 找旧明文** | 从签发那次操作的记录/操作者处取回 | 零生产写；但本机与仓库都没有，需人工回忆 |

两条都要求「先写 Secret 再开开关」，与任务 3.2 的顺序一致。
