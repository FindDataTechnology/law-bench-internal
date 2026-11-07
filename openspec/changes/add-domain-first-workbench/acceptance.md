# 验收报告 — add-domain-first-workbench（C5）

> 逐条判据 + 证据。**未清项如实列在 §3，不粉饰**。验收日期 2026-11-08。
> 视觉契约：`.impeccable/surfaces/bench-domain-console.md`（The Evidence Ledger · Operate）。
> 截图：`.impeccable/review/domain-console/<page>/{desktop,mobile}.png`（7 页 × 2 宽度，1280 / 390）。

## 0. 结论

**P0（门 / 域上下文 / 四层台账 / 提案箱 / 互认）与 P1（评测资产按域归属）全部交付并实证**；
P2（舰队提案目标切换）按提案边界属伴随 change，**未做**；一个**改动前就存在**的口令泄漏使
全量 pytest 停在 1 红，与本次改动无关（见 §3.1）。`openspec validate --strict` 绿。

| 项 | 结果 |
|---|---|
| `pytest` 全量 | **1385 passed / 60 skipped / 1 failed**（唯一失败为既有泄漏门，§3.1） |
| 新增测试 | 62（assets 10 / ledger 8 / proposals 18 / console 26） |
| `openspec validate add-domain-first-workbench --strict` | `Change 'add-domain-first-workbench' is valid` |
| 浏览器走查 | 7 页 × 2 宽度；`document.documentElement.scrollWidth` 全部 == 视口宽（零横向溢出） |
| digest 单源 | 页面 == `ontology_publications.digest` == 拉取面 `digest`（三处同值，有测试） |
| 跨仓 | `fd-official-web` 构建 237 页，产物含「进入控制台」CTA 与 `lawbench.finddatatech.cloud/d` |

## 1. 判据与证据（按 tasks.md）

### §0 前置

| 判据 | 证据 |
|---|---|
| 0.1 impeccable brief | `.impeccable/surfaces/bench-domain-console.md`（Mode=Operate；Direction 承接 No-shift；四层台账为本轮唯一新增签名件；反参考十一条） |
| 0.2 DDL 幂等 | `src/bench/workspace_store.py` 增 `domain_members.last_opened_at`、`domain_assets`、`domain_proposals`、`domain_proposal_events`、`distribution_pull_events` + 索引；`ensure_schema` 一次建齐（3 次 bootstrap 步骤在本机真库验证） |
| 0.3 asset 纯存储 | `src/bench/domain_assets.py`（446 行，`assign/list_for_domain/list_unassigned/unassign/purge_orphans/backfill`，**零路由**） |
| 0.4 提案存储 | `src/bench/proposals.py`（595 行）；`confirm` 只调 `_write_through_kernel` → `upsert_knowledge_unit`，无第二条 INSERT |
| 0.5 台账聚合 | `src/bench/ledger.py`（497 行）：四层聚合 + `reconcile()` 三类差集；`curation_layer` 返回 `rows`（声明序词表含 0 计数 + 出表 kind 标 `lane: out`） |
| 0.6 上下文复用 | `src/web/domain_context.py`（121 行）：`AREAS`、`capability()`、`visible_areas()`、`resolve_domain()`、`console_context()`；`touch_last_opened` |
| 0.7 i18n 骨架 | `src/web/i18n.py`：`nav.brand`、`console.*`（含 `ontology.col_actions/browse/new_unit`、`publish.changelog_*`）、`auth.about_bench/denied_read_about`，zh/en 成对 |

### §1 P0-A 门与域上下文

