# 合同生成 API 接口文档

> 面向「在已有基础上开发合同生成 Agent」的同事。本文档覆盖 `src/web` 下
> `/api/contracts/*` 这一套 **agent-facing** 接口（即最近新增的 contract-context 路由）。
> 文档自包含，拿到这份 md 就能开工。

## 1. 这套 API 是什么

系统已经把合同生成拆成了两层：

- **底座**：模板（母版）+ 条款库（base / tagged / custom 三类）+ 标签体系 + 法律法规。
  根据 `合同类型 + 场景(scenario) + 立场(stance)` 按「custom > tagged > base」的
  逐节覆盖规则**组装**出合同正文，正文里保留 `{{slot}}` 占位符。
- **接口层**：把上述能力以 REST 暴露出来，供 Agent 调用。

`/api/contracts/*` 就是这个接口层，它的定位是 **「给 Agent 提供组装合同所需的全部上下文 +
触发组装与渲染」**。一个 Agent 只要会发 HTTP 请求，就能：

1. 查有哪些合同类型、每个类型的标签词表、slot 清单与填空说明；
2. 触发组装，拿到带 `{{slot}}` 占位符的合同正文；
3. 由 Agent（LLM）把 slot 填成具体内容；
4. 渲染成 docx / pdf，或落库持久化。

> **关键认知**：这套 API **不做 slot 填充**。它负责把条款按标签组装成结构正确的正文，
> 正文里的 `{{甲方}}` `{{价款}}` 等占位符**原样保留**。把占位符替换成真实内容，是 Agent 的
> 核心工作（接口会给出每个 slot 的 label / description / example / required，帮你填）。

## 2. 服务地址

**远端（已部署，直接用这个）**：

- Base URL：`http://23.144.68.246:30820`
- 交互式文档：`http://23.144.68.246:30820/api/docs`（Swagger UI，可直接试调）
- OpenAPI JSON：`http://23.144.68.246:30820/openapi.json`
- 健康检查：`GET http://23.144.68.246:30820/healthz`

部署在 k3s 集群 `23.144.68.246`，NodePort `30820`（容器端口 8010），由 ArgoCD 管理。
后端连的是生产 PostgreSQL（条款库 / rubric / 产物元数据都在库里），生成的 docx/pdf 产物
落 MinIO。日常对接**直接用这个远端地址**，不必本地跑。

- **无需鉴权**：这套接口没有 API Key / 限流（鉴权在另一套 async API 上，见第 11 节）。
- **HTTP 明文**：NodePort 直连，非 HTTPS。

**本地开发（可选）**：

```bash
# 仓库根目录
uv run uvicorn src.web.app:app --reload --host 127.0.0.1 --port 8010
```

本地起来后 Base URL 为 `http://127.0.0.1:8010`，需自行配置 `database_url` 指向一个
PostgreSQL，文件产物默认写到 `output/contracts/`。

## 3. 核心概念（先看这个，再看接口）

### 3.1 合同类型（contract_type）

一共 **43 种**，如 `sale`（买卖合同）、`lease`（租赁）、`employment`（劳动）、`loan`（借款）等。
调用 `GET /api/contracts` 拿全量。所有接口里的 `{contract_type}` 路径参数都用 key（英文），
不是中文名。

### 3.2 标签驱动的组装（tag-driven assembly）

合同正文是**按节（section）组装**出来的。对每一节，条款选取优先级为：

```
custom  >  tagged  >  base
```

- `base`：该类型的母版基础条款（必有，保底）。
- `tagged`：按业务场景（scenario）细分的条款，例如「农产品买卖」「生鲜乳购销」。
- `custom`：按立场（stance）定制的条款，覆盖同节的 base/tagged。

过滤维度有两个：

| 维度 | 含义 | 取值 |
|------|------|------|
| `scenario` | 业务场景（条款真正发生变异的轴） | 各类型自带词表，如 sale 下有「农产品买卖」「消费品零售」… |
| `stance` | 立场 | 固定三值：`pro_a`（偏甲方）/ `pro_b`（偏乙方）/ `balanced`（中立）|

