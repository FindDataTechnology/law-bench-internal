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
| 1 | `ontology_templates` 多 `external-world` 一个名字；既有 6 名版本数与 schema 字节不变 | 待填 |
| 2a | `knowledge_units where namespace='erp' and kind='organization'` = 8 | 待填 |
| 2b | 8 条 crosswalk 幂等命中；`crosswalk_gaps(erp).dangling` = 0、`stale` = 8 | 待填 |
| 2c | `kind='crosswalk' and attrs->>'relation'='maps_to'` = 23 | 待填 |
| 3a | `rubrics where domain_id=<erp>` = 1，criteria = 8 | 待填 |
| 3b | `enterprise-base` 多 v3，`rubric_refs` 非空，v2 行不变 | 待填 |
| 3c | `domains` erp 的 `template_version` = 3 | 待填 |
| 4a | `domains` 多 `finance` 一行，控制台标「草稿」 | 待填 |
| 4b | `rubrics where domain_id=<finance>` = 1，criteria = 8 | 待填 |
| 4c | `finance-market` 多 v3；finance 锚 v3 | 待填 |
| 4d | `knowledge_units where namespace='finance' and kind='fact' and tier='gold'` = 105 | 待填 |
| 5a | `ontology_publications` 多两行，digest 非空 | 待填 |
| 5b | `GET /api/public/overview` 的 `totals.domains` = 4，两新域 counts 与库内一致 | 待填 |
| 5c | 24h 后 `distribution_pull_events` 里 `domain_key='erp'` 行数 | 待填（0 则如实记「已发布、消费方未接」） |

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
- `domain_assets` 表 0 行（C5 的 P1 归属表建了从未回填）：不在本变更范围。
