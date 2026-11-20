"""The near-endpoint rule is one implementation on every write path.

Change ``add-finance-erp-domain-slices``. Production carried 8 crosswalks whose
near endpoint did not exist (measured 2026-11-21, namespace ``erp``): the inbox
checked the rule, the in-process importer did not, so one path accepted what the
other refused. The quality view then reported them as "external system not
connected" — pointing whoever read it at an integration that was never the
problem.

Two things are pinned here:

- the rule itself (pure, no DB);
- that **both** write paths apply it, with the same wording.
"""

from __future__ import annotations

import json

import pytest

from src.bench import authoring, crosswalk, quality, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


def _attrs(system: str, *, connectivity: bool = False) -> str:
    attrs: dict = {
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": system, "id": system},
    }
    if connectivity:
        attrs["connectivity"] = {
            state: {"ok": False} for state in crosswalk.CONNECTIVITY_STATES
        }
    return json.dumps(attrs)


def _insert_crosswalk(conn, key: str, *, system: str, connectivity: bool = False):
    conn.execute(
        "INSERT INTO knowledge_units (kind, namespace, external_key, body, attrs, "
        "created_at, updated_at) VALUES ('crosswalk','erp',%s,'b',%s::jsonb,'now','now')",
        (key, _attrs(system, connectivity=connectivity)),
    )


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    yield empty_db


@pytest.fixture()
def domain(db_conn):
    tpl = templates.create_template(
        db_conn,
        name="erp-base",
        schema={
            "entity_types": ["organization", "account"],
            "concept_structures": {},
            "relationship_kinds": ["sells_to"],
            "tier_vocabulary": list(TIERS),
            "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
            "corpus_declaration": {"source_types": []},
            "layer": "industry",
            "authority": {"kind": "platform"},
        },
        created_by="t",
    )
    dom = workspaces.instantiate_domain(
        db_conn, key="erp", name="ERP",
        template_name="erp-base", template_version=tpl["version"], created_by="t",
    )
    db_conn.commit()
    return dom


def _mapping(**over) -> dict:
    base = {
        "relation": "same_as",
        "peer": {"kind": "external_id", "system": "kingdee", "id": "BD001"},
        "confidence": 0.9,
    }
    base.update(over)
    return base


# ------------------------------------------------------------ the rule itself


def test_bare_key_strips_the_type_prefix():
    assert crosswalk.bare_key("organization:kingdee") == "kingdee"
    assert crosswalk.bare_key("kingdee") == "kingdee"
    assert crosswalk.bare_key("") == ""


def test_endpoint_problem_is_none_when_the_bare_key_is_known():
    assert crosswalk.endpoint_problem("organization:kingdee", {"kingdee"}) is None


def test_endpoint_problem_is_none_when_the_full_key_is_known():
    assert crosswalk.endpoint_problem("organization:kingdee",
                                      {"organization:kingdee"}) is None


def test_endpoint_problem_names_the_missing_endpoint():
    problem = crosswalk.endpoint_problem("organization:ghost", set())
    assert problem is not None
    assert "organization:ghost" in problem


# --------------------------------------------------------- both write paths


def test_direct_write_refuses_a_dangling_near_end(db_conn, domain):
    """The path the importer uses. It used to accept anything."""
    with pytest.raises(ValueError) as exc:
        authoring.authoring_create_crosswalk(
            db_conn, domain_key="erp", external_key="organization:kingdee",
            body="映射", operator="system:import", attrs=_mapping(),
        )
    assert "organization:kingdee" in str(exc.value)
    assert db_conn.execute(
        "SELECT count(*) AS n FROM knowledge_units WHERE kind = 'crosswalk'"
    ).fetchone()["n"] == 0


def test_both_paths_refuse_with_the_same_wording(db_conn, domain):
    """One rule, two entry points — the message must not diverge either."""
    from src.bench import proposals

    with pytest.raises(ValueError) as direct:
        authoring.authoring_create_crosswalk(
            db_conn, domain_key="erp", external_key="organization:ghost",
            body="映射", operator="system:import", attrs=_mapping(),
        )

    with pytest.raises(proposals.ProposalTargetExists) as via_inbox:
        proposals.submit(
            db_conn, domain_key="erp", source="user:expert-1", kind="crosswalk",
            external_key="organization:ghost", body="映射",
            evidence={"mapping": _mapping(), "quote": "某张表第 3 行"},
            submitted_by="expert-1", authenticated_as="expert-1",
        )

    # The inbox wraps the same sentence in its own error type; the assertion that
    # matters is that the sentence is the rule's, not a second copy of it.
    assert str(direct.value) in str(via_inbox.value)


