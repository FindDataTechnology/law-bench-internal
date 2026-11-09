"""Legal pack's key rules: how this corpus's entity names fold together.

The kernel (``src.bench.keys``) owns the *mechanisms* — slugging, clause
addressing, ordered rule application. This module owns the **vocabulary**: which
prefixes and suffixes this domain actually uses, and — just as important — which
ones must **not** be folded away.

The exclusion list is the load-bearing part. "中华人民共和国宪法" and
"中华人民共和国宪法修正案" differ only by a suffix, and merging them would silently
destroy the distinction between an instrument and the amendment that rewrote it.
Under-merging costs a reviewer one glance; over-merging costs a wrong citation in
a published snapshot. So the rules are a short, explicit, testable list rather
than a similarity threshold.
"""

from __future__ import annotations

from src.bench.keys import FoldRule, register_rules

#: Prefixes that name the issuing state rather than the instrument. Dropping them
#: merges "中华人民共和国宪法" with "宪法" — the same document, two spellings.
PREFIX_RULES: tuple[FoldRule, ...] = (
    FoldRule("drop-prc", "prefix", "中华人民共和国"),
    FoldRule("drop-china", "prefix", "中国"),
)

#: Suffixes that name a *different* document. Listed so the intent is explicit
#: and so a future rule addition has to consciously step over them: a name
#: ending in one of these is never folded to the bare stem.
DOCUMENT_SUFFIXES: tuple[str, ...] = (
    "修正案",
    "实施条例",
    "实施细则",
    "司法解释",
    "决定",
)

#: The ordered rule list applied by :func:`canonical_name`.
RULES: tuple[FoldRule, ...] = PREFIX_RULES


def canonical_name(name: str) -> tuple[str, list[str]]:
    """Fold one entity name; ``(canonical, applied_rule_names)``."""
    from src.bench import keys

    stripped = keys.strip_trailing_qualifier(name or "")
    return keys.fold(stripped, RULES)


def is_distinct_document(name: str) -> bool:
    """True when the name carries a suffix that marks a separate document.

    Used to refuse a fold that would otherwise collapse "…宪法" into
    "…宪法修正案" (or vice versa) just because one is a prefix of the other.
    """
    value = (name or "").strip()
    return any(value.endswith(suffix) for suffix in DOCUMENT_SUFFIXES)


# Registering on import is what makes the kernel's ``rules_for`` answer for this
# domain; a deployment that never imports the pack folds nothing (safe).
register_rules("legal", RULES, is_distinct_document)