| 判据 | 证据 |
|---|---|
| 1.1 `/d` 我的域 | `GET /d` 200；列 active 成员域，`last_opened_at DESC`；零域诚实空态（会员 vs 平台管理员两种文案）；`domain_list.html` |
| 1.2 `/d/{key}` 总览 | 状态卡 4 数（本体单元 / 最新发布 / 待确认提案 / 我的任务）；打开 touch `last_opened_at` |
| 1.3 switcher + 面包屑 | `_domain_switcher.html` + `_domain_zone_nav.html`；原生 `<select>` + GET `/d/switch`，无 JS |
| 1.4 六区按角色过滤 | 测试断言：annotator 5 区、lead 6 区、平台管理员 6 区 + `管理员` 徽章 |
| 1.5 base 顶栏换形 | 品牌 → `/d`；顶栏只留 品牌 / 域指示+切换 / 语言 / 身份 / 平台门；11 条全局法律链接移出（`test_admin_web` + `test_authoring_web` 已按新契约重写，断言顶栏**不枚举**域） |
| 1.6 旧路径 302 | `/` → 302 `/d`；`/workbench/{key}` → 302 `/d/{key}`；非成员仍是 403 且**先于**跳转 |
| 1.7 双闸 | `require_scope(...)` → `require_domain_role(...)`；非成员 403 `无该域权限`，模板零域字段（测试断言响应体不含域名） |
| 1.8 设置区 | `GET/POST /d/{key}/settings`，`_LEAD_GATES`；成员/邀请读 `workspace_store`，平台级留在 admin 门 |

### §2 P0-B 四层台账

| 判据 | 证据 |
|---|---|
| 2.1 四层同页 | `/d/legal/ontology` 200；一张四行账页（`.layer-row` ×4，1px 规则线） |
| 2.2 声明层 | 模板名/版本、实体类型、关系种类、档位词表、敏感级词表；无模板锚 → 指平台门 |
| 2.3 策展层 | KU 总数、按 kind（标 entity/relationship lane）、按 tier 分布、最近 `authoring_events`；**每行带 浏览 / 新建 操作**（出表 kind 不给新建，非写手不给新建） |
| 2.4 发布层 | 最新 version/digest/published_at/changelog + 历史；无发布 → `尚无发布` 空态 |
| 2.5 消费层 | 消费者名/域范围/有效-已吊销/最近拉取版本（无则 `从未拉取`）；无 → `尚无登记消费者` 空态 |
| 2.6 一致性核对 | 零使用 kind、出表 kind（`.badge.bad` + 两条处置路径）、模板版本锚是否最新；一致时明说一致。**实测本轮报出 `belongs_to` 零使用** |
| 2.7 拉取足迹 | `distribution_pull_events` 仅成功拉取写、append-only；`test_distribution_web` 全绿（payload 字段集合未变） |

### §3 P0-C 提案箱

| 判据 | 证据 |
|---|---|
| 3.1 三态列表 | `/d/legal/inbox` 200；来源/种类/键/依据摘要/提交时间/状态/操作 |
| 3.2 确认 | `POST .../confirm` 303；`proposals.confirm` → 内核写；重复确认幂等（同 row 返回，不写第二次） |
| 3.3 驳回 | 理由必填（空 → 400 `驳回必须写明理由`）；同键同 digest 重提 → 400 `同键已驳回，需新证据`；换 digest 收 |
| 3.4 提交面 | `POST /api/d/{key}/proposals`；幂等键 `(domain, source, external_key, pending)`；缺依据 400；跨域 403 |
| 3.5 自提自确认禁令 | 2026-11-08 修：`[admin-override]` 只在**真的豁免了自提自确认**（`admin_override and submitted_by == actor`）时写入 —— 之前平台管理员确认**别人**的提案也会盖这个章，是一句不实的留痕。新增测试 `test_admin_confirming_someone_elses_proposal_writes_no_override_tag` |
| 3.6 单测 | 重复提交 3 次 1 条 pending；驳回同 digest 拒、换 digest 收；出表 kind 确认被拒且库无变化 |
| 3.7 计数同源 | 总览待确认数 == 提案箱 pending 行数（同一 `count_pending`）；清零显 0（实测 2 → 确认一条后总览与列表同为 1） |

### §4 P0-D 互认与兼容

| 判据 | 证据 |
|---|---|
| 4.1 登录页回链 | `login_denied.html` 经 `official_bench_url` 回链介绍页；base 身份区「关于知验台 ↗」 |
| 4.2 官网入口（外仓） | `fd-official-web`：`apps.ctaLabel` 新字段 + 两个 `[slug].astro` 渲染；`content/apps/{zh,en}/zhiyantai.md`（`demoUrl: https://lawbench.finddatatech.cloud/d`、`ctaLabel: 进入控制台 / Open the console`、`line: lex`、`order: 12`）；**构建通过 237 页，产物含 CTA 文案与 href** |
| 4.3 兼容表 | 11 条成员路径 + 2 条 admin 路径逐条断言可达且权限判定不变（`test_domain_console.py` 末尾两个兼容测试）；`/` 与 `/workbench/{key}` 走 302 |
| 4.4 双语 | 新键 zh/en 成对；域名称/key 来自数据、不进 i18n（`test_i18n` 系列全绿） |

