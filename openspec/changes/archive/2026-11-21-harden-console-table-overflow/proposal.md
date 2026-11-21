## Why

2026-11-20/21 修控制台表格横向溢出，**改了四轮才收干净**。每轮都是「看真实页面哪里宽就改哪里」，没有一次先把可能撑宽的情形枚举全：

1. 给 `.data-table td` 加 `overflow-wrap` → 漏了值班页用的 `.table` 类。
2. 补 `.table` + 单元格内 `.inline-form` 改 `flex-wrap` → 漏了 `<td colspan>`。
3. 补 `td[colspan]` → 但 `white-space: nowrap` **优先于任何** `overflow-wrap`，而 nowrap 来自 `nth-child` 列对齐规则。
4. 补 `td > div` → 真根因：驳回理由占 1553px，**块级子元素自成 min-content 上下文**，`td` 上的规则约束不到它。

最终在桌面 1440 与移动 390 两个视口、七个页面上全部归零（最严重的本体页原来 2655px、单格 284,473 字符）。但这四轮说明：**缺一条可复跑的判据**，下次改表格样式还会重犯。

同片还修了一个只在异常分支炸的缺陷：`app.py` 的 `_reap_stale_generation_jobs` 用了未定义的 `logger`，正常启动与 CI 全绿，一旦清理抛异常就 `NameError` → 应用起不来。

## What Changes

- **新增判据**：控制台的表格页 SHALL 有一条可复跑的溢出判据——按固定视口（1440×900 / 390×844）遍历全部域内页与全域页，断言 `document.documentElement.scrollWidth - clientWidth === 0`。判据 SHALL 在有真实数据的库上跑（本地稀疏数据测不出多域列宽问题——这是四轮返工的直接教训）。
- **样式契约**：凡承载用户内容的表格单元格，`white-space: nowrap` MUST NOT 被无差别加在 `td` 上；跨列单元格（`td[colspan]`）与单元格内块级子元素 SHALL 显式获得断行规则，因为 `overflow-wrap` 单独不足以覆盖它们。
- **启动健壮性**：应用启动期的清理步骤在失败时 SHALL 降级（记日志继续启动），MUST NOT 因清理失败而使整个应用退出。
- **非目标**：不重做控制台视觉，不改表格信息架构，不引入前端构建链。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `domain-estate-console`: 新增「表格页溢出须有可复跑判据」与「单元格断行规则须覆盖跨列与块级子元素」两条要求。
- `web-i18n` / `domain-workspace`：启动期清理失败须降级而非退出——挂到既有承载「平台启动行为」的能力上。

> 实现已上产（`sha-a5df88e`）并实测归零；本 change 补的是**判据与约束**，不是功能。

## Impact

- **代码**：`src/web/static/style.css`（断行规则，已改）、`src/web/app.py`（logger，已改）、新增溢出判据脚本。
- **已上产**：镜像 `sha-a5df88e`，桌面+移动十四页归零。
- **风险**：判据需要能登录的真实环境（Logto 账号）；无凭据时会「未判定」而不是「通过」——必须与「通过」区分，否则又是一道假绿门。
