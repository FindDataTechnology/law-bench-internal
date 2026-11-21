"""The finance pack's asset catalog registers what it can shelve and publish.

Change ``add-finance-erp-domain-slices``. The pack had adapters and checkers but
no catalog, so its gold set could never become a versioned asset. Two things are
pinned here, both of which would be silent if wrong:

- importing the pack registers its kinds (a catalog nobody imports registers
  nothing, and the publish path then reports "unregistered kind" — which reads
  like a bug in the publish path);
- ``fact`` is a *published asset kind*, never an entity type: putting it in the
  template vocabulary would make the declaration-vs-curation ledger call every
  real type unused.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The directory name carries a dash, so `import packs.finance-data...` is not
# valid syntax. Importing is what registers the pack's kinds with the kernel.
importlib.import_module("packs.finance-data.asset_catalog")

from src.bench import domain_assets, publication_kinds  # noqa: E402


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
    from src.bench.domain_assets import _bare_percent

    for provider in (*packs_catalog().PROVIDERS.values(),
                     *packs_catalog().PUBLICATION_KINDS.values()):
        assert not _bare_percent(provider["relation"]), (
            f"bare % in relation: {provider['relation']!r}"
        )


def packs_catalog():
    return importlib.import_module("packs.finance-data.asset_catalog")


def test_registration_refuses_a_bare_percent():
    """The guard is what turns a runtime platform failure into an import error."""
    from src.bench.domain_assets import _validate_provider

    with pytest.raises(ValueError, match="bare '%'"):
        _validate_provider(
            "bad", {"relation": "SELECT 1 WHERE x LIKE 'a-%'", "label_key": "k"}
        )
    # The escaped form is the documented way to express a real LIKE.
    _validate_provider(
        "ok", {"relation": "SELECT 1 WHERE x LIKE 'a-%%'", "label_key": "k"}
    )