### §5 P0-E 验收

| 判据 | 证据 |
|---|---|
| 5.1 浏览器链路 | 真 uvicorn + 真 Postgres + Playwright：登录态 → `/d` → 进 legal → 总览/本体/评测/提案/发布/设置 → 切换器；负例：非成员 403、零域空态（截图 7 页 × 2 宽度） |
| 5.2 digest 单源 | 页面 digest == `ontology_publications.digest` == `GET /api/v1/distribution/legal/ontology` 的 `digest`；本机真库值 `dc6e0bff…1b5ae5` 三处一致（`test_ledger_digest_is_the_published_digest_verbatim`） |
| 5.3 全链真跑 | 提案 #1（fleet/newco，提交人 expert-a）经控制台确认 → `knowledge_units` 由 3 条增至 4 条（`company/newco`）→ `authoring_events` +1（`op=create`、`via=authoring`、`operator=dev@local`）→ `domain_proposal_events` `pending→confirmed` → 提案箱显示 `已确认` + `影响：新增一条实体`，总览 `本体单元 4 / 待确认提案 1` |
| 5.4 全量回归 | 1385 passed / 60 skipped / 1 failed（既有泄漏门，§3.1）；新增 62 测试覆盖 §0.3/0.4/0.5 存储层 |
| 5.5 第二域演练 | `finance-demo`（金融演示域）：`/d` 列出 → 总览/本体/提案/评测四页均 200，各自空态正确（`尚无发布`、`提案箱是空的`、`本域还没有归属任何评测资产`），**零代码改动** |
| 5.6 strict + 报告 | `openspec validate --strict` = valid；本文件 |

### §6 P1 评测资产按域归属

| 判据 | 证据 |
|---|---|
| 6.1 `/d/{key}/bench` | 按 `asset_kind` 分组 + 未归属池；孤儿标 `资产已不存在`（`.badge.bad`）+ `清理失效归属` |
| 6.2 assign / unassign | `POST .../bench/assign|unassign`，lead/admin；幂等；解除不动资产 |
| 6.3 资产清单适配器 | **落地方式比计划更好**：内核 `src/bench/domain_assets.py` 做到**域无关**，只持目录机制与 provider 注册表；法律包的六类资产 SQL 在 `packs/legal/asset_catalog.py`（`PROVIDERS`：`{relation, label_key}`），导入即注册。`tests/test_kernel_domain_free.py` 保持绿 —— 法律词汇（`contract_type` 等）零出现在 `src/bench/` |
| 6.4 回填脚本 | `scripts/backfill_domain_assets.py`：显式清单 JSON（拒绝 `*`/`all` 通配）、`--dry-run`、幂等。**实测三桶全中**：assign 1 / already 1 / missing 1；dry-run 与真跑计数一致（首版 dry-run 把孤儿错算「已登记」，已按内核判定顺序修正后复验） |
| 6.5 孤儿处理 | `list_for_domain` LEFT JOIN 打 `exists`；`purge_orphans` 只删目录行 |
| 6.6 判据测试 | 同一尺归属 A+B、解除 A 后 B 仍在；回填两次只一行；`test_domain_assets_is_not_imported_anywhere_in_the_eval_path` 断言归属不进评测路径 |

## 2. 视觉门（impeccable）

每页两轮封顶：第 1 轮修可见缺陷，第 2 轮确认即停。**真机走查抓到 9 个单测看不见的缺陷，全部修复**：

