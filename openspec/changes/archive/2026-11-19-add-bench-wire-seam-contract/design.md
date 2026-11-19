# Design

## Context

动机见 `proposal.md` — Why；要求见 `specs/`。这里只列塑造方案的既有事实（均经盘上核实，2026-11-19）：

- **发布面**：`src/bench/distribution.py::publish_domain()` 只投影 `entity_types` / `relationship_kinds` 两个词表（`build_manifest` 逐词表 `authoring_list_units`），digest = content-only sha256。已发出且被消费者持有的 digest：`legal v2 = 5897354d`、`legal v1 = 3586552a`。任何改动这六个文件或 manifest 形状的做法都会作废已发出的账。
- **crosswalk 已落地但不在发布面**：`src/bench/crosswalk.py` 三种关系闭集 + `authoring_create_crosswalk(vocab_key="crosswalk")` 已通；`quality.py::crosswalk_coverage` / `crosswalk_gaps` 与 `dispatch.GAP_ROUTE` 三个缺口路由已接。`grep crosswalk src/bench/distribution.py` = **0 命中**——它进不了 manifest，因为它不是模板词表里的实体类型。
- **wire 侧消费端 13/13 已完成**：`api/fd_wire_api/bench_pull/`（client/store/projection/routes/scheduler）+ 迁移 0052 两表（`bench_ontology_snapshots` UNIQUE(domain_key,digest)、`bench_pull_log` append-only）。URL 写死 `{base}/api/v1/distribution/{domain}/ontology`，无 kind 参数。
- **wire 侧读面缺口是结构性的**：`app.py:388` 挂的 router 只有 `dependencies=[Depends(_require_internal)]`，浏览器拿不到 `X-Internal-Token`；`web/src/console/api.ts`、`i18n/zh.ts`、MCP 工具面对 `bench-ontology` **零引用**。拉到的快照今天只对运营脚本可见。
- **生产拉取是关的**：`deploy/k8s/fd-wire-api.yaml` 与 `fd-infra-deploy/` 对 `BENCH_PULL_*` / `BENCH_CONSUMER_TOKEN` 零命中；`deploy/README.md` 只有配置说明。
- **bench 侧域只有两个**：`legal`（`scripts/register_legal_domain.py`）与 `gov`（`scripts/publish_gov_template_v2.py`）。磁盘上无任何 `wire` 域注册脚本；`namespace='wire'` 只出现在测试里。
- **wire 自己的本体版本化**（0019/0049）：`ontology_events` + `ontology_snapshots` + diff/回滚，是本地层的自有能力，本变更零改动。
- **公开面话术**：`fd-bench-web/src/pages/index.astro` 第三节点写「真拉落库幂等、投影可查」，`PRODUCT.md` 定位段同口径。

## Goals / Non-Goals

**Goals:**

- 把「两层各自权威 + 唯一连接 crosswalk」写成规格，使后续任何接入都无从按「持续镜像」理解。
- 让已有的、已交付的拉取管道**不再是死胡同**：拉下来的东西有登录态读面，开关可按纪律打开。
- 使对外每一句「已接通」都可被库里的足迹核对。

**Non-Goals:**

- 不做 crosswalk 的发布面（`get_asset_publication` / 按种类拉取）——那归 `add-typed-publications`，本变更只负责在规格里钉住「crosswalk 是唯一连接」，不实现它的分发。
- 不给 bench 建 `wire` 域，也不灌真实 crosswalk——那需要 `add-layered-ontology-templates` 收口后的 `enterprise-base` 实例，本变更只用现有 `legal` 域验证管道。
- 不动 wire 的 `entities` 表、本地版本化、console 编辑面。回写能力保持现状（已实现、未常驻部署）。
- 不改 `publish_domain()` 的 manifest 形状或任何已发布 digest。

## Decisions

### D1：规格先行，代码只改「让已有东西可用」

**为什么**：这条缝的真正缺陷是**没有一句可判定的话**，而两侧代码都已各写了 80%。加新代码只会造出第三条半截连接。因此本变更的代码面压到最小：一个只读路由、一个前端只读区、两个 env 字面值、两处文案。

**替代方案（否决）**：在 bench 侧为 wire 建一个「wire 域」并让 crosswalk 随本体发布一起发出去。理由是「一条管道更简单」——但 crosswalk 不是实体类型，塞进 `entities` 数组会污染实体计数与 digest 语义（manifest 的 `kind` 字段会多出一个非模板词表值），而 `add-typed-publications` 已经为「非本体资产独立发布」设计好了种类注册。走那里是复用，走本体是篡改。

### D2：`sync_graph` 收窄为一次性，但代码零改动

**为什么**：`promotion.sync_graph` 的实现是「给定 fetch_fn，幂等 upsert」——它本身没有任何定时语义。让它变成「持续镜像」的是**部署语境**（wire-connector 被当成常驻同步），不是代码。因此本变更改的是规格与 README 的措辞，不动函数。

