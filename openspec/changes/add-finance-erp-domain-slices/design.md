# Design — 金融与 ERP 两个竖切片

> 动机见 `proposal.md`。本文件只记技术裁决、边界与风险。

## Context

生产实测（2026-11-21，只读，`kubectl --context cheap -n postgres exec postgres-0`）：

```
domains                     anchor                         KU      尺子   发布        消费者
legal                       legal-domain v2               5,144    88     v2 5897354d  fd-wire 31 次
gov                         gov-domain v2                    41     1     v1 172cb045  —
erp                         enterprise-base v2                8     0     —            erp-connector 0 次
data-ontology               data-ontology v1                  0     0     —            —
archive-probe               legal-domain v2                   1     0     —            — (演练残留)

ontology_templates: legal-domain v1..v3 / gov-domain v1..v3 / data-ontology v1..v2
                    foundation-v1 v1 / enterprise-base v1..v2 / finance-market v1..v2
                    —— 无 external-world（观测层从未导入生产）
aligned_with:       生产模板里零条
domain_assets:      0 行（C5 的 P1 归属表建了但从未回填）
```

`erp` 域那 8 条 crosswalk 全部悬空（本端 `organization:<provider>` 不存在），来源是 `scripts/import_connector_crosswalks.py` 直写。

## Goals / Non-Goals

**Goals**

- 两个域各自达到与 `legal` / `gov` 同一套交付门：四层非空、尺子解析率 100%、有已发布版本、消费者有拉取足迹。
- 让「悬空映射」这一缺陷在写入口就被拒绝，而不是等读面解释。
- 让横梁（`aligned_with`）在生产里真实存在至少一处，后续金融/观测对齐有落点。

**Non-Goals（设计级边界，扩自 proposal 的明确不做）**

- 不引入域树父子结构（否决理由见 D1）。
- 不改 `ontology_publications` / `publish_domain` / manifest 形状（wire 生产在拉 shape 2）。
- 不引入新的模板块类型、不改 `concept_structures` 的浅合并语义。
- 不做观测数据（144M 行）或报告语料（59 万章节）入域——那是语料/观测，不是本体。
- 不给 `instrument ↔ stock/fund/bond/index` 造对齐声明（见 D4 与已知边界）。

## Decisions

### D1 · 两个独立根域，不用域树父子

**否决 B（`erp/finance-market` 子域）与 C（`enterprise/{erp,finance}`）。**

域树的父子继承是**只读**的（`domain-workspace`：父域成员可读、不可写；子域成员看不到父域）。金融域的日常动作是**写**自己的 `instrument` / `quote` / `indicator`，同时希望复用 ERP 域的 `organization` 与科目——只读继承解决不了这个，反而制造一个错觉：看起来继承到了，一写就 403。

真正的复用发生在 crosswalk 层：`instrument --maps_to--> account` 是一条映射行，不是一次域继承。把它做成域层级会把「映射」这件事绑死在组织结构上，而映射的数量级（厂商数）远大于域的数量级（行业数）——这正是 `crosswalk-seam` 那条「接一个新 ERP 厂商 = 一批 KU 行，不是一个新模板」的成本约束。

C 方案额外代价：多一层域 → 多一次实例化 → 又一次空模板 + 空尺子的问题。

**独立的代价**：金融域看不到 ERP 域的知识单元。接受——跨域可见性若真有需求，应作为显式的共享机制设计（`shared-corpus-library` 已有先例），而不是靠域树隐式继承。

### D2 · 悬空校验下沉到写入口，两个入口共用一份实现

现状是两条写路径、一条守一条不守：

```
提案路径  proposals.submit → _check_crosswalk_proposal → crosswalk_endpoint_missing   ← 守
直写路径  scripts/* → authoring.authoring_create_crosswalk → _create_unit               ← 不守
```

**做法**：把「本端存在」判据抽成 `crosswalk.endpoint_problem(...)` 或等价纯函数，由 `authoring_create_crosswalk` 与 `_check_crosswalk_proposal` 共同调用。