| # | 缺陷 | 修法 |
|---|---|---|
| 1 | `/d` 整页 500（`last_opened_at.strftime`） | 内核行解码统一 ISO TEXT，模板改切片；单测看不见因为种子值是 NULL |
| 2 | 最近变更时间空白 | 模板取错列（`happened_at` → `created_at`） |
| 3 | 桌面顶栏「切换域」一字一行 | `.domain-context` `flex:0 0 auto` + nowrap；`select` 限宽 12rem |
| 4 | 移动端文档级横向溢出（480px 内容 / 390 视口） | ≤720px：域上下文与切换器各占整行、select 100% 宽 |
| 5 | 移动端「前往」按钮竖排 | `.domain-switch` 内 select 可缩、按钮 nowrap |
| 6 | 面包屑与六区导航贴到视口左缘 | 新增 `.zone-shell` 980px 容器 |
| 7 | 角色徽章误用 harbor 紫 | 改中性灰底（harbor 只给平台管理员） |
| 8 | 出表/过期/吊销判词用 harbor | 新增 `.badge.bad`（fail 色调） |
| 9 | 发布页 changelog 是裸 JSON、时间戳是 ISO 原文、`版本` 竖排 | changelog 走 i18n 词句；时间戳切片；`<th class="nowrap">` |

最终实测：7 页 × 1280/390，`scrollWidth == 视口宽`（零横向溢出）；宽表在面板内横向滚动；表头不再一字一行。

## 3. 未清项（如实登记）

**3.1 `tests/test_public_hygiene.py::test_repo_is_clean_at_head` 红 —— 既有，非本次引入。**
`deploy/law-bench-public-replica.yaml:12` 在 **HEAD** 已有明文
`POSTGRES_PASSWORD: "lbpub-repl-…"`（由 commit `24316ca` 引入，本 change 未触碰该文件）。
修它要**轮换一个在跑的凭据**，属对外可见的运维决定，故**只报不动**。

**3.2 移动端宽表只能在面板内横向滚动，没有滚动提示。**
`最近变更`、`提案箱`、`版本历史` 在 390 视口下溢出部分需横滑，面板无阴影/渐隐提示。
按两轮封顶规则停止改进；390px 下表格完整可读，只是要先知道能滑。

**3.3 P2（§7）未做。** 舰队提案目标从柏讯审批队列切到域提案箱，按提案边界属 `fd-wire`/`paas` 根的
伴随 change；本仓已提供提交面与幂等契约（契约文档化在 `proposals.submit` docstring，§7.1 待另立 change 时补正式文档）。

**3.4 遗留死模板。** `src/web/templates/workbench_home.html` 已无路由引用（`/workbench/{key}` 改 302 后），
未删以免与并发会话冲突；建议下一轮清理。

**3.5 URL 形状不统一。** 控制台是 `/d/{key}/...`，而创作深链仍是 `/workbench/{key}/authoring/...`。
为避免破坏既有外链与书签，本轮只做 302 归口，未统一前缀。

**3.6 演示域词表与域语义不符。** `finance-demo`（金融演示域）锚定 `legal-domain-template v1`，
词表是 `company/indicator/belongs_to`。这是 C1 期种子数据，本轮用作第二域演练恰好证明「零代码改动可用」，
但一个金融域挂法律模板在演示里会让人困惑 —— 属种子数据问题，非门面缺陷。

## 4. 关键设计决定（供归档/复盘）

1. **一个域一个家**：`/workbench/{key}` 永久 302 → `/d/{key}`，创作深链保留。`TestClient` 跟随跳转使既有正向断言无需改写。
2. **台账的策展层就是操作面**：旧工作台首页是创作入口，控制台若只读就会丢掉它。解法是策展层每行带
   `浏览` / `新建`，出表 kind 与非写手不给 `新建` —— 入口跟着账走，不再单开一张「快捷操作」卡。
3. **域无关内核 + 包侧 provider 注册表**：法律词汇（`contract_type`/`clause`/`law_info`）一度写进
   `src/bench/domain_assets.py`，被 `test_kernel_domain_free` 拦下 —— 这是真的分层违规，不是测试碍事。
   改为内核只持目录机制，包用 `{relation, label_key}` 声明六类资产。
4. **审计留痕必须准确**：`[admin-override]` 只在豁免真实发生（管理员确认自己提的）时写入。
5. **digest 只有一个来源**：台账不重算，读 `ontology_publications.digest`；测试同时断言页面与拉取面同值。
