## Why

知验台的金融与 ERP 两条线**资产都在，但没有一条被域合约收编**。生产库实测（2026-11-21，只读）：

| 域 | 锚定模板 | 知识单元 | 尺子 | 已发布 | 消费者拉取 |
|---|---|---|---|---|---|
| `legal` | legal-domain v2 | 5,144 | 88 | v2 `5897354d` | fd-wire 31 次 |
| `gov` | gov-domain v2 | 41 | 1 | v1 `172cb045` | — |
| `erp` | enterprise-base v2 | **8（全是 crosswalk）** | **0** | **无** | erp-connector 已登记、**0 次** |
| —（金融） | finance-market v2 在库 | — | **0** | — | — |

三件事让「有资产」不等于「能交付」：

1. **`erp` 域是个空壳**。它的 8 条 crosswalk 全是 `organization:<provider> --same_as--> <provider>`，而 `organization:kingdee` 这些**本端实体在域内一条都不存在**（实测 8/8 悬空）。它们由 `import_connector_crosswalks.py` 经 `authoring_create_crosswalk` 直写，而那条写路径**不做本端存在校验**——同一条规则，提案路径（`_check_crosswalk_proposal` → `crosswalk_endpoint_missing`）守，直写路径不守。后果不是数据损坏，是**误归因**：质量视图把这 8 条报成「外部系统未接通」，而真实原因是「本端实体不存在」，值班的人会去重验对接，方向完全错。
2. **两个行业模板都不可评**。`enterprise-base` v1/v2 与 `finance-market` v1/v2 的 `rubric_refs` 全为空 ⇒ 按 `template-readiness-gate`，实例化出来的是**草稿域**，永远报 `quality:template` 缺口，**永远无法过 `no-worse` 升版门**（无可比历史就立基线，每次都立基线）。gov 走过这条路（`seed_gov_rubric.py` 建了 `gov-document-quality` 8 条机器可核对的判据），金融与 ERP 还没有走。
3. **层之间的横梁没接上**。`finance-market` 的 `instrument` 与观测层的 `stock/fund/bond/index` 是同一个所指的不同生命周期，观测层的 `company` 与 `foundation` 的 `organization` 同理；但生产里**连 `external-world` 模板都不存在**（`import_protocol_ontology.py` 从未在生产跑过），`aligned_with` 在生产模板里零条。

为什么现在做：`erp-connector` 这个消费者**已经登记在 erp 域上**，却因为该域从未发布过任何版本而拉取足迹为零。这是现成的验收钩子——发布一版，足迹就该出现；不出现就是没接通。再拖，先接上的消费方会先长出一套自己的口径。

## What Changes

**裁决：两个独立根域，不复用域树父子关系。** 域树的父子继承是**只读**的（`domain-workspace`：父域成员可读、不可写），解决不了「金融域要写自己的 `instrument`、又要复用 ERP 域的 `organization` 与科目」这件事；跨域复用应发生在 crosswalk 层（`instrument --maps_to--> account`），不是域层级。方案 A 不需要任何内核改动（B/C 的否决理由见 design）。

- **横梁（两个域共用的前置）**：把观测层模板导入生产（脚本已存在且被 `import_protocol_ontology` 链路测试覆盖），使 `aligned_with` 有可指向的对端层。`aligned_with` 的 `type_map` 是**一对一**字符串映射，而 `instrument` 对应 `stock`/`fund`/`bond`/`index` 四个观测类型——**这条一对多今天表达不出来**，本变更如实把它记为已知边界（design §边界），不用拼接或择优的方式伪造对齐。
- **ERP 竖切片**：先给 erp 域放真实体（8 个 provider 各自对应一条 `organization`，带三态证据来源），再导入 23 条科目映射 crosswalk（3 个行业 pack：跨境电商 8 / 餐饮连锁 7 / 供应链 8，实测**全部映射进内核 12 码通用科目预设，越界 0**；行业码前缀 `X-`/`R-`/`SC-` 互不冲突），最后修 `authoring_create_crosswalk` 的本端校验，使直写路径与提案路径用同一条规则。
- **金融竖切片**：从 `finance-market` v2 实例化金融域；把 `packs/finance-data` 已有的 gold-v9 105 条人标金标落进该域 namespace（`kind='fact'`、`tier='gold'`，只读适配器已存在、幂等）；用该包的 7 个确定性 checker 建一条数据通道尺子，把模板推到 v3 并声明 `rubric_refs`，域重新锚定 v3。
- **两域各自发布 v1**，验收判据与 legal/gov 同一套门：四层非空、尺子解析率 100%、有已发布版本、消费者有拉取足迹。
- **新增一类缺口**：crosswalk 的本端实体不存在时，报 `quality:crosswalk_dangling`，MUST NOT 折进「未接通」或「未复核」。

