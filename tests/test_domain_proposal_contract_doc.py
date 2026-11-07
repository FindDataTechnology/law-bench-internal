"""The submission contract doc must not drift from the code that enforces it.

``docs/domain-proposal-contract.md`` is what the fleet-side integration reads
instead of this repo. Every user-facing refusal that a caller has to handle is
a string in the code; if one changes and the doc keeps the old wording, the
integration silently matches on nothing. These assertions are the cheap half of
that guard — the behavioural half lives in ``tests/test_domain_console.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "domain-proposal-contract.md"

#: (text the doc quotes to callers, what to look for in the code). They differ
#: only where the code builds the message with a format string.
REFUSALS = (
    ("提案必须携带依据", "提案必须携带依据"),
    ("同键已驳回，需新证据", "同键已驳回，需新证据"),
    ("不在模板 v", "不在模板 v"),
    (
        "relationship 提案的 evidence 缺少非空的 from_key/to_key 端点",
        "relationship 提案的 evidence 缺少非空的 from_key/to_key 端点",
    ),
    (
        "relationship 提案的 evidence 必须是对象并携带 from_key/to_key",
        "relationship 提案的 evidence 必须是对象并携带 from_key/to_key",
    ),
    ("驳回必须写明理由", "驳回必须写明理由"),
    ("无该域权限", "无该域权限"),
    ("missing scope: content:write", "missing scope: {scope}"),
)


def test_doc_exists():
    assert DOC.is_file()


def test_doc_states_the_endpoint_and_its_identity():
    text = DOC.read_text(encoding="utf-8")
    assert "POST /api/d/{domain_key}/proposals" in text
    for field in ("source", "kind", "external_key", "body", "evidence", "submitted_by"):
        assert f"`{field}`" in text, f"contract field {field!r} undocumented"


def test_doc_quotes_every_refusal_verbatim():
    text = DOC.read_text(encoding="utf-8")
    missing = [doc for doc, _ in REFUSALS if doc not in text]
    assert missing == [], f"contract doc is stale on: {missing}"


def test_refusals_still_exist_in_the_code():
    """The other direction: the doc must not promise messages nobody raises."""
    haystack = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            REPO_ROOT / "src" / "bench" / "proposals.py",
            REPO_ROOT / "src" / "web" / "routes" / "console.py",
            REPO_ROOT / "src" / "web" / "auth" / "deps.py",
            REPO_ROOT / "src" / "web" / "auth" / "domain_rbac.py",
        )
    )
    stale = [doc for doc, probe in REFUSALS if probe not in haystack]
    assert stale == [], f"documented refusals nobody raises any more: {stale}"
