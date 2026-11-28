# Spec Delta

## ADDED Requirements

### Requirement: 已注册种类可导出为便携信封

每一个由 pack 注册的发布种类 SHALL 可被导出为 root 契约定义的便携信封。导出的内容 SHALL 与发布同一内容时的条目投影一致，digest SHALL 与该次发布的 digest 相等。未注册的种类 SHALL 在导出处被拒绝并列出已注册种类。

#### Scenario: 尺子导出与发布 digest 相等

- **WHEN** 导出一个已发布过的 `rubric` 种类
- **THEN** 信封 digest 与该次发布的 digest 相等，条目逐字段一致

#### Scenario: 未注册种类导出被拒

- **WHEN** 请求导出一个未注册的种类
- **THEN** 拒绝并列出已注册种类，不产生信封

### Requirement: 导出不产生发布与拉取足迹

导出 SHALL 是只读投影：MUST NOT 产生新版本、MUST NOT 写入拉取足迹、MUST NOT 改变种类的发布状态。发布与拉取仍由既有 distribution 语义承担。

#### Scenario: 导出不改发布历史

- **WHEN** 反复导出同一已发布种类
- **THEN** 发布版本数不变，拉取足迹不增加
