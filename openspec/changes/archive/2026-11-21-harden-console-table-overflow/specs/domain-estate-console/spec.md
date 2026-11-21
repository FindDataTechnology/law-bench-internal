# Delta · domain-estate-console

## ADDED Requirements

### Requirement: 表格页横向溢出须有可复跑判据

运营台与其域内页面 SHALL 有一条可复跑的横向溢出判据：按固定视口（桌面 1440×900、
移动 390×844）遍历全部域内页与全域页，断言
`document.documentElement.scrollWidth - clientWidth === 0`。

判据 SHALL 在有真实数据的库上执行——本地稀疏数据测不出多域列宽问题
（2026-11-20 实测：本地一页正常、生产同页 2655px 溢出的直接原因就是数据量差异）。

判据在拿不到登录凭据或页面不可达时 SHALL 输出「未判定」并以区别于「通过」的退出码结束，
MUST NOT 把「没跑成」记成「通过」。

#### Scenario: 全部页面零溢出

- **WHEN** 判据在两个视口遍历全部域内页
- **THEN** 每页的 `scrollWidth - clientWidth` 均为 0

#### Scenario: 无凭据时不冒充通过

- **WHEN** 判据拿不到登录会话或页面返回非 200
- **THEN** 输出「未判定」并以非零退出码结束，且该退出码与「通过」和「检出溢出」都不同

#### Scenario: 本地稀疏数据不构成证据

- **WHEN** 判据只在本地开发库（每域仅数条单位）上运行并全部通过
- **THEN** 该结果 SHALL NOT 被视为表格列宽合格的证据

### Requirement: 单元格断行规则须覆盖跨列与块级子元素

承载用户内容的表格单元格 SHALL 允许长内容断行。`white-space: nowrap` MUST NOT 被无差别
加在 `td` 上；若某列确需不折行，其例外 SHALL 显式、可枚举。

跨列单元格（`td[colspan]`）与单元格内的块级子元素（`div` / `p`）SHALL 各自显式获得断行规则：
`overflow-wrap` 单独写在 `td` 上不足以覆盖它们——`nowrap` 的优先级高于任何断行属性，
而块级子元素自成 min-content 上下文。

#### Scenario: 跨列单元格内的长文本

- **WHEN** 一个 `td[colspan="7"]` 内含 840 字无空格中文
- **THEN** 该表格宽度不超过其容器，页面不产生横向滚动

#### Scenario: 单元格内块级子元素内的长文本

- **WHEN** 一个 `td` 内含 `<div>`，其文本是长串无空格中文
- **THEN** 该 `td` 不因该子元素撑宽，子元素自身断行

#### Scenario: 列 nowrap 例外须可枚举

- **WHEN** 某列需要保持不折行（如时间列、操作按钮列）
- **THEN** 该例外以显式选择器声明，而非用 `td { white-space: nowrap }` 一刀切