> 还有个 `custom_clause_ids`（custom 条款 id 列表），用于精确指定用哪一组 custom 条款，
> 典型场景是「自愈循环」里临时排除某条不合适的 custom 覆盖。一般不用，留空即可。

### 3.3 规范章节（canonical sections）

组装出的合同按以下固定顺序排节（这也是一致性校验的依据）：

```
当事人 → 鉴于 → 合同标的 → 价款及支付 → 履行期限 → 权利义务 → 违约责任 → 争议解决 → 附则 → 签署信息
```

如果组装结果缺关键节，会触发 **coherence gate（一致性闸门）** 失败，接口返回 `422`。

### 3.4 Slot（占位符）

模板正文里形如 `{{party_a}}` `{{subject}}` 的就是 slot。每个 slot 都有一份填空说明：

```json
{
  "name": "party_a",
  "label": "甲方",
  "description": "买方（采购方）的法定全称",
  "example": "北京 XX 商贸有限公司",
  "required": true,
  "source": "registry"   // registry | ontology | uncovered
}
```

`source` 表示这条说明的来源：

- `registry`：该类型手写的 slot 清单里就有（最准）。
- `ontology`：清单里没有，但通过 slot 本体（ontology）推导出来。例如 `seller_address`
  推导到 `address` 概念，复用其说明。
- `uncovered`：两边都没有 —— **这是数据缺口**，Agent 填这种 slot 时只能靠正文上下文猜，
  建议反馈给数据维护者补录。

## 4. 接口总览

| 方法 | 路径 | 用途 | Agent 何时用 |
|------|------|------|--------------|
| GET | `/api/contracts` | 列出全部合同类型 | 入口，挑类型 |
| GET | `/api/contracts/{type}` | 一次性拿该类型的**全套上下文**（bundle） | **首选**，省多次请求 |
| GET | `/api/contracts/{type}/slots` | slot 清单 + 本体覆盖 | 只想看占位符时 |
| GET | `/api/contracts/{type}/laws` | 法律法规引用 + 豆包/DeepSeek 调研原文 | 需要法条依据时 |
| GET | `/api/contracts/{type}/tags` | 该类型的标签词表 | 确认合法 scenario/stance |
| GET | `/api/contracts/{type}/clauses` | 条款目录（可过滤分页） | 想看具体条款内容时 |
| POST | `/api/contracts/{type}/generate` | 组装 + 渲染（默认 docx） | **核心：生成合同** |
| POST | `/api/contracts/{type}/generate-stored` | 组装 + 渲染 + 上传 MinIO + 落库 | 要持久化产物时 |
| GET | `/api/contracts/artifacts` | 列出已落库的产物元数据 | 查历史产物 |
| GET | `/api/contracts/artifacts/{id}` | 单个产物详情（含正文） | 取某次产物正文 |
| GET | `/api/contracts/artifacts/{id}/download` | 下载已落库的 docx/pdf | 取文件流 |
| GET | `/api/contracts/{type}/files/{filename}` | 取本次生成的临时文件 | `generate` 返回的 docx_url 指向它（内部用）|

> 路由顺序注意：`/artifacts` 这类静态路径在 `{contract_type}` 之前注册，所以
> `GET /api/contracts/artifacts` 不会被当成 `contract_type="artifacts"`。

## 5. 接口详解

### 5.1 `GET /api/contracts` — 列出合同类型

```bash
curl http://23.144.68.246:30820/api/contracts
```

响应（43 项，仅示两条）：

```json
[
  {"key": "sale", "zh": "买卖合同"},
  {"key": "lease", "zh": "租赁合同"}
]
```

### 5.2 `GET /api/contracts/{type}` — 全套上下文 bundle ⭐

