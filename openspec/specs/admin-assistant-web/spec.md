## Purpose

A floating AI assistant bound to **the domain being viewed**: a chat bubble that expands into a conversational panel and answers from that domain's own model (knowledge units, proposals, rulers, what the console says should happen next), through the MCP server's domain face. It was admin-only until 2026-11-24; it is now available to any active member of a domain, with the tool face narrowed by that member's role. With no accessible domain the assistant is not offered at all — a domain-less assistant would degrade back into the global helper this replaced.

## Requirements

### Requirement: Admin-only entry point

The workbench SHALL render the assistant entry point (floating chat bubble and its scripts) only for sessions that hold an active membership in the domain whose page is being rendered. Sessions with no accessible domain (including anonymous visitors and signed-in users who belong to no domain) SHALL receive no assistant markup, scripts, or entry point. Platform administrators SHALL keep cross-domain access.

#### Scenario: Admin sees the bubble

- **WHEN** 一个在某域持有 active 成员身份的用户打开该域的工作台页面
- **THEN** 浮岛被渲染，可展开为聊天面板

#### Scenario: Non-admin sees nothing

- **WHEN** 一个已登录但不属于任何域的用户打开工作台页面
- **THEN** 页面不含助手标记或脚本

#### Scenario: Anonymous visitor sees nothing

- **WHEN** 一个未登录请求打开工作台页面
- **THEN** 页面不含助手标记或脚本

### Requirement: Admin-gated chat API

The assistant chat endpoint SHALL only accept requests whose session resolves to an accessible domain, checked by the workbench's own fail-closed mechanism before anything is forwarded. The check SHALL deny, not degrade, when the domain cannot be resolved. Chat traffic SHALL flow through the workbench's own same-origin proxy; the chat runtime service SHALL NOT be a publicly reachable alternative path to assistant functionality.

#### Scenario: Unauthenticated request is rejected

- **WHEN** 一个没有有效会话的请求到达助手聊天端点
- **THEN** 它在调用运行时之前被拒绝

#### Scenario: Non-admin request is rejected

- **WHEN** 一个有效会话但不在当前域内的请求到达助手聊天端点
- **THEN** 它被拒绝，运行时不被调用

#### Scenario: Session with no accessible domain is rejected

- **WHEN** 一个有效会话但解析不到任何可访问域的请求到达助手聊天端点
- **THEN** 它被拒绝并给出可分辨的原因，运行时不被调用

#### Scenario: Admin request is proxied

- **WHEN** 一个域成员会话发送聊天消息
- **THEN** 请求连同该域与角色被代理到运行时，答复回到同一页面

### Requirement: Destructive tools excluded

The assistant SHALL NOT be able to invoke delete tools (`clause_delete`, `rubric_delete`, `criterion_delete`, `prompt_delete`) or any other tool on the assistant connection's denylist, for any role including platform administrators. Deletion requests made in conversation SHALL NOT change any stored data.

#### Scenario: Delete request does not delete

- **WHEN** 任何角色的用户让助手删除某条评分规则或条款
- **THEN** 不发生任何删除，存储内容保持原样

#### Scenario: Non-destructive work still available

- **WHEN** 域成员让助手检索条款、生成合同或评估草稿
- **THEN** 助手用相应工具完成任务

### Requirement: Floating conversational surface
The assistant SHALL present as a floating chat bubble available on workbench pages; expanding it opens a chat panel where the admin converses in natural language and the assistant streams replies. The bubble SHALL be collapsible and SHALL NOT obstruct page function when collapsed.

#### Scenario: Expand and converse
- **WHEN** an admin clicks the floating bubble
- **THEN** a chat panel opens, accepts a natural-language message, and streams the assistant's reply in place

#### Scenario: Collapse restores the page
- **WHEN** an admin collapses the chat panel
- **THEN** the page is fully usable and only the bubble remains

### Requirement: Graceful degradation
When the chat runtime, the MCP server, or the LLM backend is unavailable, the assistant SHALL surface a clear error in the chat panel and the rest of the workbench SHALL remain fully functional.

#### Scenario: Runtime down
- **WHEN** the chat runtime is unreachable and an admin opens the chat panel
- **THEN** the panel reports the assistant as unavailable and every other workbench page works normally

### Requirement: 助手读得到本域的进行中工作

助手 SHALL 能读到当前域的下一动作与确定性核对结论，并 SHALL 在回答中如实引用它们；当该域没有可执行动作或没有机械判据时，助手 MUST NOT 编造一条。

#### Scenario: 引用本域下一动作

- **WHEN** 域成员问「这个域现在该做什么」
- **THEN** 助手给出的回答与该域页面上「下一动作」投影一致

#### Scenario: 无判据时说无判据

- **WHEN** 域成员问某条内容能不能升格，而该类型的单位没有注册任何机械判据
- **THEN** 助手说明「没有可机械核对的判据」，而不是给出一个通过/不通过的判断

### Requirement: 栈与归属如实记录

本能力所描述的工作台助手 SHALL 与「合同审查产品的前端助手」保持为两个独立的规格：前者的形态是同源代理 + 工作台浮岛 + 独立运行时 + MCP 工具面，后者的形态是另一应用的整站前端。二者 MUST NOT 互相引用为同一份规格。

#### Scenario: 规格清单不指错

- **WHEN** 读者查阅本仓的助手规格
- **THEN** 只看到工作台助手这一份，且其中不声称存在一份掌管浮岛岛内交互的 Next.js 规格
