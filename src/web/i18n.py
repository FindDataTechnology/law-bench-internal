"""Multi-locale (zh/en) translation source for the evaluation-rules web UI.

This is the single source of truth for every UI string the web app renders, in
three places:

1. Jinja templates - ``{{ t.nav.rubrics }}`` (nested dict attribute access).
2. Python routes - flash messages emitted as keys; ``translate(t, key, **fmt)``
   resolves and formats at generation for dynamic content.
3. Client JS - ``base.html`` bootstraps ``window.__LOCALE__ = {{ t|tojson }}``
   and ``static/app.js`` reads the same nested object.

``resolve_locale`` picks the active locale per request as
``?lang`` ▶ ``lang`` cookie ▶ ``Accept-Language`` ▶ ``DEFAULT`` (``zh``).
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request

SUPPORTED: tuple[str, ...] = ("zh", "en")
DEFAULT = "zh"

# Locale -> nested catalog. The zh and en catalogs MUST expose identical key
# sets (asserted by tests/test_i18n.py). Values may contain {placeholder} tokens
# for interpolation; unknown placeholders are left untouched by str.format when
# called with the matching kwargs.
LOCALES: dict[str, dict[str, Any]] = {
    "zh": {
        "nav": {
            "brand": "评估规则管理器",
            "rubrics": "评分规则",
            "prompts": "提示词",
            "compare": "对比",
            "new_local_rubric": "+ 新建本地规则",
            "re_extract_harbor": "↻ 重新提取 harbor",
            "re_extract_confirm": "重新运行 harbor 提取？本地规则将保留。",
        },
        "switch": {"en": "EN", "zh": "中文"},
        "btn": {
            "new_prompt": "+ 新建提示词",
            "new_compare": "+ 新建对比",
        },
        "h1": {
            "evaluation_rubrics": "评估规则",
            "generation_prompts": "生成提示词",
            "prompt_compares": "提示词对比",
            "compare_label": "对比",
            "create_local_rubric": "创建本地规则",
            "edit_rubric": "编辑规则",
            "create_prompt": "创建提示词",
            "edit_prompt": "编辑提示词",
            "new_compare": "新建提示词对比",
            "criteria": "评分项",
            "content": "内容",
            "initial_criteria": "初始评分项",
            "add_criterion": "添加评分项",
        },
        "col": {
            "num": "#",
            "name": "名称",
            "context": "上下文",
            "source": "来源",
            "source_path": "来源路径",
            "criteria": "评分项",
            "contract_type": "合同类型",
            "purpose": "用途",
            "type": "类型",
            "mode": "模式",
            "n": "N",
            "created": "创建时间",
            "label": "标签",
            "rubric": "规则",
        },
        "form": {
            "name": "名称",
            "context": "上下文",
            "description": "描述",
            "contract_type": "合同类型",
            "purpose": "用途",
            "prompt_type": "提示词类型",
            "content": "内容",
            "task": "任务",
            "rubric": "规则",
            "mode": "模式",
            "drafts_per_prompt": "每个提示词的草稿数 (N)",
            "prompts": "提示词",
            "label": "标签",
            "guidance": "判定指引（通过条件 … / 不通过条件 …）",
            "unique_among_local": "（在本地规则中唯一）",
            "unique_among_prompts": "（在提示词中唯一）",
            "prompt_type_hint": "（变体/谱系标签，如 baseline / experimental）",
            "content_hint": "（提示词正文）",
            "task_hint": "（起草需求）",
            "drafts_hint": "N=1 显示通过/不通过；N>1 显示每项通过率 (k/N)。",
            "prompts_hint": "（选择 2 个或以上）",
            "label_hint": "（可选）",
            "optional": "（可选）",
            "create_rubric": "创建规则",
            "save_changes": "保存修改",
            "create_prompt_btn": "创建提示词",
            "run_compare": "运行对比",
            "cancel": "取消",
            "add_criterion_row": "+ 添加评分项行",
        },
        "hint": {
            "rubrics_list": 'JSON 数据见 <code>/api/rubrics</code>（参见 <code>/api/docs</code>）。Harbor 规则为只读，可用「重新提取 harbor」刷新。',
            "prompts_list": 'JSON 数据见 <code>/api/prompts</code>（参见 <code>/api/docs</code>）。提示词为本地编写，可完全编辑。',
            "compare_list": 'JSON 数据见 <code>/api/compare</code>。对比会使用每个所选提示词起草合同，并按规则评判每份草案。',
            "compare_form": "固定条件（合同类型 + 规则 + 任务），仅改变提示词。每个所选提示词起草一份合同（仅起草器），每份草案按规则评判。结果分组后镜像到你的浏览器。",
            "seed_criteria": "现在为规则预置评分项，或稍后从规则页添加。",
            "no_prompts_compare": '暂无提示词。请新建或运行 <code>scripts/seed_contract_prompts.py</code>。',
        },
        "empty": {
            "rubrics": "暂无评分规则。请新建本地规则或重新提取 harbor。",
            "prompts": '暂无提示词。请新建或运行 <code>scripts/seed_contract_prompts.py</code>。',
            "compares": "暂无对比。请从",
        },
        "badge": {
            "local": "本地",
        },
        "detail": {
            "back_to_rubrics": "← 返回规则列表",
            "back_to_prompts": "← 返回提示词列表",
            "back_to_compares": "← 返回对比列表",
            "edit_rubric": "编辑规则",
            "edit_prompt": "编辑提示词",
            "delete_rubric": "删除规则",
            "delete_prompt": "删除提示词",
            "delete_rubric_confirm": "删除规则「{name}」及其全部 {count} 项评分项？",
            "delete_prompt_confirm": "删除提示词「{name}」？",
            "delete_criterion_confirm": "删除评分项「{name}」？",
            "readonly_note": "这是只读的 harbor 参考规则（来源 <code>{source}</code>）。请通过刷新来源来编辑评分项——使用「重新提取 harbor」。",
            "description_label": "描述：",
            "guidance_label": "判定指引：",
            "criterion_desc_placeholder": "检查内容",
            "save_criterion": "保存评分项",
            "add_criterion": "添加评分项",
            "edit_btn": "✎ 编辑",
            "close": "关闭",
            "no_criteria": "该规则暂无评分项。",
            "loading_compare": "正在加载对比 #{id}…",
        },
        "flash": {
            "rubric_created": "规则已创建。",
            "rubric_updated": "规则已更新。",
            "rubric_deleted": "规则「{name}」已删除。",
            "criterion_added": "评分项已添加。",
            "criterion_updated": "评分项已更新。",
            "criterion_deleted": "评分项已删除。",
            "criterion_moved": "评分项已移动。",
            "prompt_created": "提示词已创建。",
            "prompt_updated": "提示词已更新。",
            "prompt_deleted": "提示词「{name}」已删除。",
            "harbor_refreshed": "Harbor 规则已刷新。",
            "harbor_failed": "Harbor 提取失败：{detail}",
        },
        "matrix": {
            "criterion": "评分项",
            "view_draft": "查看草案",
            "pass": "通过",
            "fail": "不通过",
            "running": "正在运行对比……可能需要一分钟。",
            "select_min": "请至少选择 2 个提示词。",
            "error": "错误：",
            "loading": "加载中……",
            "empty_draft": "（空草案）",
            "no_reasoning": "（无判定理由）",
            "not_found": "服务器上未找到对比 #{id}。",
            "error_loading": "加载对比失败（且无缓存可用）。",
            "draft_title": "草案 · ",
            "legend_single": "单元格显示通过/不通过。点击单元格查看判定理由。",
            "legend_multi": "单元格显示通过率 (k/N)。点击单元格查看判定理由。",
            "headline": "{n} 次运行；{passed}/{total} 项评分项通过（按最后一次草稿统计）。",
            "meta": "{ct} · {rubric} · {mode} · N={n}",
        },
        "crit_row": {
            "new": "新建评分项",
            "remove": "移除",
            "name": "名称",
            "description": "描述",
            "guidance": "判定指引",
        },
    },
    "en": {
        "nav": {
            "brand": "Evaluation Rules Manager",
            "rubrics": "Rubrics",
            "prompts": "Prompts",
            "compare": "Compare",
            "new_local_rubric": "+ New local rubric",
            "re_extract_harbor": "↻ Re-extract harbor",
            "re_extract_confirm": "Re-run harbor extraction? Local rubrics are preserved.",
        },
        "switch": {"en": "EN", "zh": "中文"},
        "btn": {
            "new_prompt": "+ New prompt",
            "new_compare": "+ New compare",
        },
        "h1": {
            "evaluation_rubrics": "Evaluation rubrics",
            "generation_prompts": "Generation prompts",
            "prompt_compares": "Prompt compares",
            "compare_label": "Compare",
            "create_local_rubric": "Create a local rubric",
            "edit_rubric": "Edit rubric",
            "create_prompt": "Create a prompt",
            "edit_prompt": "Edit prompt",
            "new_compare": "New prompt compare",
            "criteria": "Criteria",
            "content": "Content",
            "initial_criteria": "Initial criteria",
            "add_criterion": "Add a criterion",
        },
        "col": {
            "num": "#",
            "name": "Name",
            "context": "Context",
            "source": "Source",
            "source_path": "Source path",
            "criteria": "Criteria",
            "contract_type": "Contract type",
            "purpose": "Purpose",
            "type": "Type",
            "mode": "Mode",
            "n": "N",
            "created": "Created",
            "label": "Label",
            "rubric": "Rubric",
        },
        "form": {
            "name": "Name",
            "context": "Context",
            "description": "Description",
            "contract_type": "Contract type",
            "purpose": "Purpose",
            "prompt_type": "Prompt type",
            "content": "Content",
            "task": "Task",
            "rubric": "Rubric",
            "mode": "Mode",
            "drafts_per_prompt": "Drafts per prompt (N)",
            "prompts": "Prompts",
            "label": "Label",
            "guidance": "Guidance (PASS if … / FAIL if …)",
            "unique_among_local": "(unique among local rubrics)",
            "unique_among_prompts": "(unique among prompts)",
            "prompt_type_hint": "(variant/lineage tag, e.g. baseline / experimental)",
            "content_hint": "(the prompt body)",
            "task_hint": "(the drafting request)",
            "drafts_hint": "N=1 shows pass/fail; N>1 shows per-criterion pass-rate (k/N).",
            "prompts_hint": "(select 2 or more)",
            "label_hint": "(optional)",
            "optional": "(optional)",
            "create_rubric": "Create rubric",
            "save_changes": "Save changes",
            "create_prompt_btn": "Create prompt",
            "run_compare": "Run compare",
            "cancel": "Cancel",
            "add_criterion_row": "+ Add criterion row",
        },
        "hint": {
            "rubrics_list": 'A JSON view of this data is available at <code>/api/rubrics</code> (see <code>/api/docs</code>). Harbor rubrics are read-only; refresh them with “Re-extract harbor”.',
            "prompts_list": 'A JSON view of this data is available at <code>/api/prompts</code> (see <code>/api/docs</code>). Prompts are locally authored and fully editable.',
            "compare_list": 'A JSON view is available at <code>/api/compare</code>. Compares draft a contract with each selected prompt and judge each draft against the rubric.',
            "compare_form": "Hold an area fixed (contract type + rubric + task) and vary the prompt. Each selected prompt drafts a contract (drafter-only) and each draft is judged against the rubric. Results are grouped and mirrored to your browser.",
            "seed_criteria": "Seed the rubric with criteria now, or add them later from the rubric page.",
            "no_prompts_compare": 'No prompts yet. Create some or run <code>scripts/seed_contract_prompts.py</code>.',
        },
        "empty": {
            "rubrics": "No rubrics yet. Create a local rubric or re-extract harbor.",
            "prompts": 'No prompts yet. Create one or run <code>scripts/seed_contract_prompts.py</code>.',
            "compares": "No compares yet. Run one from",
        },
        "badge": {"local": "local"},
        "detail": {
            "back_to_rubrics": "← back to rubrics",
            "back_to_prompts": "← back to prompts",
            "back_to_compares": "← back to compares",
            "edit_rubric": "Edit rubric",
            "edit_prompt": "Edit prompt",
            "delete_rubric": "Delete rubric",
            "delete_prompt": "Delete prompt",
            "delete_rubric_confirm": "Delete rubric '{name}' and all {count} criteria?",
            "delete_prompt_confirm": "Delete prompt '{name}'?",
            "delete_criterion_confirm": "Delete criterion '{name}'?",
            "readonly_note": 'This is a read-only harbor reference rubric (source <code>{source}</code>). Edit criteria by refreshing the source instead - use “Re-extract harbor”.',
            "description_label": "Description:",
            "guidance_label": "Guidance:",
            "criterion_desc_placeholder": "What is checked",
            "save_criterion": "Save criterion",
            "add_criterion": "Add criterion",
            "edit_btn": "✎ Edit",
            "close": "Close",
            "no_criteria": "This rubric has no criteria yet.",
            "loading_compare": "Loading compare #{id}…",
        },
        "flash": {
            "rubric_created": "Rubric created.",
            "rubric_updated": "Rubric updated.",
            "rubric_deleted": "Rubric '{name}' deleted.",
            "criterion_added": "Criterion added.",
            "criterion_updated": "Criterion updated.",
            "criterion_deleted": "Criterion deleted.",
            "criterion_moved": "Criterion moved.",
            "prompt_created": "Prompt created.",
            "prompt_updated": "Prompt updated.",
            "prompt_deleted": "Prompt '{name}' deleted.",
            "harbor_refreshed": "Harbor rubrics refreshed.",
            "harbor_failed": "Harbor extraction failed: {detail}",
        },
        "matrix": {
            "criterion": "criterion",
            "view_draft": "view draft",
            "pass": "pass",
            "fail": "fail",
            "running": "Running compare… this may take a minute.",
            "select_min": "Select at least 2 prompts.",
            "error": "Error: ",
            "loading": "Loading…",
            "empty_draft": "(empty draft)",
            "no_reasoning": "(no reasoning recorded)",
            "not_found": "Compare #{id} was not found on the server.",
            "error_loading": "Error loading compare (and no cached copy available).",
            "draft_title": "Draft · ",
            "legend_single": "Cells show pass/fail. Click a cell for judge reasoning.",
            "legend_multi": "Cells show pass-rate (k/N). Click a cell for judge reasoning.",
            "headline": "{n} run(s); {passed}/{total} criteria passed (last-draft counts).",
            "meta": "{ct} · {rubric} · {mode} · N={n}",
        },
        "crit_row": {
            "new": "New criterion",
            "remove": "Remove",
            "name": "Name",
            "description": "Description",
            "guidance": "Guidance",
        },
    },
}


def _walk(catalog: dict[str, Any], dotted_key: str) -> str | None:
    """Walk a nested dict by a dotted path; return the leaf or None."""
    node: Any = catalog
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def resolve_locale(request: Request) -> tuple[str, dict[str, Any]]:
    """Resolve the active locale for a request.

    Order: ``?lang`` query param ▶ ``lang`` cookie ▶ first supported
    ``Accept-Language`` match ▶ ``DEFAULT``. An unsupported value at any step
    falls through to the next step.
    """
    lang = request.query_params.get("lang")
    if lang not in SUPPORTED:
        lang = request.cookies.get("lang")
    if lang not in SUPPORTED:
        accept = request.headers.get("accept-language", "")
        for tag in accept.split(","):
            code = tag.strip().split("-")[0].lower()
            if code in SUPPORTED:
                lang = code
                break
    if lang not in SUPPORTED:
        lang = DEFAULT
    return lang, LOCALES[lang]


def translate(t: dict[str, Any], key: str, **fmt: Any) -> str:
    """Resolve a dotted key against catalog ``t`` and format with ``**fmt``.

    If the key is unknown, ``key`` is returned unchanged (passthrough) - this is
    how dynamic flash text (e.g. tool stderr already rendered into the URL) and
    any legacy literal pass through without raising. Formatting only applies to
    catalog hits, so stray braces in a passthrough string never raise.
    """
    val = _walk(t, key)
    if val is None:
        return key
    return val.format(**fmt) if fmt else val


# --- Data-label localization (machine keys -> display labels) ------------- #
#
# The chrome catalog above localizes UI strings (labels, headings, buttons).
# This block localizes the DATA values rendered in templates - the English
# machine keys stored in the DB (contract_type=sale, purpose=drafting,
# name=draft_sale, mode=drafter-only, ...). The keys remain the canonical DB /
# URL / join identifiers; only the rendered display is localized, with raw-key
# fallback for anything unmapped or user-authored. See spec `data-label-i18n`.

# 19 《民法典》 typical contract types - keys mirror the seed scripts
# (scripts/seed_contract_prompts.py, seed_contract_rubrics.py) and
# chinese_contracts_class.md. zh/en expose identical key sets per kind.
LABELS: dict[str, dict[str, dict[str, str]]] = {
    "zh": {
        "contract_type": {
            "sale": "买卖合同",
            "utilities_supply": "供用电水气热力合同",
            "gift": "赠与合同",
            "loan": "借款合同",
            "guarantee": "保证合同",
            "lease": "租赁合同",
            "financing_lease": "融资租赁合同",
            "factoring": "保理合同",
            "work": "承揽合同",
            "construction": "建设工程合同",
            "transport": "运输合同",
            "technology": "技术合同",
            "bailment": "保管合同",
            "warehousing": "仓储合同",
            "entrustment": "委托合同",
            "property_service": "物业服务合同",
            "brokerage": "行纪合同",
            "intermediation": "中介合同",
            "partnership": "合伙合同",
        },
        "purpose": {"drafting": "起草"},
        "prompt_type": {
            "baseline": "基线",
            "experimental": "实验",
            "improved": "改进",
        },
        "context": {
            "contract": "合同",
            "check": "检查",
        },
        "mode": {"drafter-only": "仅起草"},
    },
    "en": {
        "contract_type": {
            "sale": "Sale",
            "utilities_supply": "Utilities Supply",
            "gift": "Gift",
            "loan": "Loan",
            "guarantee": "Guarantee",
            "lease": "Lease",
            "financing_lease": "Financing Lease",
            "factoring": "Factoring",
            "work": "Work",
            "construction": "Construction",
            "transport": "Transport",
            "technology": "Technology",
            "bailment": "Bailment",
            "warehousing": "Warehousing",
            "entrustment": "Entrustment",
            "property_service": "Property Service",
            "brokerage": "Brokerage",
            "intermediation": "Intermediation",
            "partnership": "Partnership",
        },
        "purpose": {"drafting": "Drafting"},
        "prompt_type": {
            "baseline": "Baseline",
            "experimental": "Experimental",
            "improved": "Improved",
        },
        "context": {
            "contract": "Contract",
            "check": "Check",
        },
        "mode": {"drafter-only": "Drafter-only"},
    },
}


def label_for(kind: str, value: str, lang: str = DEFAULT) -> str:
    """Resolve a data-value ``value`` of ``kind`` to a localized display label.

    Returns the raw ``value`` unchanged when ``kind`` or ``value`` is unmapped
    (including user-authored free text and future keys not yet catalogued) -
    never raises, never blanks. ``kind`` is one of: ``contract_type``,
    ``purpose``, ``prompt_type``, ``context``, ``mode``.
    """
    catalog = LABELS.get(lang) or LABELS[DEFAULT]
    return catalog.get(kind, {}).get(value, value)


def label_catalog_parity() -> bool:
    """True iff ``zh`` and ``en`` LABELS expose identical key sets per kind.

    Mirrors the chrome-catalog parity contract; asserted by the test suite so a
    one-sided addition can't silently ship.
    """
    kinds = set(LABELS["zh"]) | set(LABELS["en"])
    for kind in kinds:
        if set(LABELS["zh"].get(kind, {})) != set(LABELS["en"].get(kind, {})):
            return False
    return True


# Seeded-name display-title derivation. Only the *display* is derived; the
# machine name stays the URL path / join key. Falls back to the raw name for
# any non-conforming or user-authored name (including Chinese ones).
_PROMPT_NAME_RE = re.compile(r"^draft_(?P<key>[a-z_]+?)(?:_v\d+)?$")
_RUBRIC_NAME_RE = re.compile(r"^contract_(?P<key>[a-z_]+?)_v\d+$")


def title_for_prompt(name: str, lang: str = DEFAULT) -> str:
    """Localized display title for a seeded prompt name ``draft_<type_key>``.

    ``draft_sale`` -> ``买卖合同起草`` (zh) / ``Sale Drafting`` (en). Returns
    the raw ``name`` when it doesn't match the seed convention or the type key
    isn't a catalogued contract type.
    """
    if not name:
        return name or ""
    m = _PROMPT_NAME_RE.match(name)
    if not m:
        return name
    key = m.group("key")
    ct = (LABELS.get(lang) or LABELS[DEFAULT]).get("contract_type", {})
    if key not in ct:
        return name
    return f"{ct[key]}起草" if lang == "zh" else f"{ct[key]} Drafting"


def title_for_rubric(name: str, lang: str = DEFAULT) -> str:
    """Localized display title for a seeded rubric name ``contract_<type_key>_vN``.

    ``contract_sale_v1`` -> ``买卖合同评价规则`` (zh) / ``Sale Rubric`` (en).
    Returns the raw ``name`` when it doesn't match the seed convention or the
    type key isn't a catalogued contract type.
    """
    if not name:
        return name or ""
    m = _RUBRIC_NAME_RE.match(name)
    if not m:
        return name
    key = m.group("key")
    ct = (LABELS.get(lang) or LABELS[DEFAULT]).get("contract_type", {})
    if key not in ct:
        return name
    return f"{ct[key]}评价规则" if lang == "zh" else f"{ct[key]} Rubric"