**一个请求拿全**：模板正文 + slots + slot 填空说明 + 法律法规引用 + 标签词表 + 规范章节顺序
+ 条款可用量统计 + 该类型的 rubric / prompts 指针。Agent 冷启动时调这一个就够。

```bash
curl http://23.144.68.246:30820/api/contracts/sale
```

响应：

```json
{
  "type": "sale",
  "zh_name": "买卖合同",
  "template": {
    "body": "## 当事人\n\n甲方：{{party_a}}\n乙方：{{party_b}}\n...",
    "slots": ["party_a", "party_b", "subject", "..."]
  },
  "slot_instructions": [
    {"name": "party_a", "label": "甲方", "description": "...", "example": "...", "required": true, "source": "registry"}
  ],
  "laws": {"refs": [{"name": "中华人民共和国民法典", "...": "..."}]},
  "tags": {
    "stance": ["pro_a", "pro_b", "balanced"],
    "scenario": ["农产品买卖", "生鲜乳购销", "..."],
    "strength": [...],
    "risk": [...],
    "mandatory": [...]
  },
  "sections": ["当事人","鉴于","合同标的","价款及支付","履行期限","权利义务","违约责任","争议解决","附则","签署信息"],
  "clauses": {"base": 10, "tagged": 24, "custom": 6},
  "rubric": {"name": "contract_sale_v3"},
  "prompts": [{"name": "sale_draft", "purpose": "draft"}]
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `template.body` | 母版模板正文，含 `{{slot}}` 占位符 |
| `template.slots` | 模板里出现的全部 slot 名（去重保序） |
| `slot_instructions` | 每个 slot 的填空说明 + `source` 覆盖情况 |
| `laws.refs` | 该类型相关的法律法规结构化引用（来自内置答案库） |
| `tags` | 标签词表：`dim -> [合法值]`，含通用维度 + 该类型专属维度 |
| `sections` | 规范章节顺序（见 3.3） |
| `clauses` | base / tagged / custom 三类条款的可用条数 |
| `rubric` | 该类型最新版本的评测 rubric 名（`contract_<type>_v<N>` 取最大 N），无则 `null` |
| `prompts` | 该类型已登记的生成 prompt 指针（仅 name + purpose，不含 content） |

> `rubric` 选「最高 v<N>」而非字母序最后，所以 `v10` 会胜过 `v3`。

### 5.3 `GET /api/contracts/{type}/slots` — slot 清单

等价于 bundle 里的 `slot_instructions`，单独取更轻量。

```bash
curl http://23.144.68.246:30820/api/contracts/sale/slots
```

响应：`[{name, label, description, example, required, source}, ...]`，覆盖模板里的每一个 slot。

### 5.4 `GET /api/contracts/{type}/laws` — 法律法规

```bash
curl http://23.144.68.246:30820/api/contracts/sale/laws
```

响应：

```json
{
  "refs": [{"name": "中华人民共和国民法典", "category": "...", "...": "..."}],
  "survey_md": {
    "doubao": "# 买卖合同法律法规\n\n来源：豆包\n\n《中华人民共和国民法典》...",
    "deepseek": "# 买卖合同法律法规\n\n来源：DeepSeek\n\n..."
  }
}
```

- `refs`：结构化法条引用列表。
- `survey_md`：豆包 / DeepSeek 两个来源的**完整调研 markdown 原文**（可能为 `null`）。
  Agent 要写「签约提示」「合规建议」时，这是最权威的素材。

### 5.5 `GET /api/contracts/{type}/tags` — 标签词表

```bash
curl http://23.144.68.246:30820/api/contracts/sale/tags
```

响应：`{dim: [合法值]}`。调用 `generate` 前，用这个确认你传的 `scenario` / `stance` 是否合法。
传不合法的值会在组装阶段被当成无匹配（退化到 base），不会报错，所以**最好先查词表**。

### 5.6 `GET /api/contracts/{type}/clauses` — 条款目录

支持按 `scenario` / `stance` / `source` 过滤 + 分页。

```bash
curl 'http://23.144.68.246:30820/api/contracts/sale/clauses?scenario=农产品买卖&source=tagged&limit=20&offset=0'
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `scenario` | 无 | 按业务场景过滤 |
| `stance` | 无 | 按立场过滤 |
| `source` | 无 | `base` / `tagged` / `custom` |
| `limit` | 50 | 最大 200（超出自动夹到 200） |
| `offset` | 0 | 分页偏移 |

