
## 部署验收（2026-11-24，add-domain-next-actions 2.1）

- 出片：PR#4(后端) + PR#5(总览清单) 合并 main → image workflow 出 sha-8b5e7e1（CI test 绿）
- 部署：fd-infra-deploy 84acf017 滚 law-bench web（deployment.yaml 两处 law-template）→ ArgoCD Synced → pod Running 1/1 @ sha-8b5e7e1
- smoke_prod：PASS 13 checks
- 生产浏览器验收（ego，legal 域）：`[data-testid="next-actions"]` 渲染「接下来做」，
  两条动作且顺序正确（review_backlog 先于 quality_below_floor）：
  · 「5 条提案待确认，最老已等 299.88 小时」→ 去提案箱（数字逐字来自 review_lag 实时值）
  · 「「crosswalk」指标 0.0002，低于下限」→ 查看并修复
  ⇒ 后端投影 + 总览 UI 端到端在真库/真部署上成立。
- 期间修两处真 bug（CI image test 抓到）：理由模板 metric/value KeyError、误删「我的任务」标题。
