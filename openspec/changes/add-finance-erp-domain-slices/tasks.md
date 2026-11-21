# Tasks: add-finance-erp-domain-slices

> 基线（2026-11-21 生产只读实测，验收时逐条复核）：模板名 6 个 / `external-world` 不存在 / `aligned_with` 零条 / erp 域 8 条 KU 全悬空 / `enterprise-base` 与 `finance-market` 的 `rubric_refs` 均空 / `domain_assets` 0 行 / `ontology_publications` 3 行（legal v1,v2 + gov v1）/ `totals.domains=2`。
> 依赖顺序：1 → 2 → 3 → 4 → 5 → 6。

## 1. 横梁：观测层模板导入 + 悬空校验下沉

- [x] 1.1 抽出本端存在判据为纯函数（`crosswalk.endpoint_problem(external_key, known)` 或等价），由 `proposals._check_crosswalk_proposal` 与 `authoring.authoring_create_crosswalk` 共同调用；验证：`uv run pytest tests/test_bench_crosswalk*.py tests/test_import_connector_crosswalks.py` 全绿，且新增用例断言「同一悬空键经两条路径拒绝、错误串一致」
- [x] 1.2 `authoring_create_crosswalk` 在写前执行该判据，拒绝时点名本端键与两条正当路径；验证：新用例直写悬空本端被拒且库中行数不变；本端为 pending 提案时放行
- [x] 1.3 `quality.crosswalk_gaps` 增 `dangling` 一类（本端既非活单位也非 pending），与 `stale` / `unconfirmed` 分开计数；`dispatch.GAP_ROUTE` 增 `quality:crosswalk_dangling`；验证：`tests/test_bench_quality*.py` 新用例构造 8 条悬空 + 三态全缺，断言报两项、条数各 8；派单路由用例断言聚合键为域
- [x] 1.4 生产导入观测层模板：`uv run python scripts/import_protocol_ontology.py --dry-run` 先看计划，再真跑；验证：`ontology_templates` 多出 `external-world` 一个名字 / 一个版本，既有 6 个名字的版本数与 schema 字节零变化；模板详情显示 `layer=observation`、`authority=external`、`aligned_with` 含 8 条 `type_map` 条目
- [x] 1.5 为 1.4 写/更新测试：断言 `_aligned_with` 从协议声明读取（不硬编码）、声明缺失时返回空；验证：`uv run pytest tests/ -k "protocol_ontology or alignment"` 全绿
- [x] 1.6 重跑 `scripts/import_connector_crosswalks.py --domain erp --dry-run`：验证 dry-run 输出逐条报「本端不存在」而非静默计划写入（这是 1.2 生效的证据）

## 2. ERP 竖切片（一）：补实体让悬空清零

- [x] 2.1 新增 `scripts/seed_erp_provider_entities.py`：按 `fd-erp-vertical-templates/connector-status.json` 的 9 条 integration 建 8 个去重后的 provider 实体（`kind='organization'`，`attrs` 带 `external_system` 与 `template`），幂等 + `--dry-run`；验证：dry-run 打 8 条计划；真跑后 `knowledge_units where namespace='erp' and kind='organization'` = 8；重跑不新增
- [x] 2.2 重跑 `scripts/import_connector_crosswalks.py --domain erp`（带 --force）：验证 8 条 crosswalk 全部「幂等命中」；随后 `quality.crosswalk_gaps(erp)` 的 `dangling` = 0、`stale` = 8（三态全缺，如实）
- [x] 2.3 新增 `scripts/import_account_mapping_crosswalks.py`：读 3 个 `account-mapping/pack.json`，落 23 条 `maps_to`（本端 `account:<行业码>`，对端 `external_id{system: "universal-accounts", id: <maps_to>}`），导入时校验目标码在 12 码闭集内，越界即拒；幂等键 `(kind, namespace, external_key)`；验证：dry-run 打 23 条；真跑后 `kind='crosswalk' and attrs->>'relation'='maps_to'` = 23；重跑零新增；把一条 pack 的 `maps_to` 临时改成 `5300` 的用例断言拒绝且点名该码
- [x] 2.4 写 `tests/test_import_account_mapping_crosswalks.py`：覆盖三行业前缀不互相覆盖（`X-0001` 与 `R-0001` 并存，靠前一条 attrs 字节不变）、重复导入幂等、越界码拒绝；验证：该文件全绿
- [x] 2.5 `docs/` 补一段：erp 域从「8 条悬空 / 0 实体」到「8 实体 / 31 条映射」的变化与依据（不改 spec，只补作业记录）→ 落在本 change 的 `acceptance.md`，不新建仓内文档

