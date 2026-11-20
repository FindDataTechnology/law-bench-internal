# Tasks · console-progress-and-value

> 改动集中在 `law-bench-internal`。**不触碰** `add-domain-next-actions` 将新建的
> `src/bench/next_actions.py`（该 change 管「该做什么」，本 change 管「现在值多少分」）。

## 1. 质量比可见

- [x] 1.1 `domain_list.html` 加「质量比」列，遍历 `r.quality` 的八项渲染；三态可辨——
      达标默认、低于阈值琥珀、无物可算显示 `—`（不显示 0/100%）。验证：实测
      `/d` 输出含 `证据率 0.00`（琥珀）与 `接地率 —`（无物可算），两者渲染不同。
- [x] 1.2 `review_lag` 单独分支带 `h` 后缀（它是小时数不是比率）。验证：模板分支存在，
      实测无 `%.2f` 误显示为比率。
- [x] 1.3 `console.py` 的 `console_domain_list` 传 `thresholds` / `high_is_better` 供模板
      判方向与门槛；**不重算**任何比率。验证：`estate.matrix()` 的调用点未变，模板只读
      `r.quality`。
- [x] 1.4 CSS：`.quality-cell` 与 `.q / .q-bad / .q-na` 三态；柱子列 `nowrap` 防折行。
      验证：截图确认列宽正常、数字不折行。

## 2. 缺口徽标不再空

- [x] 2.1 i18n 补 `gap_quality_*` 八个键（中英各一套）+ `metrics_h3` + `metric_*` 八项 +
      两个状态词。验证：`label_catalog_parity()` 为 True。
- [x] 2.2 `domain_list.html` 的缺口循环按 `quality:` 前缀分色，缺键时退到
      「质量不达标 (原始键)」，不渲染空徽标。验证：实测页面 `空 label 的 badge = 0`，
      且 `证据率低`/`模板不可评` 有字。
- [x] 2.3 补 `badge-warn` / `badge-quiet` 的 CSS（此前 16 处模板引用、CSS 里零定义）。
      验证：两个 class 在 style.css 中存在。

## 3. 升格阶梯可达

- [x] 3.1 新建 `domain_console_promotion.html`：阶梯三档计数 + 单位列表 + 空态。
      验证：`/d/{key}/promotion` 返回 200，正文含「升格队列」与三档标签。
- [x] 3.2 新建路由 `GET /d/{domain_key}/promotion`（name=`console_promotion`，只读）。
      验证：带测试会话请求返回 200。
- [x] 3.3 注册进 `AREAS`（`min_role=annotator`）与 `_domain_zone_nav.html` 的
      `area_endpoints`；i18n `console.areas.promotion` 中英各一条。验证：截图区导航含「升格」。
- [x] 3.4 只列 `PROMOTABLE_KINDS`，并且不显示自相矛盾的 `len/total`。验证：实测插入一条
      `entity` 单位后显示「bronze 1 / 合计 1 / 本页显示 1」；`crosswalk` 单位不出现在队列里。

## 4. 回门面

- [x] 4.1 `base.html` 顶栏品牌旁加「← 介绍站」指向 `bench.finddatatech.cloud`；i18n
      `nav.site_link` 中英各一条；CSS `.brand-site` 更轻。验证：截图顶栏可见。

## 5. 验收

- [x] 5.1 本机启动应用（`RULES_PORT=8091 bash scripts/serve_web.sh`）并带签名会话实访：
      `/d` 200、`/d/erpprobe/promotion` 200。验证：curl 状态码 + 正文抽取。
- [x] 5.2 其他区零回归：`/d/erpprobe/publish`、`/ontology`、`/team` 均 200。验证：curl。
- [x] 5.3 `py_compile` 通过；四个 Jinja 模板能被 `Environment.get_template` 解析。
      验证：命令输出。
- [x] 5.4 i18n 双语齐：`label_catalog_parity()` → True。验证：命令输出。

## Workflow follow-up

- 本机未跑 pytest（用户明令：执行一律 GitHub Actions）。上产前须在 CI/真机跑一次
  `uv run pytest tests/test_admin_web.py tests/test_distribution_web.py`，确认模板改动无回归。
- `/dashboard` 的收编与 `add-domain-next-actions` 的边界留到下一轮，见 design「Open Questions」。
