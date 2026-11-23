
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

## 部署验收（2026-11-24，add-domain-next-actions 2.2/2.3/2.5）

- 代码：`2373066` 区页横幅 + 无成员空态 + 有事域优先排序；CI run 45254381569 test 绿
  （含此前 22 个 rubrics 缺表的红全部转绿——同批修复由 3d7bb9d 在 domain_rubrics 统一守卫）。
- 出片：law-template sha-2373066 → hkccr → ccr（digest sha256:51320980…，字节一致）。
- 部署：fd-infra-deploy c58f6404 两处 law-template 滚 → ArgoCD Synced @ c58f6404 → pod 翻到 sha-2373066。
- 生产浏览器验收（待下方填真库读数）。

### 关键设计修正（本轮实撞）

区横幅（§2.2）调 `estate.matrix` 会在**每个区页**读 `rubrics` 表并（在 knowledge 页）
对同一 Qdrant 存储再发一次 `/points/count`：

- `test_page_does_not_count_the_same_store_twice` 断言一页只扫一次 → 横幅二次扫描是真回归。
  修法：`estate.matrix` 增可选 `scope_cache`，knowledge 路由把自己已算的 `lib["chunks"]`
  转成同形缓存透传给横幅（键 `(library_key, sorted(sources))`，与 `count_scope` 一致）。
- rubrics 缺表在 `empty_db` 夹具上会让横幅抛 `UndefinedTable` → 3d7bb9d 在
  `domain_rubrics` 统一守卫（表不存在时读面答「没有标准」），横幅不再需要兜底 try/except。
- `domain_context.console_context` 签名用到 `Optional` 却未导入——已补导入（否则注解解析会
  NameError）。注：本机 import 慢 ~40s 经对照 HEAD(无本次改动) 同样 40s，属环境（本地
  `.env` 指向的服务探测超时），不是本改动的锅。

## §4 验收（2026-11-24，收尾）

- 部署 sha-399e3c8（含 h2 i18n 键修正）→ hkccr → ccr（digest sha256:7c5b1785…，字节一致）
  → fd-infra-deploy d236b541 滚 → ArgoCD Synced@01455cf9 → pod Running。
- 生产浏览器：
  · `/d` 全域矩阵：法律域→「去提案箱逐条确认」；政务/ERP/金融（0 成员）→「还没有成员 / 邀请成员」。
  · `/d/legal/ontology` 区横幅：标题正确渲染「这一区接下来做」（h2 键修正后不再显示字面键名），
    一条动作「「crosswalk」指标 0.0002，低于下限」→「查看并修复该质量项」，allowed=1。
- 「零域身份」未在浏览器走：无现成的零域 Logto 测试账号（管理员看到全部域），空态分支
  由 `test_domain_list...` 与 domain_list 既有 empty_h1 分支覆盖；真数据触发需建新 Logto 用户，
  超出本 change 范围，如实记录未走该路径。
