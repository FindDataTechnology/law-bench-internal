"""Legal pack asset catalog: which corpus assets this vertical can shelve.

The kernel (``src/bench/domain_assets``) owns the generic directory mechanics
(assign / unassign / list / orphan purge) and is domain-free by construction.
This module is the legal pack's half of that contract: the six asset kinds this
corpus exposes, how each one is keyed, and the i18n key naming it in the console.

Importing this module registers the providers with the kernel, so importing the
pack is all a deployment has to do:

============  =========================  ===================================
kind          asset table                key (display name)
============  =========================  ===================================
``rubric``    ``rubrics``                ``name`` (names are not unique in
                                         the table, so the relation is
                                         DISTINCT — the directory keys the
                                         rubric *name*, the identifier every
                                         ``eval_runs.rubric_name`` uses)
``prompt``    ``prompts``                ``name`` (UNIQUE)
``compare``   ``compare_runs``           ``id::text`` (``label`` is nullable
                                         and not unique, so only the id is a
                                         stable key; it is shown in the name)
``sample``    ``contract_artifacts``     ``body_hash`` (UNIQUE, content-
                                         addressed; the ``/samples`` corpus)
``clause``    ``clauses``                ``id::text`` (no slug exists; the
                                         upsert identity is
                                         source_path/section/body_hash and
                                         the row id survives it)
``law_info``  ``law_info``               ``contract_type`` (one directory
                                         entry stands for that type's
                                         law-info set across sources)
============  =========================  ===================================

Each relation projects exactly one row per key with two columns —
``asset_key`` and ``name`` — so the kernel can LEFT JOIN (``exists``) or
anti-join (the unassigned pool) without ever reading asset content or mutating
an asset.

``PUBLICATION_KINDS`` below is the sibling declaration for *publishing*
(``src/bench/publication_kinds``): which kinds freeze into a versioned snapshot,
what each entry projects (key + name + content summary), and the order they are
sorted in.
"""

from __future__ import annotations

from src.bench.domain_assets import register_providers
from src.bench.publication_kinds import register_kinds

#: One provider per kind, in the console's listing order. ``relation`` is a
#: self-contained SELECT of (asset_key, name); ``label_key`` names the kind in
#: the i18n catalog.
PROVIDERS: dict[str, dict] = {
    "rubric": {
        "relation": "SELECT DISTINCT name AS asset_key, name AS name FROM rubrics",
        "label_key": "bench_catalog.kind.rubric",
    },
    "prompt": {
        "relation": "SELECT name AS asset_key, name AS name FROM prompts",
        "label_key": "bench_catalog.kind.prompt",
    },
    "compare": {
        "relation": (
            "SELECT id::text AS asset_key, "
            "COALESCE(NULLIF(label, ''), 'compare #' || id::text) AS name "
            "FROM compare_runs"
        ),
        "label_key": "bench_catalog.kind.compare",
    },
    "sample": {
        "relation": (
            "SELECT body_hash AS asset_key, "
            "concat_ws(' · ', contract_type, scenario, stance) AS name "
            "FROM contract_artifacts"
        ),
        "label_key": "bench_catalog.kind.sample",
    },
    "clause": {
        "relation": (
            "SELECT id::text AS asset_key, "
            "concat_ws(' · ', contract_type, section) AS name FROM clauses"
        ),
        "label_key": "bench_catalog.kind.clause",
    },
    "law_info": {
        "relation": (
            "SELECT DISTINCT contract_type AS asset_key, contract_type AS name "
            "FROM law_info"
        ),
        "label_key": "bench_catalog.kind.law_info",
    },
}

register_providers(PROVIDERS)

#: Publishable kinds (change ``add-typed-publications``). Same relation shape as
#: the catalog providers, plus ``sort_key`` (the projected column the snapshot
#: orders entries by) and ``shape_version`` (the projection's shape; it travels
#: beside the digest, never inside it — bumping it must not invalidate digests
#: already handed out). Only the kinds whose content can be frozen usefully are
#: publishable starters: a ruler and a gold sample. The list is data: adding a
#: kind here is a pack change, not a kernel change.
PUBLICATION_KINDS: dict[str, dict] = {
    # A ruler is published whole, with its criteria inline: two versions differ
    # when a criterion's wording changes, and the consumer must see that.
    "rubric": {
        "relation": (
            "SELECT r.name AS asset_key, r.name AS name, "
            "concat_ws(E'\\n', r.context, "
            "  (SELECT string_agg(c.name || '：' || c.description, E'\\n' "
            "     ORDER BY c.ordinal) FROM criteria c WHERE c.rubric_id = r.id)) "
            "AS summary "
            "FROM rubrics r"
        ),
        "label_key": "bench_catalog.kind.rubric",
        "sort_key": "name",
        "shape_version": 1,
    },
    # A gold sample is content-addressed: the body is the whole asset.
    # Superseded artifacts are excluded — they are history, not the corpus the
    # shelf offers today, and publishing them would let a stale draft ride in
    # under the current version number.
    "sample": {
        "relation": (
            "SELECT body_hash AS asset_key, "
            "concat_ws(' · ', contract_type, scenario, stance) AS name, "
            "body_text AS summary FROM contract_artifacts "
            "WHERE superseded_at IS NULL"
        ),
        "label_key": "bench_catalog.kind.sample",
        "sort_key": "name",
        "shape_version": 1,
    },
}

register_kinds(PUBLICATION_KINDS)

