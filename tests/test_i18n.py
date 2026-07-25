"""Tests for the evaluation-rules web UI's multi-locale (zh/en) layer.

Covers: catalog parity (zh/en expose identical key sets), per-request locale
resolution (``?lang`` > cookie > default ``zh``; ``Accept-Language`` is
ignored), the language switcher, localized table headers / ``<html lang>``,
key-based flash messages with interpolation, and that every key referenced by
``app.js`` exists in both catalogs.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from src.web.i18n import (
    DEFAULT,
    LABELS,
    LOCALES,
    SUPPORTED,
    label_catalog_parity,
    label_for,
    resolve_locale,
    title_for_prompt,
    title_for_rubric,
    translate,
)

# Keys referenced by static/app.js (must exist in both catalogs so the
# client-rendered matrix and criterion-row template localize, degrading to
# the English fallback otherwise).
APP_JS_KEYS = [
    "crit_row.new", "crit_row.remove", "crit_row.name",
    "crit_row.description", "crit_row.guidance",
    "matrix.select_min", "matrix.running", "matrix.error", "matrix.meta",
    "matrix.headline", "matrix.legend_multi", "matrix.legend_single",
    "matrix.criterion", "matrix.pass", "matrix.fail", "matrix.view_draft",
    "matrix.no_reasoning", "matrix.draft_title", "matrix.loading",
    "matrix.empty_draft", "matrix.not_found", "matrix.error_loading",
]


def _leaf_keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _leaf_keys(v, p)
        else:
            out.add(p)
    return out


def _flash_q(response):
    return parse_qs(urlparse(response.headers["location"]).query)


# --- catalog ---------------------------------------------------------------- #


def test_supported_and_default():
    assert SUPPORTED == ("zh", "en")
    assert DEFAULT == "zh"


def test_catalog_parity_zh_en():
    zh, en = _leaf_keys(LOCALES["zh"]), _leaf_keys(LOCALES["en"])
    assert zh == en, f"zh-only={zh - en} en-only={en - zh}"


def test_app_js_keys_exist_in_both_catalogs():
    for locale in ("zh", "en"):
        for key in APP_JS_KEYS:
            assert translate(LOCALES[locale], key) != key, f"{locale} missing {key}"


def test_translate_passthrough_on_unknown_key():
    # dynamic error text (not a catalog key) falls through unchanged
    assert translate(LOCALES["zh"], "not.a.real.key") == "not.a.real.key"


def test_translate_interpolation():
    assert translate(LOCALES["en"], "flash.prompt_deleted", name="p1") == "Prompt 'p1' deleted."
    assert translate(LOCALES["zh"], "flash.prompt_deleted", name="p1") == "提示词「p1」已删除。"


def test_translate_stray_braces_do_not_raise_on_passthrough():
    # a passthrough string with a stray brace must not raise (no .format applied)
    assert translate(LOCALES["en"], "boom { unbalanced") == "boom { unbalanced"


# --- data-label catalog (machine keys -> display labels) ------------------ #


def test_label_catalog_parity_zh_en():
    assert label_catalog_parity() is True
    for kind in LABELS["zh"]:
        assert set(LABELS["zh"][kind]) == set(LABELS["en"][kind]), kind


# 19 《民法典》 typical named contract types + 22 practical (中国合同分类法
# Part 2, non-overlapping) types. The catalog MUST contain exactly the union of
# these two sets, in both zh and en - asserting the seed scripts and the label
# catalog stay in lockstep.
CIVIL_CODE_TYPES = {
    "sale", "utilities_supply", "gift", "loan", "guarantee", "lease",
    "financing_lease", "factoring", "work", "construction", "transport",
    "technology", "bailment", "warehousing", "entrustment",
    "property_service", "brokerage", "intermediation", "partnership",
}
PRACTICAL_TYPES = {
    "company_formation", "equity_transfer", "capital_increase",
    "merger_acquisition", "equity_incentive", "vam_agreement",
    "equity_holding_in_trust", "real_estate_sale", "real_estate_lease",
    "employment", "labor_dispatch", "ip_license", "franchise",
    "real_estate_development", "insurance", "trust", "private_equity_fund",
    "software_development", "film_production", "talent_agency",
    "ppp_project", "tourism_service",
}


def test_label_catalog_has_all_seeded_contract_types():
    expected = CIVIL_CODE_TYPES | PRACTICAL_TYPES
    for locale in ("zh", "en"):
        assert set(LABELS[locale]["contract_type"]) == expected, locale
    # guard against a silent duplicate of a 民法典 type sneaking into practical
    assert CIVIL_CODE_TYPES.isdisjoint(PRACTICAL_TYPES)


def test_label_for_known_and_unknown():
    assert label_for("contract_type", "sale", "zh") == "买卖合同"
    assert label_for("contract_type", "sale", "en") == "Sale"
    assert label_for("purpose", "drafting", "zh") == "起草"
    assert label_for("mode", "drafter-only", "zh") == "仅起草"
    assert label_for("context", "check", "zh") == "检查"
    assert label_for("prompt_type", "baseline", "zh") == "基线"
    # unknown value -> raw passthrough
    assert label_for("contract_type", "custom_type", "zh") == "custom_type"
    # unknown kind -> raw passthrough
    assert label_for("nope", "sale", "zh") == "sale"
    # default locale is zh
    assert label_for("contract_type", "sale") == "买卖合同"


def test_title_for_prompt_seeded_and_fallback():
    assert title_for_prompt("draft_sale", "zh") == "买卖合同起草"
    assert title_for_prompt("draft_sale", "en") == "Sale Drafting"
    assert title_for_prompt("draft_financing_lease", "zh") == "融资租赁合同起草"
    assert title_for_prompt("draft_sale_v2", "zh") == "买卖合同起草"  # _vN variant suffix
    # non-conforming name -> raw
    assert title_for_prompt("my_custom", "zh") == "my_custom"
    # pattern match but unknown type key -> raw
    assert title_for_prompt("draft_custom", "zh") == "draft_custom"
    # user-authored Chinese name passes through
    assert title_for_prompt("我的提示词", "zh") == "我的提示词"


def test_title_for_rubric_seeded_and_fallback():
    assert title_for_rubric("contract_sale_v1", "zh") == "买卖合同评价规则"
    assert title_for_rubric("contract_lease_v1", "en") == "Lease Rubric"
    assert title_for_rubric("contract_financing_lease_v1", "zh") == "融资租赁合同评价规则"
    # non-conforming name -> raw (the fixture's seeded test rubrics)
    assert title_for_rubric("l_rubric", "zh") == "l_rubric"
    assert title_for_rubric("h_rubric", "zh") == "h_rubric"
    # user-authored Chinese name passes through
    assert title_for_rubric("我的规则", "zh") == "我的规则"


# --- locale resolution (end-to-end via middleware) ------------------------- #


def test_default_locale_is_zh(app_client: TestClient):
    r = app_client.get("/rubrics", follow_redirects=False)
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_query_param_overrides_cookie(app_client: TestClient):
    app_client.get("/rubrics?lang=en")          # set cookie to en
    r = app_client.get("/rubrics?lang=zh")       # explicit zh wins
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_cookie_honored_without_query(app_client: TestClient):
    app_client.get("/rubrics?lang=en")           # persist en
    r = app_client.get("/rubrics")               # no ?lang -> cookie wins
    assert "lang=en" in r.headers.get("set-cookie", "")


def test_unknown_locale_falls_back_to_default(app_client: TestClient):
    r = app_client.get("/rubrics?lang=fr")
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_accept_language_ignored_defaults_to_zh(app_client: TestClient):
    # Accept-Language is deliberately not consulted; first visit is always zh,
    # even when the browser advertises English.
    r = app_client.get("/rubrics", headers={"accept-language": "en-US,en;q=0.9"})
    assert "lang=zh" in r.headers.get("set-cookie", "")


def test_accept_language_unsupported_ignored(app_client: TestClient):
    # an unsupported Accept-Language is also ignored -> zh default
    r = app_client.get("/rubrics", headers={"accept-language": "fr-FR"})
    assert "lang=zh" in r.headers.get("set-cookie", "")


# --- localized rendering ---------------------------------------------------- #


def test_html_lang_attribute(app_client: TestClient):
    assert '<html lang="zh">' in app_client.get("/rubrics?lang=zh").text
    assert '<html lang="en">' in app_client.get("/rubrics?lang=en").text


def test_table_header_localized(app_client: TestClient):
    assert "<th>名称</th>" in app_client.get("/rubrics?lang=zh").text
    assert "<th>Name</th>" in app_client.get("/rubrics?lang=en").text


def test_locale_bootstrap_present(app_client: TestClient):
    # app.js drinks from window.__LOCALE__; the zh catalog must be on the page
    r = app_client.get("/compare/1?lang=zh")
    assert "window.__LOCALE__" in r.text
    assert '"criterion": "评分项"' in r.text


def test_switcher_marks_active_locale(app_client: TestClient):
    zh = app_client.get("/rubrics?lang=zh").text
    assert 'href="/rubrics?lang=en"' in zh
    assert 'lang=zh" aria-current="true"' in zh
    en = app_client.get("/rubrics?lang=en").text
    assert 'lang=en" aria-current="true"' in en


# --- flash messages: keys + interpolation ----------------------------------- #


def test_static_flash_emits_key_and_renders_zh(app_client: TestClient):
    r = app_client.post(
        "/rubrics",
        data={"name": "r_i18n", "context": "contract", "description": "d"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    q = _flash_q(r)
    assert q["msg"][0] == "flash.rubric_created"
    assert "err" not in q
    page = app_client.get(r.headers["location"], follow_redirects=True)
    assert "规则已创建" in page.text


def test_interpolated_flash_renders_both_locales(app_client: TestClient):
    app_client.post(
        "/prompts",
        data={
            "name": "p_del", "contract_type": "sale", "purpose": "drafting",
            "content": "x",
        },
        follow_redirects=False,
    )
    r = app_client.post("/prompts/p_del/delete", follow_redirects=False)
    assert r.status_code == 303
    q = _flash_q(r)
    assert q["msg"][0] == "flash.prompt_deleted"
    assert q["name"][0] == "p_del"
    loc = r.headers["location"]
    sep = "&" if "?" in loc else "?"
    en = app_client.get(loc + sep + "lang=en", follow_redirects=True).text
    assert "deleted" in en and "p_del" in en
    zh = app_client.get(loc + sep + "lang=zh", follow_redirects=True).text
    assert "提示词「p_del」已删除" in zh


def test_resolve_locale_unit():
    # direct unit check of the resolver precedence (no HTTP)
    from starlette.requests import Request

    def req(query="", cookie=None, accept=None):
        scope = {"type": "http", "headers": [], "query_string": query.encode()}
        if cookie:
            scope["headers"].append((b"cookie", f"lang={cookie}".encode()))
        if accept:
            scope["headers"].append((b"accept-language", accept.encode()))
        return Request(scope)

    assert resolve_locale(req("lang=en"))[0] == "en"
    assert resolve_locale(req("", cookie="en"))[0] == "en"
    assert resolve_locale(req("", accept="en-US,en;q=0.9"))[0] == "zh"  # ignored -> default
    assert resolve_locale(req("lang=fr"))[0] == "zh"          # unknown -> default
    assert resolve_locale(req(""))[0] == "zh"                 # nothing -> default