响应：

```json
{
  "clauses": [
    {
      "id": 2,
      "section": "合同标的",
      "source": "tagged",
      "manual": false,
      "tags": {"source": "tagged", "scenario": "农产品买卖"},
      "body": "标的：{{subject}}",
      "slot_instructions": [{"name": "subject", "label": "标的", "description": "...", "example": "...", "required": true}],
      "law_refs": []
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### 5.7 `POST /api/contracts/{type}/generate` — 组装 + 渲染 ⭐⭐

**核心生成接口**。请求体：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `scenario` | string? | null | 业务场景，留空则只用 base |
| `stance` | string? | null | 立场 `pro_a` / `pro_b` / `balanced` |
| `custom_clause_ids` | int[]? | null | 指定 custom 条款 id 列表（一般不用） |
| `format` | enum | `docx` | `docx` / `pdf` / `both` / `markdown` |

```bash
# 最快路径：只拿正文文本，不落地文件
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate \
  -H 'Content-Type: application/json' \
  -d '{"scenario": "农产品买卖", "stance": "balanced", "format": "markdown"}'
```

响应：

```json
{
  "body_text": "## 当事人\n\n甲方：{{party_a}}\n乙方：{{party_b}}\n## 合同标的\n\n标的：{{subject}}\n...",
  "slots": ["party_a", "party_b", "subject"],
  "instructions": [{"name": "party_a", "label": "甲方", "description": "...", "example": "...", "required": true}],
  "law_refs": [{"name": "中华人民共和国民法典", "...": "..."}],
  "diagnostics": {"heuristic_sections": ["权利义务"]},
  "docx_url": null,
  "pdf_url": null
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `body_text` | **组装后的合同正文**，含 `{{slot}}` 占位符。Agent 主要拿这个去填空 |
| `slots` | 本次正文里实际出现的 slot 列表（去重保序） |
| `instructions` | 对应 slot 的填空说明（含 label/description/example/required） |
| `law_refs` | 本次组装涉及条款引用的法律法规 |
| `diagnostics.heuristic_sections` | 由「同源内部 tiebreak」选定的章节（非完全精确匹配），可用来判断哪些节是猜的 |
| `docx_url` / `pdf_url` | 生成文件的下载 URL（`format=markdown` 时为 `null`）|

`docx_url` 形如 `/api/contracts/sale/files/sale.docx`，带上 base URL 直接 GET 就能下文件
（见 5.12）。

**错误**：

- `404`：`contract_type` 不存在。
- `422`：`format` 取值非法；或组装结果未通过一致性闸门（缺关键章节），`detail` 里会写明缺哪些节。
- `500`：其他内部错误。

### 5.8 `POST /api/contracts/{type}/generate-stored` — 组装 + 渲染 + 落库

跟 `generate` 同一个请求体，区别是产物**上传 MinIO 并在 `contract_artifacts` 表里记一行**，
按 `md5(body_text)` 内容寻址去重。

两种模式（按请求体里有没有 tag 自动区分）：

**A. 指定 tag（生成单个变体）**：传了 `scenario` / `stance` / `custom_clause_ids` 任一。

```bash
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate-stored \
  -H 'Content-Type: application/json' \
  -d '{"scenario": "农产品买卖", "stance": "balanced", "format": "both"}'
```

响应：

```json
{
  "artifact_id": 42,
  "docx_url": "/api/contracts/artifacts/42/download?format=docx",
  "pdf_url": "/api/contracts/artifacts/42/download?format=pdf",
  "body_text": "...",
  "slots": ["party_a", "party_b"],
  "reused": false
}
```

- `reused: true` 表示内容已存在、复用了既有产物；只补齐缺失的格式。
- 一致性闸门失败 → `422`。

**B. 不传 tag（批量生成该类型的全部组合）**：会生成 **scenario × stance × base 的全组合**
并逐个落库。

```bash
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate-stored \
  -H 'Content-Type: application/json' \
  -d '{"format": "docx"}'
```

响应（汇总，**单组合失败不会 422**，而是记到 `failures`）：

```json
{
  "contract_type": "sale",
  "format": "docx",
  "artifacts": [
    {"artifact_id": 1, "scenario": null, "stance": null, "docx_url": "...", "pdf_url": null, "reused": false},
    {"artifact_id": 2, "scenario": "农产品买卖", "stance": null, "docx_url": "...", "pdf_url": null, "reused": false}
  ],
  "count": 12,
  "new": 10,
  "reused": 2,
  "failed": 0,
  "failures": []
}
```

### 5.9 `GET /api/contracts/artifacts` — 列出已落库产物

```bash
curl 'http://23.144.68.246:30820/api/contracts/artifacts?contract_type=sale'
```

响应（**不含 `body_text`**，按 id 倒序）：

```json
[
  {
    "id": 42,
    "contract_type": "sale",
    "scenario": "农产品买卖",
    "stance": "balanced",
    "custom_clause_ids": null,
    "body_hash": "5d41402abc4b2a76b9719d911017c592",
    "slots": ["party_a", "party_b"],
    "docx_key": "sale/42.docx",
    "pdf_key": "sale/42.pdf",
    "minio_bucket": "law-bench-contracts",
    "created_at": "2026-08-03T10:00:00Z",
    "updated_at": "2026-08-03T10:00:00Z"
  }
]
```

`contract_type` 可选；不传则返回全部类型。

### 5.10 `GET /api/contracts/artifacts/{id}` — 产物详情

```bash
curl http://23.144.68.246:30820/api/contracts/artifacts/42
```

返回完整行（**含 `body_text`**）。id 不存在 → `404`。

### 5.11 `GET /api/contracts/artifacts/{id}/download` — 下载已落库文件

```bash
curl -OJ 'http://23.144.68.246:30820/api/contracts/artifacts/42/download?format=docx'
```

- `format` 仅支持 `docx` / `pdf`，传别的 → `400`。
- 产物或对应格式不存在 → `404`。
- 返回流式文件，带 `Content-Disposition: attachment; filename="..."`。

### 5.12 `GET /api/contracts/{type}/files/{filename}` — 取本次生成的临时文件

`generate`（非 stored）返回的 `docx_url` / `pdf_url` 指向这里。**内部接口，不在 OpenAPI 里**。

```bash
curl -OJ http://23.144.68.246:30820/api/contracts/sale/files/sale.docx
```

- 路径穿越安全：文件名含 `..` / `/` / `\` 一律 `404`。
- 文件不存在 → `404`。

## 6. 请求体 Schema（`generate` / `generate-stored` 共用）

```python
class GenerateRequest(BaseModel):
    scenario: str | None = None
    stance: str | None = None
    custom_clause_ids: list[int] | None = None
    format: Literal["docx", "pdf", "both", "markdown"] = "docx"
```

`format` 说明：

| format | body_text | docx | pdf | 适用 |
|--------|-----------|------|-----|------|
| `markdown` | ✅ | ❌ | ❌ | **Agent 推荐**：最快，纯文本，不落地 |
| `docx` | ✅ | ✅ | ❌ | 要交付 Word 文档 |
| `pdf` | ✅ | ❌ | ✅ | 要交付 PDF |
| `both` | ✅ | ✅ | ✅ | 两种都要 |

> 无论哪种 `format`，`body_text` 永远返回。

## 7. 错误处理

统一的错误响应体：`{"error": "<message>"}`（部分 422 由 FastAPI 校验产生，体为标准 detail）。

| 状态码 | 触发条件 | Agent 处理建议 |
|--------|----------|----------------|
| `404` | `contract_type` 不存在 / artifact id 不存在 / 文件不存在 | 先 `GET /api/contracts` 确认类型 |
| `400` | `generate-stored` 下载 `format` 非 docx/pdf | 改正 format |
| `422` | `format` 取值非法（pydantic Literal 校验）；或组装未通过一致性闸门 | 看返回 `detail`：若是闸门失败，说明该 scenario+stance 组合缺关键章节，换个组合或补条款 |
| `500` | 其他内部错误（DB / 渲染失败等） | 重试；持续失败联系底座维护者 |

一致性闸门失败示例：

```json
{"detail": "missing canonical sections: ['价款及支付']"}
```

## 8. Agent 开发指南（重点）

一个合同生成 Agent 的推荐工作流：

```
① 选类型      GET /api/contracts                       → 拿到 [{key, zh}]
② 拿上下文    GET /api/contracts/{type}                → bundle（模板/slots/词表/法条）
③ 确认标签    从 bundle.tags 里挑合法的 scenario+stance
④ 组装正文    POST /api/contracts/{type}/generate      → format=markdown，拿 body_text + slots + instructions
⑤ 填空        （Agent/LLM 工作）用 instructions 把 body_text 里的 {{slot}} 替换成真实内容
              参考：label/description/example/required；uncovered 的 slot 靠上下文猜
⑥ 校验        检查 body_text 里还有没有残留 {{...}}；确认规范章节齐全
⑦ 交付        POST /api/contracts/{type}/generate      → format=docx/pdf，拿 docx_url 下文件
              （或 generate-stored 落库，拿 artifact_id + 持久化下载链接）
```

**填空（slot filling）是 Agent 的核心增值点**，几个要点：

- `instructions` 里 `required=true` 的 slot 必须填，缺失会导致合同不完整。
- `source=uncovered` 的 slot 没有标准说明，填的时候要谨慎，最好让用户确认。
- 同一个 slot 可能在正文多处出现，替换时用全局字符串替换，不要只替换第一个。
- `law_refs` 和 `survey_md` 可以喂给 LLM，让它生成「签约提示」「风险提示」等附加段落。
- 如果用户给了立场倾向（「我是买方，帮我偏着我」），`stance=pro_a`；中立则 `balanced`。

**性能建议**：

- 冷启动用 bundle（一次拿全），后续生成只需 `generate`。
- 只要正文文本就传 `format=markdown`，省掉文件 I/O 和 LibreOffice 转 PDF 的耗时。
- 批量生成同一类型的全组合，用 `generate-stored`（不传 tag），内部按内容去重。

## 9. 标签体系速查

- 通用维度（所有类型都有）：`stance` / `strength` / `risk` / `mandatory`。
  - `stance`：`pro_a` / `pro_b` / `balanced`
- 类型专属维度：每个类型可能有自己的 `scenario` 词表（业务场景才是条款真正变异的轴）。
- `region` / `province` 已废弃 —— 不要按省份分合同，按 `scenario` 分。

查某类型的完整词表：`GET /api/contracts/{type}/tags`。

## 10. curl 示例合集

```bash
# 0. 健康检查
curl http://23.144.68.246:30820/healthz

# 1. 列合同类型
curl http://23.144.68.246:30820/api/contracts

# 2. 拿 sale 的全套上下文
curl http://23.144.68.246:30820/api/contracts/sale

# 3. 查 sale 的标签词表
curl http://23.144.68.246:30820/api/contracts/sale/tags

# 4. 查 sale 的 slot 清单
curl http://23.144.68.246:30820/api/contracts/sale/slots

# 5. 查 sale「农产品买卖」场景的 tagged 条款
curl 'http://23.144.68.246:30820/api/contracts/sale/clauses?scenario=农产品买卖&source=tagged'

# 6. 组装 sale 合同（只拿正文，不落地）
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"农产品买卖","stance":"balanced","format":"markdown"}'

