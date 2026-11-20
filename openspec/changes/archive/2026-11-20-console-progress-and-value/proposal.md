# Proposal · console-progress-and-value

> **状态：规划中，未开工。** 本 change 改动集中在 `src/web/i18n.py`、`src/web/routes/console.py`、
> `src/web/templates/domain_list.html` 等文件——这些文件当前有另一会话（`add-typed-publications`）
> 的未提交改动。**工作树干净之前不动手**。本文件先固定范围与判断，避免开工时重新讨论。

## Why

知验台的后台（`lawbench.finddatatech.cloud`）已经能算出「这个域现在值多少分」，但**没有一处把它显示出来**。四处具体缺口，每一条都是「数据已在、只是没摆到能看见的位置」：

1. **质量比算了不渲染。** `estate.matrix()` 每行都算出 `quality`（八项：接地率 / 证据率 / 参照完整 / 键卫生 / 判官健康 / 映射覆盖 / 模板可评 / 评审时滞），但 `domain_list.html` 里 `grep quality` 命中为 0——算出来直接丢掉。而 `gaps_for()` 会产出 `quality:evidence`、`quality:crosswalk`、`quality:template` 这类缺口名，模板却用 `t.console.estate['gap_' + g]` 去取 i18n，而 i18n 里只有 `gap_ontology` / `gap_knowledge` / `gap_eval` 三个键——**其余渲染成没有文字的空 badge**。
2. **升格阶梯零入口。** `promotion.CHAIN = (bronze, silver, gold)` 是整个产品「人的确认才让知识升档」的核心机制，`/promotion/queue` 路由存在、有完整实现，但**全树没有任何一个链接指向它**。落地页对外讲「gold/silver/bronze 质量分层」，后台却没有任何一处能操作它——这是叙事与实现之间最刺眼的一道缝。
3. **`/dashboard` 是孤儿但内容最像「价值」。** 它给出通过率、平均分、版本对比、最近 10 次运行；全树只有知识库页角落链接过一次。
4. **控制台没有回落地页的链接。** 落地页是公开门面，控制台是运营台，两者零互链——运营台的用户回不到门面，门面的访客（去掉首屏那个 change 之后）能进去但出不来。

另有一条**事实性错误**：`PRODUCT.md` 写「A solo operator … No external or team audience is targeted today」，而实现里已有 annotator / expert / lead 三级域角色、平台 admin、提案制人工确认、域隔离。产品文档与实现相反。

## What Changes

- **`/d` 页渲染质量比**：每行在四柱之后呈现质量比摘要（八项中至少标出低于阈值的项），空值如实显示「无物可算」而不是 0。
- **缺口徽标不再渲染空文字**：`quality:*` 类缺口 SHALL 有对应的可读标签（i18n 补齐），MUST NOT 渲染成空 badge。质量缺口与「柱为空」缺口 SHALL 在视觉上可区分。
- **升格队列有入口**：`/promotion/queue` SHALL 从本体区（或 `/d` 行内）可达；队列页 SHALL 显示每个 tier 的计数与可升格的单位。
- **`/dashboard` 收编或重做**：要么并入某个区的读面，要么作为「本域价值面」正式进入导航。MUST NOT 继续做孤儿页。
- **控制台 → 落地页回链**：`base.html` SHALL 提供一条回到 `bench.finddatatech.cloud` 的链接（运营台用户能回门面）。
- **`PRODUCT.md` 订正**：Users 段改为团队 + 舰队运营台的事实描述。

非目标：不做 `/d` 的性能重构（但见风险）；不新增写面；不改权限模型；不做视觉重设计——这一轮是「把已有的东西摆出来」，不是「做得更漂亮」。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `domain-estate-console`: 每行质量比摘要的呈现与质量缺口标签、`/dashboard` 与升格队列的入口可达性。
- `domain-quality-metrics`: 质量比在运营台的呈现口径（无物可算 ≠ 0；低于阈值须可见）。

> 开工前须复核：`add-domain-next-actions`（0/28，同仓）也在改 `domain-estate-console`，
> 它管「该做什么」、本 change 管「现在值多少分」。**两者须明确边界后再动手**，否则会在
> `domain_list.html` / `console.py` 上直接冲突。

## Impact

- **代码（law-bench-internal）**：`src/web/i18n.py`（补 `gap_quality_*` 标签）、
  `src/web/routes/console.py`（estate 传 quality、promotion 入口数据）、
  `src/web/templates/domain_list.html`（质量列 + 缺口标签 + 升格入口）、
  `src/web/templates/base.html`（回落地页链接）、`PRODUCT.md`。
- **性能**：`/d` 已知 warm 约 1465ms。estate 已经调用 `quality.all_metrics()`（每域一次），
  本 change 是**把已算的结果渲染出来**，不新增查询——但渲染八项 × N 域会放大响应体。
  若实测变慢，须在本 change 内决定是否抽成按需展开。
- **跨仓**：`fd-bench-web` 侧的门 A 入口由 `refresh-bench-landing` 提供，本 change 只补回链。
- **风险**：与 `add-domain-next-actions` 的边界若不清，两 change 会在同一模板上冲突；
  须先读其 design 再开工。
