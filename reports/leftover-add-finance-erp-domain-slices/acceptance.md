# Acceptance — add-finance-erp-domain-slices

> 逐条判据 + 证据。基线见 `tasks.md` 抬头（2026-11-21 生产只读实测）。
> **本机不跑执行类验证**（用户 2026-11-18 明令）；本机只做 `py_compile`，
> 执行一律 GitHub Actions 与生产只读查询。

## 代码侧（可离线判定）

| # | 判据 | 状态 | 证据 |
|---|---|---|---|
| 1.1 | 本端存在判据是纯函数，两处共用 | ✅ | `src/bench/crosswalk.py::endpoint_problem`；调用点 `proposals._check_crosswalk_proposal`、`authoring.authoring_create_crosswalk` |
| 1.2 | 直写路径拒绝悬空本端、点名键与两条路径 | ✅ | `authoring_create_crosswalk` 写前调判据；`tests/test_crosswalk_endpoint_rule.py::test_direct_write_refuses_a_dangling_near_end` |
| 1.3 | `dangling` 与 `stale`/`unconfirmed` 分开计数，进矩阵、可派单 | ✅ | `quality.crosswalk_gaps` 三类；`estate.matrix` 追加三类缺口；`dispatch.GAP_ROUTE` + `GAP_TASKS` |
| 1.4 | 观测层模板导入生产 | ⏸ 待执行（写操作） | 脚本已存在且被 `tests/test_protocol_package_available.py` 覆盖；生产尚未跑 |
| 1.5 | 对齐声明从协议读、不硬编码 | ✅ | 既有 `tests/test_protocol_package_available.py::test_importer_reads_alignment_from_the_declaration_not_a_local_copy` |
| 2.1 | provider 实体种子脚本 | ✅ | `scripts/seed_erp_provider_entities.py`；实测 `plans()` 得 8 个系统（wechatpay 双行业合并） |
| 2.3 | 科目映射导入脚本 + 目标闭集校验 | ✅ | `scripts/import_account_mapping_crosswalks.py`；实测 23 条、3 行业 8/7/8、目标全部落在 12 码预设内 |
| 2.4 | 三行业前缀不互撞、幂等、越界拒绝 | ✅ | `tests/test_import_account_mapping_crosswalks.py`（5 项） |
| 3.1 | ERP 尺子 8 条判据 | ✅ | `scripts/seed_erp_rubric.py` |
| 4.2 | 金融尺子 8 条判据，前 7 条对齐 7 个 checker | ✅ | `scripts/seed_finance_rubric.py`；实测 `checkers_for('fact')` 7 个名字与判据一一对应 |
| 4.4/4.5 | gold-v9 落域 namespace、失败硬报 | ✅ | `scripts/seed_finance_gold.py` + `tests/test_seed_finance_gold.py`（缺仓/坏文件两种拒绝 + tier 保持 gold） |
| 5.1 | 发布脚本带 dry-run 与读回复核 | ✅ | `scripts/publish_domain_snapshot.py` |

## 数据侧（须在生产执行，本轮未做）

以下都是**写操作**，本机不执行。顺序不可颠倒（见 `design.md` D3）：

```bash
# 1 横梁
uv run python scripts/import_protocol_ontology.py --dry-run
uv run python scripts/import_protocol_ontology.py

# 2 ERP：补实体 → 重跑连接器映射 → 科目映射
uv run python scripts/seed_erp_provider_entities.py --dry-run
uv run python scripts/seed_erp_provider_entities.py
uv run python scripts/import_connector_crosswalks.py --domain erp --force
uv run python scripts/import_account_mapping_crosswalks.py --dry-run
uv run python scripts/import_account_mapping_crosswalks.py

# 3 ERP：尺子 → 升版 → 重锚
uv run python scripts/seed_erp_rubric.py --dry-run
uv run python scripts/seed_erp_rubric.py
uv run python scripts/promote_industry_template.py --template enterprise-base \
    --domain erp --rubric erp-ontology-consistency --reanchor

# 4 金融：开域 → 尺子 → 升版 → 重锚 → 金标
uv run python scripts/register_finance_domain.py
uv run python scripts/seed_finance_rubric.py
uv run python scripts/promote_industry_template.py --template finance-market \
    --domain finance --rubric finance-fact-quality --reanchor
uv run python scripts/seed_finance_gold.py

# 5 发布
uv run python scripts/publish_domain_snapshot.py --domain erp --domain finance
```

每一步的判据（执行后逐条填）：

