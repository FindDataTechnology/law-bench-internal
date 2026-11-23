# Tasks: deepen-industry-lines

> 三个能力同一套闭环：评测可归属（C1）→ 改完登记复测（C2）→ 台账不误报（C3）。
> 纪律：行业判据必须先在真库证明有区分度才上（`criterion-must-fire-on-real-data`）。

## 0. 前置

- [x] 0.1 真库实测各国行业 ruler 的区分度基线：`finance` 7 checker 全绿（已知）；`erp` 新 4 条
      在 23 account + 31 crosswalk 上各记 PASS/FAIL 数，作为可区分性证据抄进 `acceptance.md`
- [x] 0.2 确认 `packs/gov/checks.py` 导入后 `gov-fact` checker 非空，并记录其生产单位（document）
      与该 checker 期望单位（gov-fact）不相交 ⇒ 生产将 inconclusive 这一事实

## 1. C1 — 数据评测可归属、可跑（`domain-data-eval`）

- [x] 1.1 `src/eval/store.py::store_result` 增可选入参 `rubric_domain_id`；未传时按 `rubric_name`
      唯一命中 `rubrics.domain_id` 回填，零/多命中留 NULL；INSERT 写该列
- [x] 1.2 `src/bench/data_checks.py::run_data_eval` 解析并透传 `rubric_domain_id`
- [x] 1.3 新 `src/bench/data_eval.py::run_domain_data_eval(conn, domain_key, kind=None)`：枚举本域
      活跃单位 → `run_data_eval`；空集 inconclusive；返回 run id + 三态 + 通过比
- [x] 1.4 新 `packs/erp/`：`__init__.py`（`from . import checks`）、`checks.py`（D3 四条）、
      `pack.yaml`（kinds=[account,crosswalk]、eval_suites=[erp-ontology-consistency]）
- [x] 1.5 ~~`packs/gov/__init__.py` 补 `from packs.gov import checks`~~ **不做，理由如下**：gov 生产单位是 `document`（公文本体），而 `packs/gov/checks.py` 评的是 `gov-fact`（registry 事实），两者不相交 ⇒ 即便导入，gov 域的可评 kind 仍为空、写一条 inconclusive。导入只会在进程里注册一批匹配不到任何单位的 checker，是「看起来接上了、实际永远判不出来」。gov 的真实 registry 单位接生产另立（见挂账 6.2）。gov 域因此如实报「暂无确定性判据」，这正是 domain-data-eval 要的诚实空态。
- [x] 1.6 `src/web/routes/console.py`：`POST /d/{key}/eval-runs/data-eval`（`_LEAD_GATES` +
      `content:write`），调 `run_domain_data_eval`，flash 三态 + 通过比；`domain_console_bench.html`
      增按钮（仅 `cap.can_write` 且该域有 pack/checker 时）
- [x] 1.7 i18n：`console.bench.data_eval.*` zh/en 成对

## 2. C2 — 复测义务登记与展示（`domain-retest-loop`）

- [x] 2.1 `src/bench/proposals.py::confirm` 成功写单位后 try/except 调
      `verdicts.register_retest(domain_key, subject_kind='knowledge-unit', subject_key=<kind:key>,
      subject_version=<silver>, baseline_run_id=<域最近结论或 None>)`，异常吞（D5）
- [x] 2.2 `src/bench/template_readiness.py::promote_template_via_gate` 成功分支登记
      「template @name@version」复测（try/except，fail-open）
- [x] 2.3 `src/web/routes/console.py` 的 `eval-runs` 路由读 `verdicts.find_open_retest` 列表
      （扫本域 `authoring_tasks` `target_kind='verdict-retest'` 未结）传入模板
- [x] 2.4 `domain_console_bench.html` 增「待复测」面板：标题 / 目标版本 / 基线 id / 状态；
      无则明说「没有待复测项」
- [x] 2.5 i18n：`console.bench.retest.*` zh/en 成对

## 3. C3 — 台账把内核缝单列（`ontology-ledger-seam`）

- [x] 3.1 `src/bench/ledger.py`：`SEAM_KINDS = frozenset({proposals.CROSSWALK_KIND})`；
      `reconcile` 输出增 `seam_kinds`，`out_of_vocab_kinds` 扣除 seam；`consistent` 用扣后集合
- [x] 3.2 `domain_console_ontology.html`：越界 kind 区块把 `seam_kinds` 单列并标「内核缝·不算越界」

## 4. 测试

- [x] 4.1 `tests/test_data_eval_domain.py`：归属回填（唯一命中写、零/多命中 NULL）、按域跑出结论、
      空域 inconclusive、纯读边界（只写 eval_runs + authoring_tasks on confirm）
- [x] 4.2 `tests/test_erp_checks.py`：每条 checker 一条 PASS 样例 + 一条 FAIL 样例（区分度铁证）；
      一条「缺 confidence ⇒ FAIL」真样例
- [x] 4.3 `tests/test_retest_wiring.py`：确认后出现 verdict-retest 工单、升版后出现、
      register 抛异常不回滚确认/升版
- [x] 4.4 补 `tests/test_domain_ledger.py`：seam_kinds 单列、crosswalk 不再入 out_of_vocab、
      真正越界仍报、consistent 仍正确
- [x] 4.5 `python3 scripts/check_kernel_domain_free.py`：`src/bench` 仍域无涉（ERP 判据只在 packs/erp）

## 5. 生产验收（出片后）

- [x] 5.1 滚镜像到 ccr 后，对 `finance` / `erp` 各跑一次数据评测，取证结论带 `rubric_domain_id`
      且域矩阵「评测」柱 `last_run` 更新
- [x] 5.2 确认（一条 pending 提案）后查 `authoring_tasks` 出现 `verdict-retest` 行，域页显示
- [x] 5.3 ego-browser 真身份（`aloadtree@gmail.com`）走 `/d/erp/eval-runs`：点「跑一次数据评测」→
      看到三态结论 + 待复测面板；截图归档
- [x] 5.4 `scripts/smoke_prod.sh` 绿
- [x] 5.5 `acceptance.md`：逐条判据 + 真库读数 + 区分度证据

## 6. 挂账

- [ ] 6.1（挂账 2026-11-23） 复测义务的自动执行（调度/CI 触发）——本 change 只登记与展示，不执行
- [x] 6.2 gov-fact 真实 registry 单位接生产——**已完成**（2026-11-23 追加）：`scripts/load_gov_registry.py` 幂等落 11 源进 gov 域，8 checker 88/88；生产 run #25/#26 带 gov 域归属。详见 acceptance §8
