# law-bench 上产记录（2026-11-20）

## 链路与判据

```
law-bench-internal 3c5dd62
  → image workflow 44721433619 全绿（test 2367 passed + build-push）
  → 铸 tag sha-3c5dd62 = sha256:78eccd3d…
  → relay 自动搬到 ccr（实测 digest 796f2a85… 与 hkccr 一致）
  → fd-infra-deploy 202e781e 改 tag（2 处）→ GitHub → Gitee 镜像
  → ArgoCD 拉取 → kubectl 实测已滚
```

## 运行时实证（不信 manifest，信 pod）

| 判据 | 结果 |
|---|---|
| deployment image | `law-template:sha-3c5dd62` ✓ |
| pod 状态 | `1/1 Running`，`RESTARTS 0` |
| base.html 含「介绍站」 | 1 处 ✓ |
| console.py 含 console_promotion | 3 处 ✓ |
| i18n.py 含 gap_quality_evidence | 2 处 ✓ |
| `/d/legal/promotion` | **401**（路由存在，要鉴权） |
| `/dashboard` | **401** |
| 对照：`/d/legal/nonexistent-route-xyz` | **404**（证明 401 不是兜底） |

## 回滚

`fd-infra-deploy` 把 tag 改回 `sha-4e5a2ea`。

## 过程中修掉的两个真问题

1. **顶栏加「仪表板」撞了退役守卫**：image workflow 前两次失败都因
   `test_nav_is_english_after_switch` 断言 `>Dashboard<` 不得回 chrome。守卫是对的——
   顶栏扁平工具菜单是 §5 明确退役的。改挂 `/d` 正文。
2. **i18n 缺 `estate.dashboard_hint`**：模板用了键而 i18n 没有（一次 python 批量替换
   静默失配），会渲染成空白。已精确补中英两键并实测解析。

## 缺口（如实）

- 本机 `argocd` CLI 指向 `23.144.68.246:30910`——那是「不是我们的机器，禁止访问」。
  全程未使用它；集群验证改走 `root@100.64.0.8` + `~/.kube/config-cheap13`。
- 登录后的页面内容未在浏览器里目视（需真实 Logto 账号），只验到路由层与模板文件层。