| 步 | 判据 | 结果 |
|---|---|---|
| 1 | ✅ 模板名 6→7、版本 13→14；`external-world` v1 单独一行；既有 6 名版本数一字未变（legal3/gov3/data-ontology2/foundation1/enterprise-base2/finance-market2） | 2026-11-21 实跑 |
| 2a | ✅ erp 域 organization = 8（8/8 provider 齐） | +8 new / 0 existing |
| 2b | ✅ 8 条全部幂等命中、零 SKIP；dangling 8→**0**、stale 8、unconfirmed 8 | 修好本端后悬空清零，接通状态不变（如设计所期） |
| 2c | ✅ account 实体 23（跨境 8/餐饮 7/供应链 8）+ maps_to 23；crosswalk 总数 31 | 目标全部落在内核 12 码预设内，越界 0 |
| 3a | ✅ rubric id=90 `erp-ontology-consistency`，8 条判据，该域可见 | |
| 3b | ✅ enterprise-base v3 (id=15) `rubric_refs=['erp-ontology-consistency']`；v1(id=10)/v2(id=12) 原样 | 首次升版记立基线 |
| 3c | ✅ erp v2→v3；rollback 串 `template_id=12, template_version=2` | |
| 4a | ✅ 域 `finance` (id=6) 锚 finance-market v2 | 草稿态在 4b 后转正式 |
| 4b | ✅ rubric id=91 `finance-fact-quality`，8 条判据（前 7 条对齐 packs/finance-data 的 7 个 checker） | |
| 4c | ✅ finance-market v3 (id=16)；finance v2→v3；rollback `template_id=13, template_version=2` | |
| 4d | ✅ 105 条 `fact`/`gold` 落 finance namespace；落数 == 读入数（脚本内置不一致即失败） | `FD_SENTIMENT_REPO=/Users/chengsishi/finddata/fd-sentiment` |
| 5a | ✅ **erp 本体** v1 `f1e3771d`（31 实体/0 关系）。finance 不走本体发布——见下方「执行中修正」 | |
| 5b | ⚠️ `totals.domains` 2→**3**（legal/gov/erp）。finance 只发布了资产不发布本体，故不在概览——这是对的，不是漏 | 公开副本由 `law-bench-public-sync` CronJob 每 15 分钟灌一次；需等一轮 |
| 5c | ⏸ 当前 0 次（`erp-connector` 已登记、已激活）。**如实记「已发布、消费方未接」**——它的调度在外部，不因我们发版自动拉 | 24h 后复查，>0 才改记「已接通」 |

## 执行中修正：finance 的金标不走本体发布

按 `tasks.md` 4.4 把 105 条 gold 落进 finance namespace 后，
`publish_domain_snapshot --domain finance` 被拒：**"domain 'finance' has no
content to publish"**。

查因：`build_manifest` 只取锚定模板 `entity_types` 词表内的 kind，而 `fact`
不在 `finance-market` 的 12 个类型里。台账自己报了这件事——
`ledger.reconcile(finance)` 返回 `out_of_vocab_kinds => ['fact']`、
`consistent => False`。

**判断：不要把 `fact` 加进模板词表。** gold 是「对某条公告的人工标注断言」，
不是业务本体里的实体；加进 `entity_types` 会让另外 12 个真实类型全被台账报成
`unused`，并且对外说「这个域像理解 instrument 那样理解金标」。

**改走 `add-typed-publications` 已建的机制**：
- `packs/finance-data/asset_catalog.py`（新）登记 `fact` 的 shelf provider 与
  publication provider；
- `scripts/publish_domain_assets.py`（新）上架 + 按种类发布；
- 实测结果：`finance/fact` **v1 digest `5edc37f7`**，105 条上架并冻结；
  `asset_publications` 里多一行，`domain_assets` 从 0 行变成 105 行。

这也顺带解释了为什么公开概览只多一个域：**概览只列本体发布**，finance 没有
本体发布（它的内容是事实资产），所以 `totals.domains` 是 3 而不是 4。这不是
漏，是两类资产的区别。

## 本轮实现中发现的既有缺陷（不在原计划内）

**`quality:crosswalk_stale` 与 `quality:crosswalk_unconfirmed` 从未被任何人产出。**
`dispatch.GAP_ROUTE` 与 `GAP_TASKS` 都声明了它们，`crosswalk_gaps` 也算得出来，
但 `estate.gaps_for` 只追加 `quality:crosswalk`（覆盖率那一条）——所以这两个缺口
在派单页上永远不出现，三态证据纪律从页面这一侧根本够不着。

已在 `estate.matrix` 补上三类映射缺口的产出（`crosswalk_gaps` 每行只算一次）。
这条不是本变更的目标，但不修的话我新加的 `dangling` 也会同样不可见。

## 已知边界（如实登记）

- `instrument ↔ stock/fund/bond/index` 的一对多对齐**未声明**：`aligned_with` 的
  `type_map` 是 str→str，一对多表达不出来。见 `design.md` D4。
- `data-ontology` 域（7 条 pending、锚 v1 而模板已 v2）**未动**：疑似另一条线的在建工作。
- `domain_assets` 表**已从 0 行变成 105 行**（finance 的 fact 上架）；法律线的六个
  kind 仍未回填，那不在本变更范围。
- finance 域的 `quality:evidence` 缺口**保留红、不洗绿**：gold 单元带的是指纹锚点
  （`text_sha256` + `doc_id`），不是逐字引用；原文留在 fd-sentiment 的下载谱系里，
  本平台看不到。这正是 `evidence()` 那条「有 attrs 不等于有依据」判据的真实命中。
- erp 域的 `quality:crosswalk_unconfirmed` = 31、`stale` = 8 同样保留红：ERP 的
  科目映射 pack 记录的是「对齐」，不是「谁看过」，硬填 confidence 就是在伪造复核。

## 5.3 消费侧分段判据（2026-11-21 23:40 实查）

按任务要求「MUST NOT 因发布成功就写『已接通』」，直接查生产库：

```sql
select domain_key, count(*), min(happened_at)::date, max(happened_at)::date
  from distribution_pull_events group by 1;
```

结果：
```
legal | 55 | 2026-11-11 | 2026-11-21
erp   |  0 |      -     |      -
```

**结论：erp 已发布，但消费方未接（`domain_key='erp'` 0 行）。**

对照：`legal` 域 55 行、跨 11 天，说明这套拉起事件的机制本身是工作的——
不是表没通，是这个域还没有消费方来拉。按任务判据这属于「=0 如实记
『已发布、消费方未接』」，**不记「已接通」**。

（发布成功 ≠ 有人消费。这条判据存在的意义就是防这个混同。）
