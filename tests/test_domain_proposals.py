"""Domain proposal inbox (src/bench/proposals.py).

Runs against ``empty_db`` + ``ensure_schema`` (the full kernel schema), the
same fixture style as ``tests/test_authoring_kernel.py``. Covers the workflow
rules that make the inbox auditable: evidence is mandatory and digested,
submission is idempotent per key, rejection needs a reason and only new
evidence can reopen a rejected key, self-confirmation is banned, confirmation
writes through the one kernel path exactly once, and a domain key can never
reach another domain's inbox.
"""

from __future__ import annotations

import pytest

from src.bench import proposals, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema


@pytest.fixture()
def db_conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    # Inject the fixture's own connection so DDL lands on the per-test DB
    # instead of the process-wide cached shared connection.
    ensure_schema(db_path=empty_db)
    yield empty_db


def authoring_schema() -> dict:
    """Template schema aligned with the kernel vocabularies."""
    return {
        "entity_types": ["company", "indicator"],
        "concept_structures": {},
        "relationship_kinds": ["belongs_to"],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {},
    }


def make_domain(conn, key: str) -> dict:
    """One template + one domain instantiated from it; return the domain."""
    tmpl = templates.create_template(
        conn, name=f"tpl-{key}", schema=authoring_schema(), created_by="admin-1"
    )
    return workspaces.instantiate_domain(
        conn,
        key=key,
        name=f"Domain {key}",
        template_name=f"tpl-{key}",
        template_version=tmpl["version"],
        created_by="admin-1",
    )


def make_two_domains(conn, key_a: str, key_b: str) -> tuple[dict, dict]:
    """Two domains sharing one template (distinct domain keys, same vocab)."""
    templates.create_template(
        conn, name=f"tpl-{key_a}", schema=authoring_schema(), created_by="admin-1"
    )
    a = workspaces.instantiate_domain(
        conn, key=key_a, name=f"Domain {key_a}",
        template_name=f"tpl-{key_a}", template_version=None, created_by="admin-1",
    )
    b = workspaces.instantiate_domain(
        conn, key=key_b, name=f"Domain {key_b}",
        template_name=f"tpl-{key_a}", template_version=None, created_by="admin-1",
    )
    return a, b


_DEFAULT_EVIDENCE = object()


def submit_company(conn, domain_key: str, *, external_key: str = "co-1",
                   evidence=_DEFAULT_EVIDENCE, submitted_by: str = "expert-1") -> dict:
    # A sentinel, not None: "no evidence" (None) is itself a case under test.
    if evidence is _DEFAULT_EVIDENCE:
        evidence = {"citation": "年报 p.12"}
    return proposals.submit(
        conn,
        domain_key=domain_key,
        source="market-feed",
        kind="company",
        external_key=external_key,
        body="某公司条目",
        evidence=evidence,
        impact="补齐主体档案",
        submitted_by=submitted_by,
    )


def ku_count(conn, namespace: str, kind: str | None = None) -> int:
    if kind is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_units WHERE namespace = %s",
            (namespace,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_units "
            "WHERE namespace = %s AND kind = %s",
            (namespace, kind),
        ).fetchone()
    return row["n"]


def authoring_event_count(conn, domain_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM authoring_events WHERE domain_id = %s",
        (domain_id,),
    ).fetchone()
    return row["n"]


def proposal_event_count(conn, proposal_id: int, to_state: str | None = None) -> int:
    if to_state is None:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_proposal_events WHERE proposal_id = %s",
            (proposal_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM domain_proposal_events "
            "WHERE proposal_id = %s AND to_state = %s",
            (proposal_id, to_state),
        ).fetchone()
    return row["n"]


# --------------------------------------------------------------- 举证必须


@pytest.mark.parametrize("bad_evidence", [None, "", "   ", {}, []])
def test_submit_requires_evidence(db_conn, bad_evidence):
    """None / empty string / whitespace / empty dict / empty list are all
    "nothing behind the claim": refused before any row is written."""
    make_domain(db_conn, "dom-evidence")
    with pytest.raises(ValueError, match="提案必须携带依据"):
        submit_company(db_conn, "dom-evidence", evidence=bad_evidence)

    assert proposals.count_pending(db_conn, domain_key="dom-evidence") == 0
    assert proposals.list_proposals(db_conn, domain_key="dom-evidence") == []