**为什么不让直写路径直接走提案路径**：直写路径的存在有正当理由——导入脚本产出的是**已核对的证据**（ERP 的连接器状态是仓内派生物、行业科目映射是已发布的 pack 资产），把它们塞进提案箱要求人工逐条确认，是给没有判断余量的事加一道假门。真正缺的不是「人看过没有」，是「本端存不存在」——那是确定性的，两个入口都该拒。

**判据的输入**：本端存在 = 活单位 ∪ 本域待确认提案。与提案路径现有的 `known = live | pending` 同源，不新增查询口径。

**一处必须小心**：`create_crosswalk` 的调用方里既有「建实体后再建映射」的顺序，也有「映射先于实体」的合法场景（提案箱内两端同时在评审）。判据允许 pending 正是为此；**不允许**的是两端都没有。

### D3 · 尺子从域包里已在跑的确定性 checker 取，不新写标准

`packs/finance-data/checks.py` 有 7 个 checker（`band-vocabulary` / `band-direction-consistency` / `text-fingerprint-sha256` / `text-chars-positive` / `doc-id-identity` / `as-of-iso-date` / `amount-anchor-parseable`），每个都有出处与契约语义。`packs/gov/checks.py` 同理（gov 线已用 `seed_gov_rubric.py` 建出 `gov-document-quality` 8 条）。

金融域的尺子直接把这批 checker 的判据写成 rubric criteria；ERP 域的尺子取自 `fd-erp-vertical-templates` 的边界四条（零旁路账本 / 零直连库表 / 仅经白名单车道回写 / 对外部系统零写入）与 `fd-erp-ledger-mcp` 的科目预设不变量。

**不在模板里硬编码这些判据**：模板只声明 `rubric_refs`（名字清单），判据文本住在 rubric 表。模板拿 `no-worse` 门做升版裁决，判据的实现归域包——这是 `bench-platform` 那条「内核领域无关、新增域不改内核」的直接应用。

**升版顺序必须是**：建 rubric → 模板升版并声明 `rubric_refs` → 域重新锚定。反过来的话，`instantiate_domain` 会在「声明了尺子但解析不到」处拒绝——那是对的（`template-readiness-gate` 明文），但会让人误以为要放宽校验。

**「草稿域」不新增列**：`template-readiness-gate` 已裁定它必须由模板声明计算得出，手工位会分叉。本设计不碰这条，只在读面消费同一结论。

### D4 · 横梁先只接能做对的那一条

观测层 `aligned_with` 是 `{from: to}` 的**一对一字符串映射**（`load_alignment` 的返回形状、`templates.validate_layer_declarations` 的校验都只接受 str→str）。而 `finance-market` 新增的 `instrument` 对应观测层**四个**类型（`stock` / `fund` / `bond` / `index`）。

四种做法，选第四：

| 做法 | 问题 |
|---|---|
| `instrument → stock` | 谎报：基金/债券被说成股票 |
| 新增四条 `aligned_with` 条目、同一 `from` | 校验不过（`type_map` 是 dict，同键被后者覆盖，静默丢三条） |
| 把 `instrument` 拆成四个 industry 类型 | 违反已裁的「模板数 = 行业数，映射数 = 厂商数」；且 `enterprise-base` 的 `item` 会与它们重复 |
| **如实记录为已知边界，本变更不声明这条** | 需要一对多对齐能力，那是 `ontology-template-layering` 的一次升版 |

因此本变更的横梁只做**观测层 ↔ foundation** 那一条（`company → organization`、`city → place` 等 8 条已在 `fd-open-data-protocol` 的 `vocabulary/alignment/foundation.yaml` 里声明），它是一对一的、上游已发布的、且导入脚本已经在消费它（`import_protocol_ontology.py::_aligned_with` 从声明读，不硬编码）。

`finance-market` 与观测层的对齐留作 Open Question，不在本变更的 spec 里承诺。

### D5 · 科目映射按行业前缀分段，且目标必须在通用科目闭集内

三个行业 pack 的行业码前缀互不冲突（`X-` / `R-` / `SC-`），实测 23 条全部映射进内核 12 码通用预设（`0002_universal_accounts.sql`：1000/1100/1200/1300/2000/2100/3000/3100/4000/5000/5100/5200），越界 0。

