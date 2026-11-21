# Tasks · harden-console-table-overflow

## 1. 溢出判据

- [x] 1.1 新建 `scripts/check_console_overflow.py`：登录（账号密码从环境变量读）→ 遍历
      `/d`、`/d/{domain}` 与七个域内页 → 两个视口断言 `scrollWidth - clientWidth === 0`。
      验证：在合法会话下运行，输出每页两个视口的读数与结论行。
- [x] 1.2 三态退出码：`0` 全零 / `1` 检出溢出（打印页面与像素）/ `2` 未判定（无凭据或
      页面非 200）。验证：分别用正确凭据、故意破坏的页面、空凭据三种情况跑，确认三个不同退出码。
- [x] 1.3 判据自带 `--self-check`：构造「干净页」与「会溢出的页」两个夹具，
      断言判据对前者绿、后者红。验证：夹具双向都成立（防恒绿）。
- [x] 1.4 在**生产**（legal 域 5000+ 单位）上跑一次，把输出落
      `reports/<date>-console-overflow.md`。验证：报告含环境、时间、每页读数。

## 2. 断行规则契约化

- [x] 2.1 复核 `src/web/static/style.css` 现有规则，为每条 `white-space: nowrap` 加一行注释
      说明「为什么这一列不能折行」。验证：`grep -n "nowrap" src/web/static/style.css` 每条都有注释。
- [x] 2.2 `td[colspan]` 与 `td > div/p/span` 两组规则必须存在且带注释（说明 nowrap 优先级
      与 min-content 上下文这两个坑）。验证：grep 到两组规则。

## 3. 启动健壮性

- [x] 3.1 `src/web/app.py` 的模块级 `logger` 存在，且启动期清理的 `except` 分支引用它。
      验证：故意让清理抛异常（连不存在的库），应用仍能启动并打出告警。
- [x] 3.2 补一条测试：mock 清理函数抛异常，断言 `create_app()` 正常返回（不抛）。
      验证：该测试在移除 logger 定义时变红。

## 4. 收口

- [x] 4.1 在 `reports/` 写明：本次四轮修复各自的漏点（`.table` → `colspan` → `nowrap`
      优先级 → 块级子元素），作为「为什么判据必须枚举全部继承路径」的证据。
      验证：报告存在且含四轮列表。

## Workflow follow-up

- 上产前后各跑一次 `check_console_overflow.py`；两次结果都落盘。
- 判据不进阻塞 CI（需登录凭据）；若将来有测试账号可注入 runner，再评估接入。
