# Design · harden-console-table-overflow

## Context

见 proposal「Why」。实现已上产（`sha-a5df88e`），本 change 补判据与约束。

现状：控制台没有任何自动化 UI 判据。已有的 CI（`knowledge-surface.yml`）跑 pytest，
覆盖后端行为；渲染后的页面宽度不在任何断言之下——这是四轮返工的根因。

## Goals / Non-Goals

Goals：让「页面有没有横向溢出」成为一条可复跑、退出码可判的断言；把断行规则写成可枚举的契约。

Non-Goals：不引入前端测试框架；不做视觉回归截图对比（那是另一个量级的事）；不改表格信息架构。

## Decisions

**D1 · 判据是脚本 + 退出码，不是 CI 的一步。**

控制台需要登录（Logto），而 GitHub runner 拿不到生产会话。因此判据是一个独立脚本，
在有凭据的机器上跑；不进阻塞式 CI。

代价：不会被每次提交自动执行。缓解：把「上产前后各跑一次」写进验收清单，
并要求输出落盘（谁跑的、什么时候、哪些页面）。

**D2 · 三态退出码，与前一轮的探针一致。**

`0` 全部零溢出 / `1` 检出溢出（输出页面与像素数）/ `2` 未判定（无凭据、页面不可达）。
理由：本仓已有先例——`scripts/check_status_wording.py` 与 fd-bench-web 的
`check_facts.py` 都用「未判定 ≠ 通过」的三态。假绿门比没有门更糟。

**D3 · 视口固定为 1440×900 与 390×844。**

对应真实使用（笔记本与手机），也与既有本仓截图脚本一致。不追加更多断点——
判据的目的是「不被撑破」，不是覆盖所有设备。

**D4 · 判据必须先在有真实数据的库上跑过一次并被记录。**

本地库每域只有数条单位，列宽问题不出现。判据文档与 task 里都要求
「至少在 legal 域（5000+ 单位）上跑过一次」，并在报告里写明确切环境。

**D5 · 断行规则的分层。**

```
td                       overflow-wrap: anywhere        （兜底）
td[colspan]              white-space: normal            （nowrap 优先，必须显式清）
td > div / p / span      min-width:0 + overflow-wrap    （块级子元素自成 min-content）
td 内 .inline-form       flex-wrap: wrap                （表单不撑宽）
.table（非 data-table）   同一套规则                     （类名不统一是真实存在的）
窄屏 .layer-body          overflow-x: auto               （四列表格放不下时容器内滚动）
```

`white-space: nowrap` 只允许出现在显式的列例外上（时间列、操作按钮列），
且每加一处都要有注释说明原因。

## Risks / Trade-offs

- [判据不进 CI，会忘记跑] → 写进上产清单；脚本本身在无凭据时明确报「未判定」，不会静默通过。
- [凭据扩散] → 脚本从环境变量读账号，不落盘；判据文档里不写具体凭据。
- [断行规则可能让某些表格变得很难读（长内容全挤在一列）] → 这是表格结构问题，
  应另立 change 处理（例如把长文本列改为可展开）。本 change 只保证「不撑破页面」。

## Migration Plan

无数据迁移。样式与 logger 已上产；判据脚本随本 change 落地。

## Open Questions

- 判据要不要覆盖 `/admin/*` 平台页？当前先覆盖域内页与 `/d`，平台页后续按需追加。
