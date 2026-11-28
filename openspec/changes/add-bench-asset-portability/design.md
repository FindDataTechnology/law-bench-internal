# Design

## Context

见 proposal.md「Why」。本仓现状：

- 模板存于 `ontology_templates`（`templates.py`，schema 为 JSONB），已有层、继承、外部权威与校验规则；模板行没有复制血缘字段。
- 本体发布由 `distribution.publish_domain` 生成，内容快照经内核 `build_payload`（shape 2，key-addressed），已含 `template_name/template_version/entity_types/relationship_kinds`。
- 尺子/金集等由 `publication_kinds` 注册投影、`asset-publication` 冻结版本；rubric 已有 `derived_from`+`fork_diff`（`domain_rubrics.ForkError`）。
- `src/bench/conformance_adapter.py` 已把六端口跑在一次性 PG 沙箱上，`adapters.json` 已登记。

## Goals / Non-Goals

**Goals:**

- 五类资产的导出/导入端点，消费 root 契约信封。
- 模板级复制血缘与加法校验。
- 部署开关与审计留痕。

**Non-Goals:**

- 不自动建域、不自动发布、不自动绑定消费者。
- 不导出域包代码（`components`）。
- 不改变既有发布与拉取语义。

## Decisions

### D1 信封由现有投影拼装，不新造内容表示

- 决策：`ontology-template` 取模板 schema 行；其余四类取各自注册投影/发布载荷；信封 digest 用内核 `digest_of`。
- 理由：发布已经证明内容可规范化；信封只是换容器。
- 备选：为信封定义一套新的资产模型——被否，会与发布和领域资产目录产生第二套词汇。

### D2 血缘落在模板行的三列，而非单独表

- 决策：`ontology_templates` 增 `derived_from`（父模板 id）、`fork_diff`（jsonb）、`upstream`（jsonb：name/version/digest）。
- 理由：与 rubric 的 `derived_from`/`fork_diff` 同形；读面一次查询即可显示血缘。
- 备选：单独 lineage 表——被否，模板血缘是一对一，单独表只增加 join。

### D3 导入用「校验-解析-单事务写入」

- 决策：先在内存完成 digest/完整性/类别/加法校验，再在单事务内建模板；失败零写入。
- 理由：本仓已因「先写后验」踩过静默半包；信封不能重演。
- 备选：逐条写、失败回滚——被否，错误信息无法指向第一个失败项。

### D4 导入只建模板，不建域

- 决策：导入返回模板标识；建域仍是 `workspaces.instantiate_domain` 的显式调用。
- 理由：域是长期资产（`domain-lifecycle`：归档不释放 key），不能由一次导入隐式创建。

### D5 端点受部署开关与既有身份模型约束

- 决策：`BENCH_ASSET_PORTABILITY=1` 才挂载；导出需管理角色，导入需平台管理员；审计表 `asset_transfer_events` 只增。
- 理由：跨实例搬运是高风险动作；默认关闭保证未开启部署的既有行为逐字节不变。
- 备选：与发布共用一个开关——被否，发布已上线，搬运是新面。

### D6 加法校验调用内核，不复制规则

- 决策：导入 fork 时用 `fd_ontology_kernel.vocab.assert_additive` 对照 `upstream` 解析出的父词表。
- 理由：规则只有一份；复制会在某一侧漂移。
- 备选：本地比较集合——被否，退役语义（`superseded_by`）会漏。

## Risks / Trade-offs

- [schema 迁移加列] → 迁移只加可空列，旧行零变化；回滚只需停用开关。
- [信封体积] → 五类资产均为词表/尺子级数据；大语料不入信封，仍走 `library:<id>` 引用。
- [客户端实例版本漂移] → 信封携带 `manifest_shape`；未知 shape 按内核 `shape_spec` 拒绝并列出支持版本。
- [审计表增长] → 只增不改，随实例生命周期保留；与既有拉取足迹同策略。

## Migration Plan

1. 加三列与审计表（幂等 DDL，走既有 `ensure_schema`）。
2. 上线开关默认关闭的端点。
3. 先在测试实例做官方模板导出→空实例导入往返。
4. 开启后再接谦面侧的 `fork` 落地。
5. 回滚：关开关即回到旧行为；已导入资产保留（它们已是普通资产）。