# 7. 组装并生成 docx
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"农产品买卖","stance":"pro_a","format":"docx"}'
# → 用返回的 docx_url 下载
curl -OJ http://23.144.68.246:30820/api/contracts/sale/files/sale.docx

# 8. 组装 + 落库（both）
curl -X POST http://23.144.68.246:30820/api/contracts/sale/generate-stored \
  -H 'Content-Type: application/json' \
  -d '{"scenario":"农产品买卖","stance":"balanced","format":"both"}'

# 9. 列已落库产物
curl 'http://23.144.68.246:30820/api/contracts/artifacts?contract_type=sale'

# 10. 下载已落库产物的 pdf
curl -OJ 'http://23.144.68.246:30820/api/contracts/artifacts/42/download?format=pdf'
```

## 11. 相关接口（不是本文档重点，但你需要知道）

仓库里其实有**两套**对外接口，别搞混：

| 接口 | 位置 | 端口 | 定位 | 本文是否覆盖 |
|------|------|------|------|--------------|
| contract-context API | `src/web/routes/contract_context.py` | 8010 | **本文档**。agent-facing，上下文最全，无鉴权 | ✅ |
| async 生成 API | `fd-coding-law-bench-mcp/src/.../api/` | 8000 | 生产级：async + API Key + 限流 + CORS + batch | ❌（已有独立文档） |

如果你要做**对外部署**（鉴权、限流、跨域），用 async 那套，文档在
`fd-coding-law-bench-mcp/docs/api-reference.md` 和 `api-server.md`，跑法：

```bash
uvicorn fd_coding_law_bench_mcp.api.main:app --port 8000
```

它提供 `POST /contracts/content`、`POST /contracts/batch`、`GET /contracts/types`、
`GET /tags/combinations/{type}`、`POST /tags/validate` 等，功能子集与本文档重叠但更偏
「纯生成」，**上下文粒度不如本文档**（没有 slots/laws/clauses catalog/bundle）。
两套可以并用：用本文档拿上下文 + 填空，用 async 那套做对外生成网关。

另外 `src/web/routes/api.py` 下还有一套 `/api/rubrics`、`/api/prompts`、`/api/compare`
**评测管理**接口（rubric / criterion / prompt 的 CRUD + prompt 对比评测），与「生成」关系不大，
属于评测侧，需要时再看 `http://23.144.68.246:30820/api/docs`。