@pytest.mark.parametrize(
    "field,value", [("kind", ""), ("external_key", " "), ("body", "")]
)
def test_submit_requires_text_fields(db_conn, field, value):
    """kind / external_key / body must be non-empty strings."""
    make_domain(db_conn, "dom-text")
    kwargs = dict(
        domain_key="dom-text",
        source="market-feed",
        kind="company",
        external_key="co-1",
        body="某公司条目",
        evidence={"citation": "年报 p.12"},
        submitted_by="expert-1",
    )
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        proposals.submit(db_conn, **kwargs)
    assert proposals.count_pending(db_conn, domain_key="dom-text") == 0


def test_digest_is_stable_across_key_order(db_conn):
    """Canonical JSON: dict ordering never changes the digest."""
    first = proposals.canonical_evidence_digest({"a": 1, "b": [2, 3]})
    second = proposals.canonical_evidence_digest({"b": [2, 3], "a": 1})
    assert first == second
    assert len(first) == 64


# ------------------------------------------------------------- 幂等提交


def test_submit_is_idempotent_per_pending_key(db_conn):
    """3x same (domain, source, external_key) -> one pending row, same id,
    and the first evidence snapshot is returned unchanged."""
    make_domain(db_conn, "dom-idem")

    first = submit_company(db_conn, "dom-idem", evidence={"citation": "first"})
    second = submit_company(db_conn, "dom-idem", evidence={"citation": "second"})
    third = submit_company(db_conn, "dom-idem", evidence={"citation": "third"})

    assert first["id"] == second["id"] == third["id"]
    assert third["state"] == "pending"
    assert third["evidence"] == {"citation": "first"}  # not overwritten
    assert third["evidence_digest"] == first["evidence_digest"]
    assert proposals.count_pending(db_conn, domain_key="dom-idem") == 1
    assert len(proposals.list_proposals(db_conn, domain_key="dom-idem")) == 1
    # only the actual insert appended an event
    assert proposal_event_count(db_conn, first["id"]) == 1


# ------------------------------------------------------------- 驳回规则


def test_reject_requires_a_note(db_conn):
    """A bare rejection is not actionable: the reason is mandatory."""
    make_domain(db_conn, "dom-reject-note")
    proposal = submit_company(db_conn, "dom-reject-note")

    for bad in ("", "   "):
        with pytest.raises(ValueError, match="驳回必须写明理由"):
            proposals.reject(
                db_conn,
                domain_key="dom-reject-note",
                proposal_id=proposal["id"],
                actor="lead-1",
                note=bad,
            )
    assert proposals.get(
        db_conn, domain_key="dom-reject-note", proposal_id=proposal["id"]
    )["state"] == "pending"


def test_reject_then_resubmit_needs_new_evidence(db_conn):
    """Same evidence after rejection -> refused; different evidence -> a new
    pending row (the rejected row stays on record)."""
    make_domain(db_conn, "dom-resubmit")
    evidence = {"citation": "旧年报 p.12"}
    first = submit_company(db_conn, "dom-resubmit", evidence=evidence)
    rejected = proposals.reject(
        db_conn,
        domain_key="dom-resubmit",
        proposal_id=first["id"],
        actor="lead-1",
        note="依据过期",
    )
    assert rejected["state"] == "rejected"
    assert rejected["decided_by"] == "lead-1"
    assert rejected["decision_note"] == "依据过期"

    # rejecting twice is idempotent (no second event)
    again = proposals.reject(
        db_conn,
        domain_key="dom-resubmit",
        proposal_id=first["id"],
        actor="lead-1",
        note="依据过期",
    )
    assert again["id"] == first["id"]
    assert proposal_event_count(db_conn, first["id"], "rejected") == 1

    with pytest.raises(ValueError, match="同键已驳回"):
        submit_company(db_conn, "dom-resubmit", evidence=evidence)

    second = submit_company(
        db_conn, "dom-resubmit", evidence={"citation": "新年报 p.3"}
    )
    assert second["id"] != first["id"]
    assert second["state"] == "pending"
    assert second["evidence"] == {"citation": "新年报 p.3"}
    assert proposals.count_pending(db_conn, domain_key="dom-resubmit") == 1
    assert len(
        proposals.list_proposals(db_conn, domain_key="dom-resubmit")
    ) == 2


