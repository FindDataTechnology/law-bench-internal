"""Retest obligations are booked on confirm and on template promotion (C2).

The mechanism (``verdicts.register_retest`` → ``authoring_tasks``) already
existed and was unit-tested; what was missing was a production caller. These
tests pin the wiring, not the mechanism:

- confirming a proposal books one ``verdict-retest`` task for the written unit;
- promoting a template books one per anchoring domain;
- a booking failure does NOT unwind the confirmation or the promotion (fail-open).
"""

from __future__ import annotations

import pytest

from src.bench import (
    proposals, template_readiness, templates, workspaces, authoring, verdicts,
)
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811
    ensure_schema(db_path=empty_db)
    yield empty_db


def _schema(entity_types=("company",)):
    return {
        "entity_types": list(entity_types),
        "concept_structures": {},
        "relationship_kinds": ["relates_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
        "rubric_refs": [],
    }


def _make_domain(conn, key):
    tmpl = templates.create_template(conn, name=f"tpl-{key}", schema=_schema(), created_by="admin-1")
    return workspaces.instantiate_domain(
        conn, key=key, name=f"Domain {key}", template_name=f"tpl-{key}",
        template_version=tmpl["version"], created_by="admin-1",
    )


def _retest_rows(conn, domain_id):
    return conn.execute(
        "SELECT title, target_kind, target_key, status FROM authoring_tasks "
        "WHERE domain_id = %s AND target_kind = %s",
        (domain_id, verdicts.RETEST_TARGET_KIND),
    ).fetchall()


def _submit(conn, domain_key, *, external_key="acme"):
    # `user:` needs no fleet registration (only `fleet:` is gated on a live
    # registration), but a human identity may only submit as itself — so the
    # authenticated identity must equal the `user:` source's identity.
    return proposals.submit(
        conn,
        domain_key=domain_key,
        source="user:expert@x",
        kind="company",
        external_key=external_key,
        body="Acme GmbH",
        evidence={"quote": "Acme", "source_path": "x"},
        submitted_by="expert@x",
        authenticated_as="expert@x",
    )


def test_confirm_books_retest(db_conn):
    dom = _make_domain(db_conn, "dom-confirm")
    prop = _submit(db_conn, "dom-confirm")
    db_conn.commit()

    proposals.confirm(
        db_conn, domain_key="dom-confirm", proposal_id=prop["id"], actor="lead@x",
    )
    rows = _retest_rows(db_conn, dom["id"])
    assert len(rows) == 1
    assert "company:acme" in rows[0]["target_key"]


def test_confirm_retest_booking_is_idempotent_on_same_unit(db_conn):
    dom = _make_domain(db_conn, "dom-confirm2")
    prop = _submit(db_conn, "dom-confirm2")
    db_conn.commit()
    proposals.confirm(db_conn, domain_key="dom-confirm2", proposal_id=prop["id"], actor="lead@x")
    # a second confirm is idempotent (returns the same proposal, writes nothing);
    # the retest booking therefore must not double either.
    proposals.confirm(db_conn, domain_key="dom-confirm2", proposal_id=prop["id"], actor="lead@x")
    assert len(_retest_rows(db_conn, dom["id"])) == 1


def test_confirm_survives_retest_booking_failure(db_conn, monkeypatch):
    _make_domain(db_conn, "dom-confirm3")
    prop = _submit(db_conn, "dom-confirm3")
    db_conn.commit()

    def boom(*a, **k):
        raise RuntimeError("booking down")

    monkeypatch.setattr(verdicts, "register_retest", boom)
    # must not raise: booking failure cannot unwind a confirmed proposal
    out = proposals.confirm(db_conn, domain_key="dom-confirm3", proposal_id=prop["id"], actor="lead@x")
    assert out["state"] == "confirmed"


def test_template_promotion_books_retest_per_anchoring_domain(db_conn):
    dom = _make_domain(db_conn, "dom-tpl")
    # promote tpl-dom-tpl to v2
    template_readiness.promote_template_via_gate(
        db_conn, name="tpl-dom-tpl", schema=_schema(entity_types=("company", "indicator")),
        created_by="admin-1",
    )
    rows = _retest_rows(db_conn, dom["id"])
    assert len(rows) == 1
    assert rows[0]["target_key"].startswith("template:tpl-dom-tpl@v")