## 12. 附：规范章节顺序

```
当事人
鉴于
合同标的
价款及支付
履行期限
权利义务
违约责任
争议解决
附则
签署信息
```

## 13. 常见坑

1. **slot 不会被接口填掉**：`body_text` 里一定带着 `{{slot}}`，得 Agent 自己填。
2. **非法 scenario 不报错**：传了词表里没有的 scenario，组装时当成无 tagged 匹配，退化到 base。
   生成前先用 `/tags` 确认。
3. **`format=markdown` 时 `docx_url`/`pdf_url` 为 `null`**：别对着 null 发下载请求。
4. **`generate` 的文件是临时的**：`/files/{filename}` 指向 `output/contracts/`，进程或目录清理后可能丢失。
   要持久化用 `generate-stored`，产物在 MinIO + DB 里。
5. **`generate-stored` 不传 tag = 全组合批量**：别误以为「不传 tag = 生成 base 一份」，
   它会生成 scenario×stance×base 的**全部**组合。
6. **`rubric` 字段可能为 `null`**：该类型还没登记 rubric 时。不影响生成，只影响后续评测。

---

*接口源码：`src/web/routes/contract_context.py`。所有路由都是对 `src.contracts` /
`src.clauses` / `src.eval` 既有服务函数的薄封装，没有独立业务逻辑，出问题查对应服务层即可。
OpenAPI 实时镜像：`http://23.144.68.246:30820/api/docs`。*
