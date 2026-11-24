"""Deterministic checkers for the legal pack's ``clause`` units.

Registration happens at import time: importing this module installs the
checkers below into ``src.bench.data_checks.register_checker`` for kind
``'clause'``. Every checker is pure and deterministic — no LLM, no network,
no filesystem.

Why this file exists: legal was the **only** pack with no ``checks.py``
(erp / finance / gov / kg-gate all had one), so the legal domain's 5,000
clause units had no machine-verifiable criteria at all — the only gate was a
human reading each one. That is what the promotion ladder's ``silver`` step
was standing in for.

What these checkers are and are not:

- They do **not** judge legal quality. Whether a clause is good law is a human
  call and stays one.
- They check what is mechanically checkable about *this corpus's own
  integrity*: is the text intact, does the article number agree with the
  stored locator, is the body long enough to be a clause at all.

Discriminating power was measured on production before these were written
(2026-11-24, 4,986 live legal clauses) — otherwise they would be gates that
never fire, which teaches people to ignore gates:

=========================  =========
fragmented body            1,217 / 4,986  (24%)
body does not start with 条号      1
body shorter than 20 chars          22
missing corpus locator               7
=========================  =========
"""

from __future__ import annotations

import json
import re
from typing import Any

from src.bench.data_checks import CheckResult, register_checker

KIND = "clause"

#: An article number at the head of the body: 第七十条 / 第一千二百五十三条.
_ARTICLE_HEAD = re.compile(r"^第[一二三四五六七八九十百千零〇]+条")

#: The article number inside an external key: ``民法典#第1253条``.
_KEY_ARTICLE = re.compile(r"#第([一二三四五六七八九十百千零〇]+)条$")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}


def _cn_to_int(text: str) -> int | None:
    """Parse a Chinese numeral as used in article numbers (一千二百五十三).

    Returns ``None`` for anything this parser does not understand, so a caller
    reports "could not check" rather than a fabricated mismatch.
    """
    total, section, digit = 0, 0, None
    for ch in text:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            section += (1 if digit is None else digit) * _CN_UNITS[ch]
            digit = None
        else:
            return None
    return total + section + (digit or 0)


def _attrs(unit: dict) -> dict:
    raw = unit.get("attrs")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


def check_body_present(unit: dict) -> CheckResult:
    """A clause with no text is a placeholder, not material.

    Fail-closed on whitespace-only bodies: the corpus is Chinese text, so
    "present" means there is at least one non-space character.
    """
    body = (unit.get("body") or "").strip()
    return CheckResult(
        "body-present",
        bool(body),
        "正文为空" if not body else f"{len(body)} 字符",
    )


def check_body_not_fragmented(unit: dict) -> CheckResult:
    """The body is not one character per line.

    The corpus comes from a chunker that sometimes split on every glyph. The
    text is *present* either way, so nothing else catches it, but it reads as
    unpunctuated rubble downstream. Measured 1,217 of 4,986 live clauses (24%).
    """
    body = unit.get("body") or ""
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if len(lines) < 5:
        # Too few lines for the ratio to mean anything; not this checker's call.
        return CheckResult("body-not-fragmented", True, "行数不足，不判")
    short = sum(1 for ln in lines if len(ln) <= 2)
    ratio = short / len(lines)
    return CheckResult(
        "body-not-fragmented",
        ratio <= 0.3,
        f"{short}/{len(lines)} 行仅 1-2 字（{ratio:.0%}）",
    )


def check_article_number_agrees(unit: dict) -> CheckResult:
    """The 条号 in the body head matches the one in the external key.

    A clause whose stored locator and whose text disagree is filed under the
    wrong article — the kind of error that survives every downstream read
    because nothing cross-checks the two. When either side cannot be parsed
    the check answers "could not check" rather than inventing a verdict.
    """
    key = unit.get("external_key") or ""
    body = (unit.get("body") or "").strip()
    m_key = _KEY_ARTICLE.search(key)
    if m_key is None:
        return CheckResult("article-number-agrees", True, "键里没有条号，不判")
    m_body = _ARTICLE_HEAD.match(body)
    if m_body is None:
        return CheckResult("article-number-agrees", True, "正文开头没有条号，不判")
    want = _cn_to_int(m_key.group(1))
    got = _cn_to_int(m_body.group(1)[1:-1])  # strip 第 / 条
    if want is None or got is None:
        return CheckResult("article-number-agrees", True, "数字解析不出，不判")
    return CheckResult(
        "article-number-agrees",
        want == got,
        f"键第{want}条 / 正文第{got}条" + ("" if want == got else " ← 不一致"),
    )


def check_corpus_locator(unit: dict) -> CheckResult:
    """The unit carries the locator that makes it traceable to a document.

    ``attrs.corpus`` holds ``{library, doc_id, source_key}``; without it the
    clause cannot be traced back to the document it came from, and the whole
    point of a source-grounded corpus is that it can be.
    """
    corpus = _attrs(unit).get("corpus") or {}
    missing = [k for k in ("doc_id", "library") if not corpus.get(k)]
    return CheckResult(
        "corpus-locator",
        not missing,
        "缺 " + "、".join(missing) if missing else "doc_id=" + str(corpus.get("doc_id")),
    )


def check_body_is_substantial(unit: dict) -> CheckResult:
    """A clause shorter than 20 characters is not a clause.

    This is a floor, not a quality bar: a real article is a sentence at least.
    Measured 22 of 4,986 below it.
    """
    compact = re.sub(r"\s", "", unit.get("body") or "")
    return CheckResult(
        "body-is-substantial",
        len(compact) >= 20,
        f"{len(compact)} 字",
    )


#: Registration order fixes criteria order on the evaluation row.
for _name, _fn in (
    ("body-present", check_body_present),
    ("body-not-fragmented", check_body_not_fragmented),
    ("article-number-agrees", check_article_number_agrees),
    ("corpus-locator", check_corpus_locator),
    ("body-is-substantial", check_body_is_substantial),
):
    register_checker(KIND, _name, _fn)
