## 1. 存储层：域树与大库（纯增量）

- [ ] 1.1 `ensure_schema` 增 `domains.parent_id / domains.path`（含 `UNIQUE(path)`）与回填：现有 legal → `path='legal'`；验证＝在真实 cell 库副本上跑 `initDb` 后 `select key,path from domains` 返回 `legal | legal`
- [ ] 1.2 新增 `libraries / library_sources / domain_library_subscriptions` 三表（含 `UNIQUE(library_key)`、`UNIQUE(domain_id, library_id)`）；验证＝新增 `tests/test_shared_library_store.py` 建库/建源/订阅/重复 key 拒绝全绿
- [ ] 1.3 新增 `corpus_chunks`（pgvector `vector(2048)` + `(library_id, scope_path)` 索引 + `content_hash`）；验证＝迁移脚本在空库建表成功，且 `\d corpus_chunks` 含向量列与两个索引
- [ ] 1.4 `knowledge_units` 增 `derived_from JSONB` 并把 `namespace` 语义改为域 path（回填 `'default'`→`'legal'`）；验证＝`select namespace,count(*) from knowledge_units group by 1` 只剩 `legal`
- [ ] 1.5 `rubrics` 增 `domain_id NOT NULL / derived_from / fork_diff`，回填现有 2 行为 legal；验证＝`select count(*) from rubrics where domain_id is null` 为 0
- [ ] 1.6 订阅解析函数 `effective_sources(domain_path)`：沿路径向上收集、父在前子收窄、只减不加；验证＝单测覆盖「父订阅 3 源 / 子收窄到 2 / 子试图加父未订阅库被拒」三种情况

## 2. 语料与检索：切 pgvector

- [ ] 2.1 新增 `src/search/pgvector_store.py`（写块/删块/按库+子树+源过滤检索），幂等键用 `content_hash`；验证＝单测：同文档两次摄取块数不变
- [ ] 2.2 `ingest` 改为按库摄取并写 `scope_path / source_key / doc_path / chunk_seq / meta`；验证＝摄取一个测试源后每块可溯源（源/文档/块序号）
- [ ] 2.3 `search()` 增加 `domain_path` 参数并按有效订阅过滤；缺域标识的租户调用拒绝；未订阅域返回显式「未订阅语料」错误态；验证＝单测三态（有匹配/无匹配/未订阅）可区分
- [ ] 2.4 检索范围解释接口：返回「每个源来自本域订阅还是继承、被哪次收窄削掉」；验证＝单测断言解释结果与实际过滤所用集合同源（同一函数产出）
- [ ] 2.5 ES 路径降级为 fallback（不可用时日志告警而非 500），生产未配 ES 时整条链路走 pgvector；验证＝生产 `/search` 不再出现「搜索后端不可用」

## 3. 本体与评测标准域化

- [ ] 3.1 模板 `extends`：保存时校验「继承项不可删除」、实例化前校验继承后的有效词表；验证＝单测：删父项被拒 / 增子项成功且有效词表 = 父 ∪ 子
- [ ] 3.2 模板升版不传播：父模板 v2 发布后子模板与实例仍钉 v1，界面提示可升级；验证＝单测 + 模板详情页断言
- [ ] 3.3 `knowledge_units` 读取沿路径向上继承、同键本域优先；写入按域 path 落 namespace；验证＝单测：父域 1 条 + 子域同名 1 条 → 子域读到自己那条，子域无同名时读到父域那条
- [ ] 3.4 rubric 域化读写 + 引用式继承 + fork 必须写 `fork_diff`；验证＝单测：fork 未带差异被拒 / 带差异成功且 `derived_from` 指向父 rubric
- [ ] 3.5 评测运行按域解析 rubric（本域优先、同名覆盖）并记录所用 rubric 的所属域；验证＝单测：子域同名 rubric 生效，运行记录标子域

## 4. 交互：全域运营台 + 域内 8 区

- [ ] 4.1 `AREAS` 扩为 8 区（新增 `knowledge`、`eval-standards`，`bench` 收窄为 `eval-runs`），`min_role` 沿用；验证＝按角色渲染的区集合单测（annotator/expert/lead/admin 四种）
- [ ] 4.2 L0 全域运营台 `/d`：父子缩进 + 四支柱缺口矩阵 + 缺口筛选；验证＝e2e：造 3 个域（1 缺语料、1 缺 rubric）后页面标出缺口且可筛
- [ ] 4.3 「知识库」区：有效取材范围（含继承来源）+ 订阅管理 + 库健康；验证＝页面展示某子域的源清单并标明「继承自 legal」
- [ ] 4.4 「评测标准」区：本域 rubric + 继承自父域分组 + fork 入口（要求填差异）；验证＝e2e：fork 一条后出现在本域分组且带差异摘要
- [ ] 4.5 「评测运行」区：历史运行 + 结果，按域过滤；验证＝造两条不同域的运行，页面只显示本域
- [ ] 4.6 新建细分域向导：选父域 → 预览继承词表 → 勾选订阅源 → 生成缺口清单 → 提交创建；验证＝e2e：5 步走完在 L0 出现新域，缺口如实
- [ ] 4.7 批量派单（按缺口筛选后派给负责人/舰队）需二次确认，页面加载零写操作；验证＝e2e：未确认前无任务创建

## 5. 旧路径收敛与兼容

- [ ] 5.1 旧 11 条入口（法律法规/法规索引/合同模板/合同样本/条款库/评分规则/提示词/对比/仪表盘/人工审查/搜索）建 302 映射表；验证＝参数化测试遍历映射表，每条断言 302 且目标 200
- [ ] 5.2 顶栏只保留三层导航（全域/我的域/域内区），旧平铺菜单移除；验证＝e2e 断言顶栏不再出现旧菜单项
- [ ] 5.3 legal 域零回归：`/d`、`/d/legal`、六区页面、旧路径全 200/302；验证＝e2e 全量走查通过

## 6. 收口

- [ ] 6.1 `openspec validate add-domain-tree-and-shared-libraries --strict` 通过
- [ ] 6.2 全量 pytest + e2e 通过（含既有 1396 条基线不回归）
- [ ] 6.3 生产落地：镜像滚版后确认启动日志 `boot: schema ensured on database 'law_bench'`，并逐条验 5.1 的 11 条路径
- [ ] 6.4 验收报告：域树、库订阅、检索过滤、rubric 继承四件事各留一条可复核证据（SQL/页面/单测名）
