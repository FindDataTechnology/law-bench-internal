# Proposal

## Why

知验台目前只能发布本体的「内容快照」，模板结构与尺子/金集没有便携导出与导入通道；模板也没有 `derived_from`/差异说明，客户无法把官方模板复制到自己的实例后长期维护且保持可追溯。root 契约 `bench-asset-portability` 定义了信封与三档维护，本变更把它落到知验台侧。

## What Changes

- 新增模板/尺子/金集的**导出与导入机器端点**：产出与消费 root 契约定义的便携信封，校验 digest 与完整性后才写入。
- 模板新增 **`derived_from` + `fork_diff` + `upstream{name,version,digest}`** 字段；导入 fork 时对上游词表执行加法校验。
- 导入一个 `ontology-template` 信封时，可在本实例创建对应模板；导入不自动创建域、不自动发布。
- 已注册的 `asset-publication` 种类与 `ontology-template` 都成为信封可导出资产，digest 与同内容发布一致。
- 导入导出默认关闭，由部署配置开启；不改变既有发布/拉取行为。

## Capabilities

### New Capabilities

- `bench-asset-export-import`: 模板、尺子集、金集、评测套件的便携导出与导入；digest/完整性校验；fork 血缘与加法校验；导入不自动建域/发布。

### Modified Capabilities

- `ontology-template`: 模板新增复制血缘（`derived_from`/`fork_diff`/`upstream`），并允许从导入的信封实例化模板（仍受既有继承与层规则约束）。
- `asset-publication`: 已注册的发布种类可被导出为信封，导出 digest 与该种类发布时的 digest 相等。

## Impact

- 新增机器端点（受部署开关与既有凭据模型约束），不改既有 `GET /api/v1/distribution/...` 的拉取语义。
- `src/bench/templates.py`、`src/bench/domain_rubrics.py`、`src/bench/distribution.py`、`src/bench/publication_kinds.py`、符合性适配器。
- 与 `fd-ontology-kernel` 的信封格式、digest 共用，无第二份实现。
