"""Entity keys: slugging, clause addressing, and rule-driven alias folding.

A key is an entity's identity: get it wrong and every reference, dedup, publish
and downstream consumer inherits the error. Two failure modes matter, and they
are not symmetric:

- **under-merging** (one thing, two keys) is noisy but recoverable — a reviewer
  sees both and can merge later;
- **over-merging** (two things, one key) silently destroys a distinction, and a
  published snapshot carries the loss forward.

So this module deliberately provides *mechanisms*, never a guess: ``fold``
applies an explicit, ordered list of rules supplied by the domain pack, and
refuses to do fuzzy matching at all. The kernel must not know what
"中华人民共和国" is; a pack does.

Three address forms:

- :func:`slug` — text to a stable, URL-safe fragment.
- :func:`clause_no` — "第<digits>条" to ``12``; structural names (preface,
  chapter, section) are *not* clauses and return ``None``.
- :func:`clause_key` — ``"<parent>#第12条"``; a clause never exists without its
  parent document, because "第十二条" alone matches nearly every instrument.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

#: Full-width spaces and the usual CJK separators that carry no meaning in a key.
_SEPARATORS = re.compile(r"[\s\u3000/\\:：·、，,。;；（）()\[\]【】《》〈〉\"'“”‘’]+")
_DASHES = re.compile(r"-{2,}")
#: Trailing parenthetical qualifiers: "（2018年修正文本）", "(2020)", "（试行）".
_TRAILING_QUALIFIER = re.compile(r"[（(][^（()）]{1,40}[）)]\s*$")

#: A clause address, digits only after folding the Chinese numerals.
_CLAUSE = re.compile(r"第\s*([0-9]+|[〇零一二三四五六七八九十百千两]+)\s*条")
#: Structural names that are *not* clauses (checked before the clause regex, so
#: "第二章" and "第三节" never reach the numeral path).
_STRUCTURAL = re.compile(r"^(序\s*言|目\s*录|前\s*言|附\s*则|总\s*则|第[〇零一二三四五六七八九十百千0-9]+\s*[章节编款项])")

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1000}


def slug(text: str) -> str:
    """Stable key fragment: NFKC, separators folded to ``-``, capped length."""
    normalised = unicodedata.normalize("NFKC", text or "").strip()
    folded = _SEPARATORS.sub("-", normalised)
    folded = _DASHES.sub("-", folded).strip("-")
    return folded[:80] or "unnamed"


def strip_trailing_qualifier(text: str) -> str:
    """Drop a trailing parenthetical ("（2018年修正文本）"), once."""
    return _TRAILING_QUALIFIER.sub("", (text or "").strip()).strip()


def fold(text: str, rules: Iterable["FoldRule"] = ()) -> tuple[str, list[str]]:
    """Apply an ordered rule list; return ``(canonical, applied_rule_names)``.

    Rules are applied in the order given and each may fire at most once. The
    returned names make a merge explainable: a reviewer can see *why* two
    spellings collapsed, which is the difference between a normalisation and a
    guess.
    """
    value = (text or "").strip()
    applied: list[str] = []
    for rule in rules:
        new = rule.apply(value)
        if new != value:
            applied.append(rule.name)
            value = new
    return value, applied


class FoldRule:
    """One explicit normalisation step. ``kind`` is ``prefix`` / ``suffix``."""

    __slots__ = ("name", "kind", "text")

    def __init__(self, name: str, kind: str, text: str):
        if kind not in ("prefix", "suffix"):
            raise ValueError("kind must be 'prefix' or 'suffix'")
        self.name, self.kind, self.text = name, kind, text

    def apply(self, value: str) -> str:
        if self.kind == "prefix" and value.startswith(self.text):
            return value[len(self.text):].strip()
        if self.kind == "suffix" and value.endswith(self.text):
            return value[: -len(self.text)].strip()
        return value

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        return f"<FoldRule {self.name} {self.kind}={self.text!r}>"


def chinese_to_int(text: str) -> Optional[int]:
    """Convert "一百二十三" / "12" to an int; ``None`` when unparsable."""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch in _DIGITS:
            current = _DIGITS[ch]
        elif ch in _UNITS:
            unit = _UNITS[ch]
            total += (current or 1) * unit
            current = 0
        else:
            return None
    return total + current


def clause_no(text: str) -> Optional[int]:
    """The article number if ``text`` *is* a clause address, else ``None``.

    Structural names win over the numeral path: "第二章" must not become
    clause 2, and "序言" is not a clause at all.
    """
    value = unicodedata.normalize("NFKC", (text or "")).strip()
    if _STRUCTURAL.match(value):
        return None
    match = _CLAUSE.search(value)
    if not match:
        return None
    number = chinese_to_int(match.group(1))
    return number if number and number > 0 else None


def clause_key(parent_key: str, number: int) -> str:
    """``<parent>#第<N>条`` — a clause is never addressable without its parent."""
    parent = (parent_key or "").strip()
    if not parent:
        raise ValueError("a clause key needs its parent document key")
    if not isinstance(number, int) or number <= 0:
        raise ValueError("clause number must be a positive integer")
    return f"{parent}#第{number}条"


# ── rule registry ────────────────────────────────────────────────────────────
#
# The kernel must not import a domain pack (there is a gate for that), and it
# must not contain domain vocabulary. So packs *push* their rules here at import
# time and the kernel only ever asks "what rules exist for this domain key" —
# the same inversion ``src/bench/domain_assets`` uses for asset providers.

_RULES: dict[str, tuple] = {}
_DISTINCT: dict[str, object] = {}


def register_rules(domain_key: str, rules: Iterable["FoldRule"],
                   distinct_document=None) -> None:
    """Register a domain's fold rules (called by a pack on import)."""
    if not domain_key:
        raise ValueError("domain_key is required")
    _RULES[domain_key] = tuple(rules)
    if distinct_document is not None:
        _DISTINCT[domain_key] = distinct_document


def rules_for(domain_key: str) -> tuple:
    """The fold rules for a domain; empty when its pack was never imported.

    Empty is the safe default: nothing is folded, so nothing is over-merged.
    """
    return _RULES.get(domain_key, ())


def distinct_document_for(domain_key: str):
    return _DISTINCT.get(domain_key)


def registered() -> list[str]:
    """Domain keys with registered rules (for diagnostics)."""
    return sorted(_RULES)