## Capabilities

### New Capabilities

（无。本变更主要**使用**既有能力：`domain-workspace` 实例化、`crosswalk-seam` 映射、`template-readiness-gate` 尺子解析、`domain-quality-metrics` 质量比、`knowledge-distribution` 发布。不新造能力，也不为凑齐校验而编需求。）

### Modified Capabilities

- `crosswalk-seam`：把「本端端点必须是本域活单位或待确认提案」从**提案路径**提升为**写路径的共同判据**。今天这条规则只在一个入口执行，另一个入口（`authoring_create_crosswalk` 直写）能造出悬空映射；两入口分歧不是配置差异，是同一份规则的两份实现。
- `domain-quality-metrics`：新增「悬空映射」为独立缺口 `quality:crosswalk_dangling`——本端实体不存在的 crosswalk 与该外部系统「未接通」是两件事（前者是本域少了一条实体，后者是对外系统没验过），合并计数会让值班的人修错方向。

## Impact

**代码（law-bench-internal）**

- `src/bench/crosswalk.py`：导出本端存在判据（从 `src/bench/proposals.py::_check_crosswalk_proposal` 抽出，两处共用同一实现）。
- `src/bench/authoring.py`：`authoring_create_crosswalk` 增加本端校验（与提案路径同判据、同报错词汇）。
- `src/bench/quality.py`：`crosswalk_gaps` 增 `dangling` 一类；`mapped`/`entities` 的交集逻辑不变。
- `src/bench/dispatch.py`：`quality:crosswalk_dangling` 路由。

**数据操作（脚本，全部幂等 + `--dry-run`）**

- `scripts/import_protocol_ontology.py`（已存在）：生产首次导入观测层模板。
- 新增 `scripts/seed_finance_rubric.py`、`scripts/seed_erp_rubric.py`：沿 `seed_gov_rubric.py` 先例，判据取自两个域包里**已经在跑的**确定性 checker，不新写标准。
- 新增 `scripts/seed_erp_provider_entities.py`：8 个 provider 本端实体（依据 `connector-status.json`，不造数）。
- 新增 `scripts/import_account_mapping_crosswalks.py`：23 条 `maps_to`（依据 3 个 `account-mapping/pack.json`，只读）。
- `scripts/import_connector_crosswalks.py`（已存在）：修好本端校验后重跑，幂等命中。

**跨仓（只读）**

- `fd-erp-vertical-templates`：`connector-status.json` + 3 份 `account-mapping/pack.json` 是来源；本变更**不改那两个仓**。
- `packs/finance-data`：`adapters.py` / `checks.py` 是来源，零改动。

**明确不做**

- 不灌 `semantic_observations` 的 144M 行、不灌 `daas.db` 的 59 万报告章节与 1,573 份年报。它们是语料/观测，不是本体；灌进去计数好看而质量比全空——正是 `domain-quality-metrics` 点名的失败模式。
- 不接 `fd-quant` 的 50 工具面、不接 `fd-cn-report`、不接 47 张 dashboard spec。
- 不动 `data-ontology` 域（7 条待确认提案，疑似另一条在建工作）与 `archive-probe`（演练残留）。
- 不做域树重构、不做 B/C 两种建模（design §否决理由）、不改 `ontology_publications` 与 manifest 形状。
- 不给 `instrument ↔ stock/fund/bond/index` 造对齐——一对多今天表达不出来，见 design §已知边界。
