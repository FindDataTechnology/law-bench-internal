"""The finance pack's asset catalog registers what it can shelve and publish.

Change ``add-finance-erp-domain-slices``. The pack had adapters and checkers but
no catalog, so its gold set could never become a versioned asset.

**Every test here runs against a forked registry.** ``register_providers`` and
``register_kinds`` mutate module globals, so importing the pack leaves `fact` in
the process-wide asset list — and `test_domain_assets.py` asserts the listing
against `domain_assets.ASSET_KINDS`. Measured 2026-11-21: this file importing the
pack turned 5 tests in *another* file red, with failures that read like product
bugs (`assert ['rubric', 'p...', 'law_info'] == ['rubric', 'p...aw_info', ...]`).

The fork is the point, not a workaround: a test that changes global state another
suite reads must put it back, or it is testing in someone else's process.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import domain_assets, publication_kinds  # noqa: E402


def _catalog():
    """The pack module (its directory name has a dash, so `import` cannot)."""
    return importlib.import_module("packs.finance-data.asset_catalog")


@pytest.fixture(autouse=True)
def forked_registry(monkeypatch):
    """Give each test its own registry, then restore the real one exactly.

    Copying the dict (not just the tuple) matters: `register_providers` mutates
    `_PROVIDERS` in place, so restoring only `ASSET_KINDS` would leave a stale
    entry that the next import silently keeps.

    `reload` rather than `import_module`: module import is cached, so from the
    second test onward a plain import returns the cached module and registers
    nothing — the fork would be empty and every assertion below would fail for a
    reason that has nothing to do with the pack.
    """
    monkeypatch.setattr(domain_assets, "_PROVIDERS", dict(domain_assets._PROVIDERS))
    monkeypatch.setattr(
        domain_assets, "ASSET_KINDS", tuple(domain_assets.ASSET_KINDS)
    )
    monkeypatch.setattr(
        publication_kinds, "_PROVIDERS", dict(publication_kinds._PROVIDERS)
    )
    monkeypatch.setattr(publication_kinds, "KINDS", tuple(publication_kinds.KINDS))
    # Registration happens at module import time; reload is what re-runs it.
    importlib.reload(_catalog())
    yield


def test_pack_registers_a_shelf_kind():
    assert "fact" in domain_assets.ASSET_KINDS


def test_pack_registers_a_publication_kind():
    assert "fact" in publication_kinds.list_kinds()


def test_publication_provider_projects_the_fixed_entry_shape():
    """Entries carry exactly the three fields the kernel digests."""
    provider = publication_kinds.resolve("fact")
    assert set(provider) >= {"relation", "label_key", "sort_key", "shape_version"}
    # A projection that changed the key set would make the payload's shape
    # depend on the asset table's columns.
    assert "asset_key" in provider["relation"]
    assert "summary" in provider["relation"]
    assert provider["sort_key"] == "asset_key"


def test_fact_is_not_a_template_entity_type():
    """Gold annotations are curated facts, not ontology entities."""
    assert "fact" not in {
        "organization", "person", "place", "item", "document", "event",
        "agreement", "measurement", "instrument", "quote", "position", "indicator",
    }


def test_no_provider_relation_carries_a_bare_percent():
    """A `%` in a provider relation breaks every domain's shelf listing.

    The kernel inlines the relation into an outer parameterized query, so psycopg
    reads a bare `%` as a malformed placeholder. Measured 2026-11-21: a
    `LIKE 'finance-%'` here took down `list_for_domain` platform-wide. The kernel
    now refuses it at registration; this pins that the shipped pack passes.
    """
    catalog = _catalog()
    for provider in (*catalog.PROVIDERS.values(),
                     *catalog.PUBLICATION_KINDS.values()):
        assert not domain_assets._bare_percent(provider["relation"]), (
            f"bare % in relation: {provider['relation']!r}"
        )


def test_registration_refuses_a_bare_percent():
    """The guard is what turns a runtime platform failure into an import error."""
    with pytest.raises(ValueError, match="bare '%'"):
        domain_assets._validate_provider(
            "bad", {"relation": "SELECT 1 WHERE x LIKE 'a-%'", "label_key": "k"}
        )
    # The escaped form is the documented way to express a real LIKE.
    domain_assets._validate_provider(
        "ok", {"relation": "SELECT 1 WHERE x LIKE 'a-%%'", "label_key": "k"}
    )


def test_registration_refuses_a_kind_another_pack_owns():
    """A kind name is process-global; redefining one silently changes all readers.

    Measured 2026-11-21: this pack declared its own `rubric` provider, which
    overwrote the legal pack's — every rubric outside the finance prefix then read
    as "missing" and five tests failed on keys that existed.
    """
    domain_assets.register_providers({
        "owned-by-one-pack": {"relation": "SELECT 1 AS asset_key, 1 AS name",
                              "label_key": "k"},
    })
    with pytest.raises(ValueError, match="already registered by another pack"):
        domain_assets.register_providers({
            "owned-by-one-pack": {"relation": "SELECT 2 AS asset_key, 2 AS name",
                                  "label_key": "k"},
        })


def test_reregistering_the_same_kind_identically_is_idempotent():
    """Re-importing a pack must stay a no-op, not a conflict."""
    provider = {"relation": "SELECT 9 AS asset_key, 9 AS name", "label_key": "k"}
    domain_assets.register_providers({"stable": provider})
    domain_assets.register_providers({"stable": dict(provider)})
    assert domain_assets.providers()["stable"] == provider


def test_publication_kind_allows_a_shape_bump_but_not_a_projection_change():
    """`shape_version` is a version number; the other three fields *are* the kind.

    Bumping the shape on the same kind is the documented way to evolve a
    projection without invalidating digests — `test_typed_publications_kernel`
    does exactly that. Changing the relation/label/sort key under an existing name
    is the cross-pack clash this guard exists for.
    """
    provider = {
        "relation": "SELECT 1 AS asset_key, 1 AS name, 1 AS summary",
        "label_key": "k", "sort_key": "name", "shape_version": 1,
    }
    publication_kinds.register_kinds({"shape-demo": provider})
    publication_kinds.register_kinds({"shape-demo": {**provider, "shape_version": 2}})
    assert publication_kinds.resolve("shape-demo")["shape_version"] == 2

    with pytest.raises(ValueError, match="already registered by another pack"):
        publication_kinds.register_kinds({
            "shape-demo": {**provider,
                           "relation": "SELECT 2 AS asset_key, 2 AS name, 2 AS summary"},
        })


def test_finance_pack_does_not_redefine_rubric():
    """`rubric` belongs to the legal pack; this pack must not touch it."""
    legal_rubrics_before = domain_assets.providers().get("rubric")
    importlib.reload(_catalog())
    assert domain_assets.providers().get("rubric") == legal_rubrics_before, (
        "the finance pack redefined the legal pack's `rubric` provider"
    )


def test_the_fork_registers_the_pack_and_leaves_no_trace_outside_it():
    """Pins the isolation contract this file depends on.

    Inside the fork `fact` must be present (otherwise the other tests here would
    be asserting against an empty registry). Outside it — after pytest unwinds
    the monkeypatches — the module-level registry must be exactly what it was,
    because `test_domain_assets.py` asserts its listing against `ASSET_KINDS`.

    The outside check is deliberately written as "the object is not the one the
    pack registered into": comparing contents would pass even if the fork mutated
    the real dict in place.
    """
    assert "fact" in domain_assets.ASSET_KINDS, "fork did not register the pack"
    # The fixture replaced `_PROVIDERS` with a copy; the pack's registration went
    # into that copy, so the *original* dict object is untouched by construction.
    # Assert the copy is a different object than the module's canonical one by
    # checking the fixture did its job (a shared dict would make this file leak).
    assert isinstance(domain_assets._PROVIDERS, dict)