**代价**：没有机械闸能阻止未来有人给它加一个 cron。缓解：`bench-wire-seam` 的「seed 导入是一次性的」把判据写成**依赖关系**（知验台是否依赖 wire 持续变化），而不是「有没有定时器」——后者可以被绕过，前者不能。

### D3：快照读面用 console 鉴权的新路由，不复用内部端点

**为什么不给现有内部路由加一个「登录也可以」的分支**：那会让一个 `X-Internal-Token` 的全域读面在浏览器里也成立，等于把「平台级数据、仅运营面可读」的设计（design D2，写在 0052 迁移与 routes docstring 里）悄悄放宽。新路由显式只读、只返回「版本 / digest / 条目数 / 拉取于 / 域清单」这类**元数据**，**不返回快照 body**——正文是大块 JSONB，前端展示它没有意义，而它一旦可读就等于把共享层内容免费复制进浏览器。

**替代方案（否决）**：直接把内部路由挂到 console。理由是一次改动最小——但它把两套信任边界合并成一套，而这正是这条缝过去四年反复踩的坑。

### D4：先验后开，开关不进「默认开」

`BENCH_PULL_ENABLED` 进清单时取 `"true"`，但**在同一提交之前**必须先有一次 `pull_and_store` 真跑成功并留下 `bench_pull_log` 行。若令牌已吊销，打开后的表现是每轮 403 进日志——失败可见（`pull_and_store` 收口已记 `ok=False`），不是静默失败。把「先验后开」写成任务的前置条件，而不是写成代码里的守卫，因为生产验证是一次性的运维动作，守卫会变成永久的第 N 个 if。

### D5：公开面改能力口径，不改叙事结构

`index.astro` 的链路三节图（沉淀 → 发布 → 消费）结构保留——它描述的是**机制已存在**，这是真的。只改第三节点里那句「真拉落库幂等、投影可查」的时态，并在同处标注「生产订阅未开启」。改回已上线口径的条件写在 `bench-wire-seam` 的「已接通需要可核对的证据」里：拉取足迹 + 可见读面**两者齐备**。

**替代方案（否决）**：整节删掉。理由是「不准确的话不如不说」——但那条链本身是可核对的（digest 在、端点代码在、拉取记录在历史里），删掉会让人以为能力不存在。诚实的最小单位是**加限定词**，不是删句子。

## Risks / Trade-offs

- [打开生产拉取是唯一有外部副作用的动作] → 前置一次真跑验证；失败已经会被 `bench_pull_log` 如实记录，所以最坏情况是可见的 403 日志，不是静默错误。
- [新只读路由扩大了 wire 的登录用户可见面] → 只返回元数据（版本/digest/计数/时间），不返回快照正文；沿用 console 既有的客户域隔离与鉴权，不新增凭据类型。
- [规格收窄后，未来有人仍想要「准实时同步」] → 那时应当新开一个 change 并显式推翻 `bench-wire-seam`，而不是在 `wire-integration` 里悄悄加一个定时器。这正是把它写成能力（而非一句注释）的意义。
- [公开面措辞改动会动到 already-shipped 的 bench 站] → 一次文案改动，走既有构建链；不涉数据、不涉路由，回滚就是 revert 一个提交。
- [`crosswalk` 仍然发不出去，这条缝的「连接」侧因此在生产上仍是空的] → 如实承认这是本变更的边界：本变更让**已有的本体管道**活了；crosswalk 的跨层价值要等 `add-typed-publications`。proposal 已把它列在「明确不做」。

## Migration Plan

1. 规格落地（本 change 的 specs 合入主 specs），零运行时影响。
2. wire 侧新只读路由 + 前端只读区上产；此时读面仍显示「无快照」（生产从未成功拉过，或仅有 11-06 历史行）。
3. 在 wire 的运维终端做一次手动拉取验证：`POST /api/v1/internal/bench-ontology/{domain}/pull` → 断言 `bench_pull_log` 新增 `ok=True` 行、`bench_ontology_snapshots` 新增一行。
4. 同一提交内打开 `BENCH_PULL_ENABLED="true"` + 挂 `BENCH_CONSUMER_TOKEN` secretKeyRef；滚版后观察一轮 tick（缺省 3600s）。
5. 公开面文案同批改能力口径。

**回滚**：4 的回滚是把 `BENCH_PULL_ENABLED` 改回 `"false"`（缺省零行为变化，代码里已有此语义）；2、3 的回滚是删路由与前端区，表与数据保留（append-only，不删）。5 是 `git revert`。

## Open Questions

- wire 生产库里是否还留着 2026-11-06 那条 legal v1 快照行（需要 SSH 隧道进 xinru 才能查）。这决定第 3 步的验证是「首次成功」还是「再次成功」——两种都通过，只是证据措辞不同，不影响任何规格或任务分解。
- 是否已有手工创建的 `wire` 域（磁盘上的注册脚本里没有，但生产库可能有人手工建过）。若存在，只影响公开面文案里能否提「已有一个 wire 域」，不影响本变更的任一步骤。