def test_direct_write_accepts_when_the_endpoint_exists(db_conn, domain):
    authoring.authoring_create_unit(
        db_conn, domain_key="erp", kind="organization",
        external_key="organization:kingdee", body="金蝶", operator="t",
    )
    unit = authoring.authoring_create_crosswalk(
        db_conn, domain_key="erp", external_key="organization:kingdee",
        body="映射", operator="system:import", attrs=_mapping(),
    )
    assert unit["kind"] == "crosswalk"


def test_direct_write_accepts_an_endpoint_that_is_only_pending(db_conn, domain):
    """A pair of endpoints may be under review together."""
    from src.bench import proposals

    proposals.submit(
        db_conn, domain_key="erp", source="user:expert-1", kind="organization",
        external_key="organization:kingdee", body="金蝶",
        evidence={"quote": "connector-status.json"}, submitted_by="expert-1",
        authenticated_as="expert-1",
    )
    unit = authoring.authoring_create_crosswalk(
        db_conn, domain_key="erp", external_key="organization:kingdee",
        body="映射", operator="system:import", attrs=_mapping(),
    )
    assert unit["kind"] == "crosswalk"


def test_confirming_a_crosswalk_does_not_pass_by_pointing_at_itself(db_conn, domain):
    """The pending proposal's own key IS its near endpoint.

    Leaving that row in the known set would let every confirmation satisfy the
    check with the very row it is confirming — the rule would never fire.
    """
    from src.bench import proposals

    # The near endpoint never exists; only the crosswalk proposal itself is in
    # the box. (Written directly because `submit` would refuse it — that refusal
    # is the rule under test, so it cannot also be how the fixture is built.)
    db_conn.execute(
        "INSERT INTO domain_proposals (domain_id, source, kind, external_key, body, "
        "evidence, evidence_digest, state, submitted_by) "
        "VALUES (%s,'user:expert-1','crosswalk','organization:ghost','映射',"
        "%s::jsonb,'d','pending','expert-1')",
        (domain["id"], json.dumps({"mapping": _mapping()})),
    )
    pid = db_conn.execute(
        "SELECT id FROM domain_proposals WHERE external_key = 'organization:ghost'"
    ).fetchone()["id"]
    db_conn.commit()

    with pytest.raises(ValueError) as exc:
        proposals.confirm(db_conn, domain_key="erp", proposal_id=pid, actor="lead-1")
    assert "organization:ghost" in str(exc.value)


# --------------------------------------------------------------- the gap


def test_dangling_gap_is_counted_separately_from_stale(db_conn, domain):
    """8 rows, near end missing, connectivity absent — two different answers."""
    for i in range(8):
        _insert_crosswalk(
            db_conn, f"organization:provider-{i}",
            system=f"provider-{i}", connectivity=True,
        )
    db_conn.commit()

    gaps = quality.crosswalk_gaps(db_conn, namespace="erp")
    assert len(gaps["dangling"]) == 8
    assert len(gaps["stale"]) == 8
    assert gaps["unconfirmed"] == []


def test_dangling_gap_reaches_the_matrix(db_conn, domain):
    """A gap nobody emits is not a gap. Until 2026-11-21 the matrix never
    carried any crosswalk gap, so the three-state discipline was unreachable
    from the page that dispatches work."""
    from src.bench import estate

    _insert_crosswalk(db_conn, "organization:ghost", system="x")
    db_conn.commit()

    row = estate.matrix(db_conn, domains=[domain])[0]
    assert "quality:crosswalk_dangling" in row["gaps"]


def test_fixing_the_near_end_clears_dangling_but_not_stale(db_conn, domain):
    """Repairing the endpoint does not connect the external system."""
    _insert_crosswalk(db_conn, "organization:kingdee", system="kingdee",
                      connectivity=True)
    db_conn.commit()

    before = quality.crosswalk_gaps(db_conn, namespace="erp")
    assert len(before["dangling"]) == 1

    authoring.authoring_create_unit(
        db_conn, domain_key="erp", kind="organization",
        external_key="organization:kingdee", body="金蝶", operator="t",
    )
    after = quality.crosswalk_gaps(db_conn, namespace="erp")
    assert after["dangling"] == []
    assert len(after["stale"]) == 1
