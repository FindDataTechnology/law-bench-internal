"""Finance-data pack asset catalog: which assets this vertical can shelve.

The kernel (``src/bench/domain_assets``) owns the generic directory mechanics and
is domain-free by construction; this module is the finance pack's half of that
contract — which kinds it exposes, how each is keyed, and the i18n key naming it
in the console.

Two kinds, and the split matters:

``fact``
    the human-annotated sentiment gold set (``kind='fact'`` knowledge units in
    the domain's namespace). Keyed by ``external_key`` — the announcement doc id.
    These are an *ontology* asset, published with the domain.

``rubric``
    the deterministic data-check rulers. Keyed by rubric name. Shelved and
    published as a *ruler*, never merged into the ontology vocabulary.

Why ``fact`` is not a template entity type: a gold annotation is a *curated
assertion about an announcement*, not an entity in the business ontology. Adding
``fact`` to ``finance-market``'s ``entity_types`` would put evaluation data into
the vocabulary a domain reasons with, and the declaration-vs-curation ledger
would then call every other entity type "unused". Publishing it as a typed asset
keeps the two apart: the ontology says what the domain knows about the world, the
asset publication says which gold rows a consumer may rely on.

Importing this module registers both declarations, so importing the pack is all
a deployment has to do.
"""

from __future__ import annotations

from src.bench.domain_assets import register_providers
from src.bench.publication_kinds import register_kinds

#: One provider per kind, in the console's listing order. ``relation`` is a
#: self-contained SELECT of (asset_key, name); ``label_key`` names the kind in
#: the i18n catalog.
PROVIDERS: dict[str, dict] = {
    "fact": {
        "relation": (
            "SELECT external_key AS asset_key, "
            "  COALESCE(attrs->>'expected_band', 'fact') || ' · ' || "
            "  COALESCE(external_key, '') AS name "
            "FROM knowledge_units "
            "WHERE kind = 'fact' AND (tags->>'deleted') IS NULL"
        ),
        "label_key": "bench_catalog.kind.fact",
    },
    "rubric": {
        # No literal `%` anywhere in a provider relation: the kernel inlines it
        # into an outer parameterized query, so a bare `%` reaches psycopg as a
        # malformed placeholder and blows up every domain's shelf listing, not
        # just this one (measured 2026-11-21 — a `LIKE 'finance-%'` here broke
        # `list_for_domain` for the whole platform). Filter by prefix through
        # LEFT() instead, which is equivalent and has no metacharacter.
        "relation": (
            "SELECT DISTINCT name AS asset_key, name AS name FROM rubrics "
            "WHERE LEFT(name, 8) = 'finance-'"
        ),
        "label_key": "bench_catalog.kind.rubric",
    },
}

#: Publication kinds: what freezes into a versioned snapshot and what an entry
#: projects. ``summary`` is content (it enters the digest), ``name`` is display.
#:
#: ``fact`` publishes the whole gold row's identity and its anchor, not the
#: announcement text — the text lives in fd-sentiment's download lineage and
#: never enters this platform. A consumer that wants the body follows
#: ``text_sha256`` there; what it gets here is "these doc ids, at these bands,
#: as of these dates" — enough to know whether its copy is the same one.
PUBLICATION_KINDS: dict[str, dict] = {
    "fact": {
        "relation": (
            "SELECT external_key AS asset_key, "
            "  COALESCE(attrs->>'expected_band', 'fact') || ' · ' || "
            "  COALESCE(external_key, '') AS name, "
            "  concat_ws(' · ', attrs->>'as_of', attrs->>'expected_band', "
            "            attrs->>'direction', attrs->>'text_sha256', "
            "            attrs->>'gold_set') AS summary "
            "FROM knowledge_units "
            "WHERE kind = 'fact' AND (tags->>'deleted') IS NULL "
            "ORDER BY external_key"
        ),
        "label_key": "bench_catalog.kind.fact",
        "sort_key": "asset_key",
        "shape_version": 1,
    },
}

register_providers(PROVIDERS)
register_kinds(PUBLICATION_KINDS)
