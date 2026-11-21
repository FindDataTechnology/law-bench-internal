# 控制台横向溢出判据 — 首次全量运行（2026-11-21）

## 判据

`scripts/check_console_overflow.py`：登录生产控制台 → 从 `/d` 解析全部域 → 遍历
`/d` + 每域六个页（本体/知识库/提案/发布/值班/升格）→ 两个视口（1440×900 / 390×844）
断言 `scrollWidth - clientWidth === 0`。三态退出码：0 全零 / 1 检出溢出 / 2 未判定。

## 运行结果

```
环境    https://lawbench.finddatatech.cloud（生产，legal 域 5000+ 单位）
时间    2026-11-21
命令    python3 scripts/check_console_overflow.py
结果    ✓ 31 页 × 2 视口全部零溢出
退出码  0
```

覆盖：5 个域（legal / gov / finance / erp / data-ontology）× 6 个域内页 + `/d` = 31 页。

## 判据自身的有效性

`--self-check` 三条夹具全过：干净页绿、桌面溢出红、移动溢出红。
无凭据时退出码 **2**（未判定），与「通过」(0) 和「检出溢出」(1) 均不同。

## 写这个脚本时踩的坑（已修，留作证据）

第一版用 `a[href^="/d/"]` 选域链接，**取到 0 个域**，判据于是只测了 1 页还报「通过」。
生产实测：域链接是**绝对 URL**（`https://host/d/legal`）。改为按 `/d/` 片段解析，
并加守卫：解析不出任何域 → 退出码 2「未判定」，不是通过。

**这正是本 change 要防的那类假绿**——判据在没真正覆盖时看起来是绿的。

## 四轮修复的漏点（为什么判据必须枚举全部继承路径）

| 轮次 | 加了什么 | 漏了什么 |
|---|---|---|
| 1 | `.data-table td` 的 `overflow-wrap` | 值班页用的是 `.table` 类 |
| 2 | `.table` + 单元格内 `.inline-form` flex-wrap | `<td colspan>` 单元格 |
| 3 | `td[colspan]` 的断行 | `white-space: nowrap` 优先于任何 `overflow-wrap` |
| 4 | `td > div` 块级子元素 | （真根因：驳回理由 div 占 1553px） |

夹具红证（长文本 + 两种容器形态）：旧规则 tableW=6396 / 溢出 4977px；新规则 1398 / 0。
