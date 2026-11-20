# Design · console-progress-and-value

## Context

见 proposal「Why」。实现相关的现状（2026-11-20 实测，非推断）：

- `estate.matrix()` **已经在算**质量比（`with_quality=True` 是默认值），每行结果挂在 `r["quality"]`，八项：`grounding / evidence / referential / key_hygiene / judge / crosswalk / template / review_lag`。`domain_list.html` 从来没读过它。
- `gaps_for()` 会产出 `quality:*` 系列缺口名，模板却用 `t.console.estate['gap_' + g]` 查表，i18n 里只有 `gap_ontology / gap_knowledge / gap_eval` 三个键——其余渲染成无字徽标。
- `badge-warn` / `badge-quiet` 两个 class 在 16 处模板里被引用，但 `style.css` 里**没有定义**，它们退化成 `.badge` 默认灰。
- `/promotion/queue` 存在且完整，但返回 JSON、**全树零链接**。升格阶梯是产品叙事的核心，后台却不可达。
- `/dashboard` 只被知识库页角落链过一次。

## Goals / Non-Goals

Goals：让「这个域现在值多少分」在一页内可读；质量缺口与柱为空可辨；升格阶梯可达；控制台能回门面。

Non-Goals：不改质量比算法、不改权限模型、不新增写面、不动 `add-domain-next-actions` 要新建的 `next_actions.py`。

## Decisions

**D1 · 质量比渲染已算好的结果，不重算。**
`estate.matrix()` 的输出里已经有 `r["quality"]`，模板直接遍历它。`console.py` 只额外传 `thresholds` 与 `high_is_better` 两张静态表供模板判「低于阈值」的方向与门槛——它们不是计算，是查询参数。
理由：任何在模板层做的除法都会成为第二处口径。proposal 里担心的「/d 变慢」不成立：`all_metrics` 本来就在跑。

**D2 · 三态必须可辨：达标 / 低于阈值 / 无物可算。**
无物可算显示 `—`，不显示 `0` 或 `100%`。这与 `domain-quality-metrics` spec 既有要求一致，此前只是没在运营台执行。

**D3 · `review_lag` 特殊显示：单位是小时，不是比率。**
`review_lag.value` 是平均小时数（`round(avg_h, 2)`）。用统一的 `%.2f` 会把它显示成 `1.50`，被读成 150%。模板对它单独分支，带 `h` 后缀。

**D4 · 缺口徽标按类型分色，缺键时不静默。**
`quality:*` 用 `badge-quiet`（无底 + 边），柱为空用 `badge-warn`（琥珀）。标签查不到时退到「质量不达标 (quality:xxx)」，把原始键名带出来——空徽标是这次要修的东西，不能用一个 fallback 把它重新造出来。

**D5 · 升格队列是新建页面，不是「挂个链接」。**
`/promotion/queue` 返回 JSON，没有模板。新建 `domain_console_promotion.html` + `GET /d/{key}/promotion`，注册进 `AREAS` 与区导航。升格动作仍是既有 POST，本页纯读。

**D6 · 升格页只列 `PROMOTABLE_KINDS`。**
实测发现内核 `promotion_queue` 的分页查询**不按 kind 过滤**，而 `counts` 只统计 `entity`/`relation`——于是 `crosswalk` 之类的单位会出现在兕表里、却永远爬不上阶梯（实测：2 行 crosswalk，`total=0`，页面显示「本页显示 2 / 0」自相矛盾）。
本 change 在路由层筛掉非可升格 kind，**不改内核**（内核行为属另一口径，改它要有自己的依据）。同时不显示自相矛盾的 `len/total`，只显示实际条数。

**D7 · 回门面链接放顶栏品牌旁，样式更轻。**
`bench.finddatatech.cloud` 是公开面，运营台是登录后的面。回链不抢「域优先」主线，用小字号 muted。

## Risks / Trade-offs

- [八项 × N 域把表格撑爆] → CSS 给质量列 `max-width` + 小字号标签；柱子列 `nowrap` 防折行。
- [内核 `promotion_queue` 的 total/units 不一致是既存缺陷] → 本 change 只在下游筛选，并在代码注释里写明「内核行为另有 change 管」，不偷偷改内核口径。
- [新增 AREAS 项会让所有域多一个导航项] → 它是 pure read、annotator 可见，与其余区同级；不通过 `min_role` 提门槛以免普通人看不到自己域的阶梯。

## Migration Plan

无数据迁移。上线即生效。回滚：撤掉模板与路由注册（`AREAS` 少一项，导航自动消失）。

## Open Questions

- `/dashboard` 的收编方式（并入 eval-runs 还是独立入口）本轮未定——它内容与「评测运行」区重叠，但口径不同（dashboard 走 `pipeline_runs`，eval-runs 走域资产）。留到下一轮，等 `add-domain-next-actions` 落地后一起看。