## 3. ERP 竖切片（二）：尺子 + 模板升版 + 域重锚

- [x] 3.1 新增 `scripts/seed_erp_rubric.py`（沿 `seed_gov_rubric.py` 形状）：判据取自 `fd-erp-vertical-templates` 的边界四条 + 科目预设不变量，落到 erp 域的 rubric（`domain_id` = erp）；验证：dry-run 打条目；真跑后 `rubrics where domain_id=<erp>` = 1 且 criteria 条数与脚本声明一致；重跑幂等（先删 criteria 再插，与 gov 先例同手法）
- [x] 3.2 `enterprise-base` 升 v3 并声明 `rubric_refs`（走 `template_readiness.promote_template_via_gate`，首次升版记「立基线」）；验证：模板表多一行 v3、`schema->'rubric_refs'` 非空；v2 行字节不变；升版日志显示 gate=`no-worse`、结局为立基线
- [x] 3.3 把 erp 域重锚到 v3（`UPDATE domains SET template_id, template_version`，带 old→new 打印与回滚串）；验证：`domains` 里 erp 的 `template_version`=3；域控制台本体台账的「锚定版本 vs 最新版本」不再报落后
- [x] 3.4 质量视图核对：erp 域的 `quality:template` 缺口消失、`模板可评性` 解析率 = 100%；验证：域总览页该项显示 1/1 而非「不可评」

## 4. 金融竖切片：开域 + 金标 + 尺子

- [x] 4.1 从 `finance-market` v2 实例化金融域（key `finance`，名「金融数据域」），参照 `register_legal_domain.py` 的 idempotent 手法；验证：`domains` 多一行；`instantiate_domain` 不因尺子为空而拒（草稿域合法），控制台标「草稿」
- [x] 4.2 新增 `scripts/seed_finance_rubric.py`：7 个 checker 的判据写成 rubric criteria，挂到 finance 域；验证：`rubrics where domain_id=<finance>` = 1，criteria = 7；同样幂等重跑
- [x] 4.3 `finance-market` 升 v3 声明 `rubric_refs` 并把 finance 域重锚；验证：同 3.2/3.3 的判据，v2 行不变
- [x] 4.4 落 gold-v9：以 `packs/finance-data/adapters.py::load_sentiment_gold` 的同一逻辑写进 **finance 域 namespace**（现适配器写死 `namespace='finance-data'`，需参数化或加一层域内落库脚本）；验证：`knowledge_units where namespace='finance' and kind='fact'` = 105、`tier='gold'`；重跑幂等不新增；兄弟仓缺失时**硬失败不写空**（用例覆盖）
- [x] 4.5 为 4.4 写测试：断言「兄弟仓不存在 → 抛错且零行写入」「存在 → 105 行且二次运行 105 行」；验证：新测试文件全绿

## 5. 发布与消费判据

- [x] 5.1 **erp 发布本体 v1 `f1e3771d`**；finance 不走本体发布（gold 是事实资产不是实体）——改走 `scripts/publish_domain_assets.py` 得 `finance/fact v1 5edc37f7`。两者 digest 均读回自表，非信任返回值
- [x] 5.2 公开概览 `totals.domains` 2→**3**（合法/gov/erp）；finance 只发资产不发本体故不在列。需等 `law-bench-public-sync` 灌一轮副本（15min CronJob）
- [ ] 5.3 消费侧分段判据：24h 后查 `distribution_pull_events` 里 `domain_key='erp'` 的行数；>0 记「已接通」，=0 如实记「已发布、消费方未接」；验证：结论写进 `acceptance.md`，MUST NOT 因发布成功就写「已接通」

## 6. 验收

- [x] 6.5 相邻域调研（`data-ontology` 7 条 pending）：产出 `verdict-data-ontology-proposals.md`——2 条 evidence 结构上永远落不下去、5 条同批数据两个提交方各提一遍 + 键含非身份列。**未经人类签字不执行驳回**；同时补上 `reject` 缺失的机器身份闸（与 `confirm` 对称）

- [ ] 6.1 全量回归：`uv run pytest tests` 全绿（本机只做静态与单测，真机行为以 5.x 为准）
- [ ] 6.2 `bash scripts/smoke_prod.sh` 绿（部署后）
- [x] 6.3 `openspec validate add-finance-erp-domain-slices --strict` 绿
- [x] 6.4 写 `acceptance.md`：逐条判据 + 证据（生产 SQL 输出 / 页面截图 / digest），并把设计里的两条已知边界（`instrument` 一对多未声明、`data-ontology` 未动）如实登记