# ----------------------------------------------------------- 自提自确认


def test_self_confirm_is_banned_and_admin_override_allows_it(db_conn):
    """The submitter cannot approve their own proposal; an explicit admin
    override can, and the override is stamped into the decision note."""
    domain = make_domain(db_conn, "dom-self")
    proposal = submit_company(db_conn, "dom-self", submitted_by="expert-1")

    with pytest.raises(PermissionError, match="提案人不得自提自确认"):
        proposals.confirm(
            db_conn,
            domain_key="dom-self",
            proposal_id=proposal["id"],
            actor="expert-1",
        )
    assert proposals.get(
        db_conn, domain_key="dom-self", proposal_id=proposal["id"]
    )["state"] == "pending"
    assert ku_count(db_conn, "dom-self") == 0

    confirmed = proposals.confirm(
        db_conn,
        domain_key="dom-self",
        proposal_id=proposal["id"],
        actor="expert-1",
        admin_override=True,
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decided_by"] == "expert-1"
    assert confirmed["decision_note"].startswith("[admin-override]")
    assert ku_count(db_conn, "dom-self", "company") == 1
    assert authoring_event_count(db_conn, domain["id"]) == 1


def test_admin_confirming_someone_elses_proposal_writes_no_override_tag(db_conn):
    """The override tag marks a waiver that actually happened.

    An admin confirming a proposal submitted by *another* identity never met the
    separation-of-duties rule, so stamping "[admin-override]" there would claim a
    waiver in the audit trail that did not occur. The note must stay empty.
    """
    make_domain(db_conn, "dom-other-author")
    proposal = submit_company(db_conn, "dom-other-author", submitted_by="expert-1")

    confirmed = proposals.confirm(
        db_conn,
        domain_key="dom-other-author",
        proposal_id=proposal["id"],
        actor="dev@local",
        admin_override=True,
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decision_note"] == ""
    events = proposals.events_for(db_conn, proposal_id=proposal["id"])
    # The event column stores NULL for "no note" (the proposal row stores '');
    # either way nothing may claim an override happened.
    assert not events[-1]["note"]


# ------------------------------------------------- 确认走内核唯一写路径


def test_confirm_writes_one_ku_through_the_kernel_and_one_event(db_conn):
    """Confirmation produces a real KU with operator provenance and exactly
    one 'confirmed' transition; confirming again is a no-op."""
    domain = make_domain(db_conn, "dom-confirm")
    proposal = submit_company(db_conn, "dom-confirm", submitted_by="expert-1")

    confirmed = proposals.confirm(
        db_conn, domain_key="dom-confirm", proposal_id=proposal["id"], actor="lead-1"
    )
    assert confirmed["state"] == "confirmed"
    assert confirmed["decided_by"] == "lead-1"
    assert confirmed["decision_note"] == ""

    unit = db_conn.execute(
        "SELECT kind, namespace, external_key, body, tier, provenance "
        "FROM knowledge_units WHERE namespace = %s",
        ("dom-confirm",),
    ).fetchone()
    assert unit["kind"] == "company"
    assert unit["external_key"] == "co-1"
    assert unit["body"] == "某公司条目"
    assert unit["tier"] == "raw"
    assert unit["provenance"] == {"operator": "lead-1", "via": "authoring"}

    # the kernel wrote its own append-only event
    assert authoring_event_count(db_conn, domain["id"]) == 1

    events = proposals.events_for(db_conn, proposal_id=proposal["id"])
    assert [e["to_state"] for e in events] == ["pending", "confirmed"]
    assert events[1]["actor"] == "lead-1"
    assert events[1]["from_state"] == "pending"

    # idempotent second confirm: no second KU, no second event
    second = proposals.confirm(
        db_conn, domain_key="dom-confirm", proposal_id=proposal["id"], actor="lead-1"
    )
    assert second["id"] == proposal["id"]
    assert second["state"] == "confirmed"
    assert ku_count(db_conn, "dom-confirm") == 1
    assert proposal_event_count(db_conn, proposal["id"], "confirmed") == 1
    assert proposals.count_pending(db_conn, domain_key="dom-confirm") == 0


def test_confirm_relationship_uses_the_relationship_kernel_path(db_conn):
    """A relationship-kind proposal lands as a relationship KU with the
    kernel's deterministic key (endpoints read from the evidence payload)."""
    domain = make_domain(db_conn, "dom-rel")
    proposal = proposals.submit(
        db_conn,
        domain_key="dom-rel",
        source="market-feed",
        kind="belongs_to",
        external_key="co-1->belongs_to:grp-1",
        body="归属关系",
        evidence={"from_key": "co-1", "to_key": "grp-1", "citation": "公告"},
        submitted_by="expert-1",
    )

    proposals.confirm(
        db_conn, domain_key="dom-rel", proposal_id=proposal["id"], actor="lead-1"
    )

    row = db_conn.execute(
        "SELECT kind, external_key, attrs FROM knowledge_units WHERE namespace = %s",
        ("dom-rel",),
    ).fetchone()
    assert row["kind"] == "belongs_to"
    assert row["external_key"] == "co-1->belongs_to:grp-1"
    assert row["attrs"]["from_key"] == "co-1"
    assert row["attrs"]["to_key"] == "grp-1"
    assert authoring_event_count(db_conn, domain["id"]) == 1


# --------------------------------------------------------------- 词表外


def test_confirm_out_of_vocabulary_kind_writes_nothing(db_conn):
    """A kind in neither vocabulary is refused naming both lists and the
    anchored template version, before any KU or transition is written."""
    domain = make_domain(db_conn, "dom-oov")
    proposal = submit_company(db_conn, "dom-oov", external_key="co-x")
    # Move the proposal to an unvetted kind through the inbox (submission is
    # permissive; only confirmation gates the vocabulary).
    db_conn.execute(
        "UPDATE domain_proposals SET kind = 'gadget' WHERE id = %s",
        (proposal["id"],),
    )
    db_conn.commit()

    with pytest.raises(ValueError) as exc:
        proposals.confirm(
            db_conn, domain_key="dom-oov", proposal_id=proposal["id"], actor="lead-1"
        )
    message = str(exc.value)
    assert "不在模板 v1 词表内" in message
    assert "entity_types" in message and "relationship_kinds" in message
    assert "'company'" in message
    assert "'belongs_to'" in message

    assert ku_count(db_conn, "dom-oov") == 0
    assert authoring_event_count(db_conn, domain["id"]) == 0
    assert proposals.get(
        db_conn, domain_key="dom-oov", proposal_id=proposal["id"]
    )["state"] == "pending"
    assert proposal_event_count(db_conn, proposal["id"]) == 1  # submit only


# --------------------------------------------------------------- 跨域隔离


def test_cross_domain_proposal_is_invisible_and_undecidable(db_conn):
    """Domain B's key can neither read nor decide a proposal that lives in A,
    and an unknown domain key fails closed."""
    make_two_domains(db_conn, "dom-a", "dom-b")
    proposal = submit_company(db_conn, "dom-a")

    assert proposals.get(
        db_conn, domain_key="dom-b", proposal_id=proposal["id"]
    ) is None
    assert proposals.list_proposals(db_conn, domain_key="dom-b") == []
    assert proposals.count_pending(db_conn, domain_key="dom-b") == 0

    with pytest.raises(ValueError, match="not found in domain 'dom-b'"):
        proposals.confirm(
            db_conn, domain_key="dom-b", proposal_id=proposal["id"], actor="lead-1"
        )
    with pytest.raises(ValueError, match="not found in domain 'dom-b'"):
        proposals.reject(
            db_conn,
            domain_key="dom-b",
            proposal_id=proposal["id"],
            actor="lead-1",
            note="不属于本域",
        )

    # a domain key that does not exist is refused on the read side too
    with pytest.raises(ValueError, match="domain 'dom-missing' not found"):
        proposals.get(db_conn, domain_key="dom-missing", proposal_id=proposal["id"])

    # A's own key still sees it, untouched
    assert proposals.get(
        db_conn, domain_key="dom-a", proposal_id=proposal["id"]
    )["state"] == "pending"
