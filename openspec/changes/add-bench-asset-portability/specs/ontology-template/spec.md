# Spec Delta

## ADDED Requirements

### Requirement: 模板可声明复制血缘

模板 SHALL 可选地声明 `derived_from`、`fork_diff` 与 `upstream{name, version, digest}`。三者一旦声明 `derived_from`，`fork_diff` 与 `upstream` SHALL 同时存在；缺任一项 SHALL 被拒绝。血缘 SHALL 只读记录来源，MUST NOT 改变模板的层、继承规则或实例化行为。

#### Scenario: 缺差异说明拒绝

- **WHEN** 保存一份 `derived_from` 指向官方模板但没有 `fork_diff` 的模板
- **THEN** 拒绝并说明复制件必须记录与来源的差异

#### Scenario: 血缘不改变层规则

- **WHEN** 一份带血缘的模板声明了与父模板不同的 `layer`
- **THEN** 仍按既有分层规则拒绝跨层继承

### Requirement: 导入模板受既有继承与完整性规则约束

从信封导入的模板 SHALL 通过与手工创建相同的 schema 校验（四类词表完整、tier/sensitivity 词表、层声明、`extends` 同层只增不删）。导入 MUST NOT 绕过这些规则；校验失败 SHALL 整体拒绝且不创建模板。

#### Scenario: 缺词表的导入模板被拒

- **WHEN** 导入一个缺少 tier 词表的模板信封
- **THEN** 拒绝并报明缺失项，模板未被创建

#### Scenario: 合规导入模板可实例化

- **WHEN** 导入的模板通过全部校验
- **THEN** 它可以像手工创建的模板一样被实例化为域，且有效词表完整
