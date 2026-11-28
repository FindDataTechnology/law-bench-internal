# Tasks

## 1. 数据与校验

- [x] 1.1 `ontology_templates` 增加 `derived_from`、`fork_diff`、`upstream` 三列（可空，幂等 DDL）
- [x] 1.2 新增只增审计表 `asset_transfer_events`（谁/何时/类别/digest/目标/结果）
- [x] 1.3 模板保存校验扩展：声明 `derived_from` 时 `fork_diff` 与 `upstream` 必填
- [x] 1.4 导入时的加法校验接入内核 `vocab.assert_additive`（对照 upstream 词表）

## 2. 导出

- [x] 2.1 实现五类资产的信封装配（模板 schema / 词表 / ruler-set / gold-set / eval-suite），digest 走内核 `digest_of`
- [x] 2.2 导出端点：按类别产出信封，只读、无发布行、无拉取足迹
- [x] 2.3 未注册类别导出拒绝并列出已注册类别
- [x] 2.4 断言同一内容导出 digest 与发布 digest 相等

## 3. 导入

- [x] 3.1 实现信封解析与校验（digest、逐文件 sha256、类别、shape 支持）
- [x] 3.2 单事务创建模板；失败零写入、零临时残留
- [x] 3.3 导入幂等（同 digest 重复导入不新增行）
- [x] 3.4 导入不建域、不发布、不绑定消费者
- [x] 3.5 导入模板走既有 schema 校验（四类词表、层、extends 同层只增不删）

## 4. 接入与开关

- [x] 4.1 `BENCH_ASSET_PORTABILITY` 部署开关，默认关闭并返回可读原因
- [x] 4.2 导出/导入的身份与角色校验（管理角色 / 平台管理员）
- [x] 4.3 审计写入只记成功导入；失败不留成功记录

## 5. 验证

- [x] 5.1 单文件测试：导出→导入往返，digest 与有效词表逐字段相等
- [x] 5.2 负例：篡改信封（整体拒绝、零写入）
- [x] 5.3 负例：缺 `fork_diff`、删除上游词表项（拒绝并指名）
- [x] 5.4 负例：未开启开关时的端点行为
- [x] 5.5 运行内核符合性闸，确认本仓六端口在新断言下可执行（SKIP 如实列出）

## 6. Workflow follow-up

- 契约 change `bench-asset-portability` 归档后再归档本 change。
- 谦面侧 `add-pack-bench-ability` 的 `fork` 落地依赖本 change 的导入端点。
- `gold-set` / `eval-suite` / `vocabulary-release` 的导入需要目标上下文，本版仅导出；后续 change 补机器端点。