**导出键 = `<行业码>`**，不拼行业名：`external_key` 是语义键（`crosswalk-seam` 明文），而行业码本身就是行业内的语义标识，加前缀反而让同一份 pack 在两个域里产生两个键。

**导入时校验目标在闭集内**：`universal_accounts` 是内核表，知验台读不到它（跨仓）。所以校验的依据是 pack 文件里声明的 `maps_to` 与 `universal_preset_version`，取值集合硬编码在导入脚本里并**引出处**（`fd-erp-ledger-mcp/.../0002_universal_accounts.sql`）——48 行常量，比为一个一次性校验建立跨仓依赖便宜。`shortcut: 预设码表在脚本里是副本，内核换预设版本时要同步改；升级路径是内核暴露一个只读的预设清单面。`

## Risks / Trade-offs

- **`external-world` 首次导入生产会让模板数从 6 个名字变成 7 个**，若有统计按「模板数」计数会看到跳变。→ 导入前在 tasks 里登记基线数字，导入后核对 `+1 名字 / +1 版本`，不做比例型断言。
- **给 erp 域补 8 个 provider 实体会让 `crosswalk_coverage` 的分母从 0 变成 8**，覆盖率从 `None` 变成 `0/8`。这是从「没有可量的东西」到「量出来是 0」的**改善**，但读面上看起来像「变差了」。→ 验收里写明这个转变是预期的，并在域控制台的空态文案里保留「分母为 0 时报不可量」的原口径。
- **金融域用 `packs/finance-data` 的 gold-v9 会依赖兄弟仓 `fd-sentiment` 在磁盘上**。→ 适配器约定「找不到就抛错、不造假金标」；若目标机上没有该 checkout，域里就只有尺子没有 fact 单元，`ontology` 柱非空（模板词表在）、`knowledge` 柱空。**不因此 skip 验收**——但也不伪造数据。验收脚本要区分「载入 0 条」与「载入失败」。
- **两个域同时首发布会让 `ontology_publications` 多两行**，`bench-public-overview` 的 `totals.domains` 从 2 变 4。若草稿域不该进公开概览，需先落 `domain-quality-metrics` 那条新增需求（草稿域不计入）。→ 顺序安排成：先尺子、后发布，这样发布时两个域都已是正式域。
- **`erp-connector` 已登记但 0 次拉取**：发布后它不一定会自动拉（它是外部消费者，调度在它自己那边）。→ 验收判据拆成两级：域侧「有已发布版本」必达；消费者侧「有拉取足迹」作为**分段判据**，若 24h 内没有足迹则如实记为「已发布但消费方未接」，MUST NOT 因为发布成功就宣称已接通。

## Migration Plan

全部为**新增**与**幂等重跑**，无破坏性迁移、无表结构变更：

1. 导入观测层模板（新模板名，不触碰既有 6 个）。
2. 建两把 rubric（`domain_id` 指向各自域；gov 的先例是 `INSERT ... ON CONFLICT` 语义）。
3. 两个模板升版 + 声明 `rubric_refs`；域 `template_id/template_version` 重锚（`publish_gov_template_v2.py` 的同一手法，含 rollback 打印）。
4. 补 erp 的 8 个 provider 实体 → 重跑 `import_connector_crosswalks.py`（幂等命中，此前若因校验被拒则此次通过）。
5. 导入 23 条科目映射。
6. 金融域实例化 + 落 gold-v9。
7. 两域各发布 v1。

**回滚**：1–3 与 7 都是新增行；4/5 是 upsert 到既有键（若要撤，按 `external_key` 软删）。模板升版不删旧版，域重锚可改回旧 `template_id`。**不涉及任何 DELETE**。

## Open Questions

- `instrument` 与观测层 `stock/fund/bond/index` 的一对多对齐：需要 `aligned_with` 支持一对多（或引入显式的 `aligned_with` 多条目语义）。这是 `ontology-template-layering` 的一次升版，本变更不承诺，也不占位。
- `data-ontology` 域（7 条待确认提案、0 单元、锚 data-ontology v1 而模板已 v2）是谁的在建工作——本变更不动它，也不把它当先例。
