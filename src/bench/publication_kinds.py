"""Typed publication kinds: a registry of *what this deployment can publish*.

Ontology publications are one kind among several. Other knowledge assets — the
standard a fleet scores itself against, the gold corpus it is measured on — are
also versioned objects, and a fleet that self-evaluates needs them as
**immutable versions**: only a frozen snapshot makes yesterday's and today's
scores comparable. This module is the kernel half of that: the registry and the
entry projection. Nothing here knows which kinds exist — a domain pack registers
them, exactly the way it registers the asset catalog
(``src/bench/domain_assets``), so adding a vertical needs no kernel change and
the kernel-purity gate keeps holding.

Provider contract (per kind)::

    {
      "relation": "<SELECT: one row per asset_key, columns asset_key, name, summary>",
      "label_key": "<i18n key naming the kind in the console>",
      "sort_key": "<projected column the entry list is ordered by>",
      "shape_version": <positive int; the projection's shape, NOT part of the digest>,
    }

``relation`` is a self-contained SELECT over the asset's own table (DISTINCT
where its identity column is not unique). ``summary`` is whatever text makes
two versions of the same entry distinguishable — it is content, so it enters
the digest; ``name`` is display.

Two rules this module exists to keep:

- **The projection is a pure function of content.** Entries are normalized to a
  fixed key set and sorted by ``(sort_key, asset_key)``, so the same shelf
  projects to the same payload regardless of row order in the database.
- **Shape version stays outside the payload.** It travels in the publication
  row and the pull response, never inside the digested manifest — bumping the
  shape must not invalidate every digest ever published.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Rows are decoded from either dict-row or
plain tuple cursors.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

#: Every registered kind, in registration order. Replaced (not mutated) by
#: :func:`register_kinds`, so ``list(KINDS)`` always reflects what this process
#: can publish.
KINDS: tuple[str, ...] = ()

_PROVIDERS: dict[str, dict] = {}

_STRING_FIELDS = ("relation", "label_key", "sort_key")

#: The entry key set. Fixed: a projection that omits a field would make the
#: payload's shape depend on the asset table's columns.
ENTRY_FIELDS = ("asset_key", "name", "summary")

# ------------------------------------------------------------------ registry


def _validate_provider(kind: str, provider: Any) -> dict:
    """Shape-check one provider; raise naming the offending kind."""
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError(f"publication kind must be a non-empty string; got {kind!r}")
    if not isinstance(provider, Mapping):
        raise ValueError(f"provider for {kind!r} must be a mapping")
    out: dict = {}
    for field in _STRING_FIELDS:
        value = provider.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"provider for {kind!r} needs a non-empty {field!r} string"
            )
        out[field] = value
    # A sort key outside the projected key set would sort every entry as "",
    # making the payload depend on row order — the exact nondeterminism the
    # digest cannot absorb.
    if out["sort_key"] not in ENTRY_FIELDS:
        raise ValueError(
            f"provider for {kind!r}: sort_key {out['sort_key']!r} must be one of "
            f"{list(ENTRY_FIELDS)}"
        )
    shape_version = provider.get("shape_version")
    if isinstance(shape_version, bool) or not isinstance(shape_version, int) or shape_version < 1:
        raise ValueError(
            f"provider for {kind!r} needs a positive integer 'shape_version'"
        )
    out["shape_version"] = shape_version
    return out


def register_kinds(providers: Mapping[str, Mapping[str, Any]]) -> None:
    """Register (or replace) the publication kinds this process can serve.

    Called by a domain pack at import time; idempotent per kind, so importing a
    pack twice duplicates nothing. The pack owns the SQL and the label keys.
    """
    if not isinstance(providers, Mapping) or not providers:
        raise ValueError("providers must be a non-empty mapping of kind -> provider")
    validated = {
        kind: _validate_provider(kind, provider)
        for kind, provider in providers.items()
    }
    global KINDS
    _PROVIDERS.update(validated)
    KINDS = tuple(_PROVIDERS)


def list_kinds() -> tuple[str, ...]:
    """The registered kinds, in registration order (empty when no pack loaded)."""
    return KINDS


def resolve(
    kind: str,
    providers: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict:
    """The provider for one kind, or a refusal that names the registered kinds.

    An unregistered kind must be refused loudly, never served as an empty
    catalogue: "nothing to publish" and "this deployment cannot publish that"
    are different statements, and only one of them is true.
    """
    catalog = (
        {k: _validate_provider(k, p) for k, p in providers.items()}
        if providers is not None
        else {k: dict(p) for k, p in _PROVIDERS.items()}
    )
    if not catalog:
        raise ValueError(
            "no publication kinds registered: import the domain pack that "
            "declares this deployment's publishable asset kinds"
        )
    if kind not in catalog:
        raise ValueError(
            f"asset_kind must be one of {list(catalog)}; got {kind!r}"
        )
    return catalog[kind]


# ---------------------------------------------------------------- projection


def _columns(row: Any) -> tuple[Any, Any, Any]:
    if isinstance(row, Mapping):
        return row["asset_key"], row["name"], row["summary"]
    return row[0], row[1], row[2]


def _as_text(value: Any) -> str:
    """Normalize to text; missing values become ``""`` so a column added later
    does not produce a phantom diff against snapshots taken before it."""
    return "" if value is None else str(value)


def build_manifest(
    conn: Any,
    *,
    domain_id: int,
    asset_kind: str,
    providers: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict:
    """Project the entries of ``asset_kind`` shelved by this domain.

    Only the domain's **shelf** is projected (``domain_assets``): an asset that
    was never catalogued into the domain is not part of its publication, and
    publishing never touches the shelf. The domain key is deliberately NOT in
    the payload — the digest is a content anchor, so the same ruler shelved by
    two domains is the same ruler.

    Refuses an empty projection: a publication with no entries is not a
    snapshot of anything. Duplicate keys mean corrupt content and are refused
    rather than silently collapsed.
    """
    provider = resolve(asset_kind, providers)
    rows = conn.execute(
        "SELECT a.asset_key, a.name, a.summary FROM domain_assets da "
        f"JOIN ({provider['relation']}) a ON a.asset_key = da.asset_key "
        "WHERE da.domain_id = %s AND da.asset_kind = %s",
        (domain_id, asset_kind),
    ).fetchall()
    entries: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        key, name, summary = _columns(row)
        text_key = _as_text(key)
        if text_key in seen:
            raise ValueError(
                f"duplicate asset_key {text_key!r} in the {asset_kind!r} "
                "projection; cannot publish corrupt content"
            )
        seen.add(text_key)
        entries.append(
            {"asset_key": text_key, "name": _as_text(name), "summary": _as_text(summary)}
        )
    if not entries:
        raise ValueError(f"asset_kind {asset_kind!r} has nothing to publish")
    sort_key = provider["sort_key"]
    entries.sort(key=lambda e: (e.get(sort_key, ""), e["asset_key"]))
    return {"asset_kind": asset_kind, "entries": entries}


def diff_manifests(old: Optional[dict], new: dict) -> dict:
    """Keyed diff against the previous snapshot — the changelog's vocabulary.

    ``old is None`` is the first publication: the changelog records the initial
    inventory. Otherwise entries are keyed by ``asset_key``; ``changed`` carries
    field-level ``before``/``after``. Same shape as the ontology changelog, so
    the console renders both with one template branch.
    """
    counts = {"entries": len(new.get("entries") or [])}
    if old is None:
        return {"initial": True, "counts": counts}
    before = {e["asset_key"]: e for e in old.get("entries") or []}
    after = {e["asset_key"]: e for e in new.get("entries") or []}
    changed: list[dict] = []
    for key in sorted(before.keys() & after.keys()):
        fields = {
            field: {"before": before[key].get(field), "after": after[key].get(field)}
            for field in ENTRY_FIELDS
            if field != "asset_key" and before[key].get(field) != after[key].get(field)
        }
        if fields:
            changed.append({"key": key, "fields": fields})
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": changed,
        "counts": counts,
    }
