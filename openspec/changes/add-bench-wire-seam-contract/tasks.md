# Tasks

## 1. 规格落地（本仓）

- [x] 1.1 `add-crosswalk-seam` 的 delta 补一条边界断言：crosswalk 是两层之间唯一的跨层连接，本体关系图谱与模板词表复制都不构成连接；验证：`openspec validate add-crosswalk-seam --strict` 绿，且其 `specs/crosswalk-seam/spec.md` 新增该需求后总需求数 +1
- [x] 1.2 `src/bench/promotion.py::sync_graph` 的模块与函数 docstring 明确「一次性 seed 导入，非持续同步；判据是知验台是否依赖 wire 持续变化」；验证：`python3 -c` 断言 `sync_graph.__doc__` 含 `One-shot` 与 `stall`（依赖判据），`python -m py_compile` 通过（代码行为零变化）
- [x] 1.3 `wire-connector/README.md` 的命令面一节标注一次性语义，并链接到本 change 的 `bench-wire-seam` 能力；验证：README 含「一次性」字样（实测 3 处）且 `常驻同步` 只出现在否定语境（实测 1 处，文案为「已被当成常驻同步通道，违约」）

## 2. wire 侧只读读面（跨仓 fd-wire）

- [x] 2.1 `api/fd_wire_api/bench_pull/routes.py` 新增 console 鉴权只读路由（如 `GET /api/v1/console/bench-ontology`），返回域清单与每域最新版本的**元数据**（domain/version/digest/条目计数/pulled_at），**不返回快照正文**；验证：`api/tests/test_bench_ontology_pull.py` 新增 5 用例（无登录 401 / 有登录 200 / 只出元数据且响应体不含 `payload` 与该实体名 / 空态为空列表 / 内部令牌不是此面凭据）
- [x] 2.2 该路由显式不挂 `X-Internal-Token` 依赖，与既有内部路由分属两套信任边界；验证：双向边界用例并存——新面无 console 登录即 401（即便带内部令牌）、内部面无 `X-Internal-Token` 即 401（即便带 console 登录）
- [x] 2.3 `web/src/console/api.ts` 增加客户端函数与类型，`EntitiesPage`（或其上位页）新增只读区「标准本体 · 版本/digest/条目数/拉取于」，无快照时显示「尚未拉取过」空态而非空表；验证：`web/src/console/BenchOntologySection.test.tsx` 4 用例（有数据渲染元数据 / 空态 / 403 报因 / 其它错误带状态码）；`npx tsc --noEmit` 退出码 0；i18n zh/en `benchOntology` 键块对仗
- [x] 2.4 只读区在 ACL 受限（free tier / 无域权限）时显示可读的报因，不静默空；验证：用例断言 403 渲染 `bench-ontology-error` 且**不**渲染 `bench-ontology-empty`（ACL 受限不得伪装成「尚未拉取」）

## 3. 生产拉取按纪律打开（跨仓 fd-wire + 运维）

- [ ] 3.1 **阻塞（缺令牌明文，待裁决路径 A/B）** 先验证：对 `legal` 域做一次手动拉取（`POST /api/v1/internal/bench-ontology/legal/pull`），断言 `bench_pull_log` 新增 `ok=True` 行且 `bench_ontology_snapshots` 新增一行；验证：把两条 SQL 的返回值落盘到 `openspec/changes/add-bench-wire-seam-contract/evidence/pull-proof.md`（含执行时间与版本/digest）。**只读核查已完成**：`fd-wire` 登记存在未吊销（machine/legal）、生产已有 2026-11-06 的 legal v1 快照、令牌明文在仓库与 Secret 中均不存在——见 `evidence/prod-recon.md`
- [~] 3.2 **清单已就绪、开关仍为 false（等 3.1）** 在 `deploy/k8s/fd-wire-api.yaml` 增加 `BENCH_PULL_URL` / `BENCH_PULL_ENABLED` / `BENCH_PULL_DOMAINS` / `BENCH_PULL_INTERVAL_SECONDS` 字面值，并把 `BENCH_CONSUMER_TOKEN` 挂为 `fd-wire-env` 的 `bench_consumer_token`（`optional: true`，键未建时 pod 照常起）；验证：清单 5 项齐备、无重复 env 名（`yaml.safe_load_all` 实测 dups=[]）、`ENABLED` 值为 `"false"`——翻 true 是 3.1 通过后的单独一步
- [ ] 3.3 滚版后观察一轮 tick，断言 `bench_pull_log` 持续新增 `ok=True` 行且无 `ok=False`；验证：滚版后 ≥1 小时的 `bench_pull_log` 明细落盘到同一 evidence 文件
- [ ] 3.4 3.2/3.3 若失败（403/令牌吊销/域无发布），把 `BENCH_PULL_ENABLED` 改回 `"false"` 并在 evidence 文件记录真实原因；验证：清单回到关闭态，且 evidence 文件写明失败语义而非「已完成」

## 4. 对外口径（跨仓 fd-bench-web）

- [x] 4.1 `src/pages/index.astro` 链路三节图第三节点改为能力口径（「消费端接入能力已交付 · 生产订阅未开启」），保留机制描述与 digest 证据；验证：`grep -c "真拉落库"` 在 index.astro 为 0；PRODUCT.md 仅余一处且已限定为历史证据语境（「在 2026-11-06 联调时验证过……此后生产订阅未开启」）；新措辞「消费端接入能力已交付」「生产订阅尚未开启」两处齐备（hero + 第三节点）
- [x] 4.2 `PRODUCT.md` 的 Positioning 与 Operating Context 同步该口径，并写明改回「已上线」的两个条件（拉取足迹 + 可见读面）；验证：`PRODUCT.md` 的「口径纪律」段列明两条件（拉取足迹 + 可见读面），与 `specs/bench-wire-seam/spec.md`「已接通需要可核对的证据」一一对应
- [ ] 4.3 若第 3 组已完成（拉取在跑且有读面），则按 4.2 的两个条件判定是否直接写「已上线」；验证：判据留痕在同一提交的说明里，二选一必须显式

## 5. 验收

- [ ] 5.1 `openspec validate add-bench-wire-seam-contract --strict` 绿；验证：命令输出无 error
- [ ] 5.2 law-bench-internal 侧零回归：`uv run pytest tests/test_bench_promotion.py tests/test_bench_crosswalk*.py` 全绿；验证：命令输出 passed，无 skip 新增
- [ ] 5.3 fd-wire 侧零回归：`api/tests/test_bench_ontology_pull.py` 全绿（含既有 4.1–4.5 用例）；验证：命令输出 passed
- [ ] 5.4 跨仓对照：同一域，bench 侧发布记录的 digest 与 wire 侧读面显示的 digest 逐字相等；验证：两侧各取一次读数写入 evidence 文件，比对结果一致

## Workflow follow-up

- 合入后 `openspec sync` 把三份 delta 落进主 specs（`bench-wire-seam` 成为新能力，`bench-platform` / `wire-integration` 各自 +1）。
- `add-crosswalk-seam` 的 8.1–8.3 与本 change 的 1.1 共享同一份边界断言，收口时一并核。
- crosswalk 的发布面不在本 change：待 `add-typed-publications` 落地后另开 change，读 `bench-wire-seam` 的「唯一连接」要求作为约束。
