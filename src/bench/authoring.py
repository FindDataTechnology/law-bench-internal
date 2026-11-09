"""Expert authoring entry points over the kernel knowledge-unit store.

Every authoring write goes through :func:`src.bench.store.upsert_knowledge_unit`
(the single ontology write path): the domain key is the KU namespace, the kind
is gated against the vocabulary of the exact template version the domain is
anchored to, the first tier is ``raw``, and the operator lands in the
provenance. Each write appends one row to ``authoring_events`` (append-only:
no code path ever updates or deletes an event row), so the change trail stays
replayable.

Domain isolation is enforced here, at the entry points: every write and read
first resolves the domain (unknown key refused), then uses its key as the
namespace, so cross-domain content can never leak through this module.

Key conventions locked in this module are distribution-contract anchors:

- ``RELATIONSHIP_KEY_TEMPLATE`` is the deterministic external-key convention
  for relationship units. Downstream publishing consumers derive relationship
  identity from this key; changing it breaks identity alignment with
  already-published data.

Style: borrowed connection (never opened or closed here), ``%s`` placeholders,
one ``conn.commit()`` at the end of each write, JSONB via ``json.dumps``/
``json.loads``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from . import store, templates, workspaces

# Distribution-contract anchor (see module docstring): the deterministic
# external-key convention for relationship units. Do not change it.
RELATIONSHIP_KEY_TEMPLATE = "{from_key}->{kind}:{to_key}"

# Vocabularies mirrored by the CHECK constraints on authoring_events /
# authoring_tasks (see src/bench/workspace_store.py::WORKSPACE_SCHEMA).
EVENT_OPS = ("create", "update", "delete")
TASK_STATUSES = ("pending", "in_progress", "done", "cancelled")

_EVENT_COLS = (
    "id, domain_id, unit_kind, unit_key, op, before, after, operator, via, created_at"
)
_EVENT_KEYS = (
    "id",
    "domain_id",
    "unit_kind",
    "unit_key",
    "op",
    "before",
    "after",
    "operator",
    "via",
    "created_at",
)

_TASK_COLS = (
    "id, domain_id, assignee, title, detail, target_kind, target_key, "
    "status, transitions, created_by, created_at, updated_at"
)
_TASK_KEYS = (
    "id",
    "domain_id",
    "assignee",
    "title",
    "detail",
    "target_kind",
    "target_key",
    "status",
    "transitions",
    "created_by",
    "created_at",
    "updated_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _copy_unit(unit: dict) -> dict:
    """Deep-ish copy of a KU dict (JSON round-trip) so an event snapshot can
    never alias the live row dict."""
    return json.loads(json.dumps(unit))


def _event_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _EVENT_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "unit_kind": values[2],
        "unit_key": values[3],
        "op": values[4],
        "before": _decode_jsonb(values[5]),
        "after": _decode_jsonb(values[6]),
        "operator": values[7],
        "via": values[8],
        "created_at": _iso(values[9]),
    }


def _task_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _TASK_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "assignee": values[2],
        "title": values[3],
        "detail": values[4],
        "target_kind": values[5],
        "target_key": values[6],
        "status": values[7],
        "transitions": _decode_jsonb(values[8]),
        "created_by": values[9],
        "created_at": _iso(values[10]),
        "updated_at": _iso(values[11]),
    }


# ------------------------------------------------------------------ helpers


def _load_domain(conn: Any, *, domain_key: str) -> dict:
    """Resolve the domain or refuse the operation (fail-closed isolation)."""
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    return domain


def _gate_kind(conn: Any, *, domain: dict, kind: str, vocab_key: str) -> None:
    """Check ``kind`` against the domain's anchored template vocabulary.

    The vocabulary lives in the domain's data (the template row the domain was
    instantiated from); this gate only reads it, it does not own it.
    """
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    if tmpl is None:
        raise ValueError(
            f"domain {domain['key']!r} anchors template id "
            f"{domain['template_id']!r}, which does not exist"
        )
    schema = tmpl["schema"]
    if not isinstance(schema, dict):
        raise ValueError(
            f"domain {domain['key']!r} template schema is not a dict; "
            f"cannot check the {vocab_key} vocabulary"
        )
    vocab = schema.get(vocab_key)
    if not isinstance(vocab, list) or not vocab:
        raise ValueError(
            f"domain {domain['key']!r} template schema has no usable "
            f"{vocab_key} vocabulary"
        )
    if kind not in vocab:
        raise ValueError(
            f"kind {kind!r} is not in the {vocab_key} vocabulary of domain "
            f"{domain['key']!r}; allowed kinds: {vocab}"
        )


def _vocabulary(conn: Any, *, domain: dict, key: str) -> list[str]:
    """The declared vocabulary list for ``key`` (``[]`` when unusable).

    Read-only sibling of :func:`_gate_kind`: the pickers and the importer need
    the list itself, not a pass/fail verdict, and they must read it from the
    same template row the gate uses.
    """
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    vocab = schema.get(key) if isinstance(schema, dict) else None
    return [str(v) for v in vocab] if isinstance(vocab, list) else []


def _record_event(
    conn: Any,
    *,
    domain_id: int,
    unit_kind: str,
    unit_key: str,
    op: str,
    before: Optional[dict],
    after: Optional[dict],
    operator: str,
    via: str = "authoring",
) -> dict:
    """Append one change event (no commit -- the caller owns the transaction)."""
    cur = conn.execute(
        f"INSERT INTO authoring_events "
        f"(domain_id, unit_kind, unit_key, op, before, after, operator, via) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_EVENT_COLS}",
        (
            domain_id,
            unit_kind,
            unit_key,
            op,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            operator,
            via,
        ),
    )
    return _event_to_dict(cur.fetchone())


def _commit_with_event(
    conn: Any,
    *,
    domain: dict,
    kind: str,
    external_key: str,
    op: str,
    before: Optional[dict],
    after: Optional[dict],
    operator: str,
) -> None:
    """Append the change event, then commit once.

    The event insert shares the write's transaction: if it raises, the
    exception propagates to the caller with nothing further committed (the
    transaction is rolled back so the connection stays usable).
    """
    try:
        _record_event(
            conn,
            domain_id=domain["id"],
            unit_kind=kind,
            unit_key=external_key,
            op=op,
            before=before,
            after=after,
            operator=operator,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    conn.commit()


def _create_unit(
    conn: Any,
    *,
    domain: dict,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict],
    attrs: Optional[dict],
    vocab_key: str,
) -> dict:
    """Shared create path: vocabulary gate, KU upsert, append-only event."""
    _gate_kind(conn, domain=domain, kind=kind, vocab_key=vocab_key)
    # The op is decided by prior existence, not by the upsert result: the KU
    # upsert cannot distinguish create from update (ON CONFLICT DO UPDATE).
    existed = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )
    written = store.upsert_knowledge_unit(
        conn,
        kind=kind,
        external_key=external_key,
        body=body,
        namespace=domain["key"],
        tags=tags,
        attrs=attrs,
        tier="raw",
        provenance={"operator": operator, "via": "authoring"},
        commit=False,
    )
    _commit_with_event(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        op="create" if existed is None else "update",
        before=_copy_unit(existed) if existed is not None else None,
        after=written,
        operator=operator,
    )
    return written


def _soft_delete_unit(
    conn: Any, *, domain: dict, kind: str, external_key: str, operator: str
) -> dict:
    """Shared delete path (soft delete): flag the KU, record the event.

    Content and metadata are preserved unchanged so the event stream stays
    replayable; only ``tags["deleted"]`` and the provenance stamp move.
    """
    prior = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )
    if prior is None:
        raise ValueError(
            f"unit {kind!r}/{external_key!r} not found in domain {domain['key']!r}"
        )
    tags = dict(prior["tags"] or {})
    tags["deleted"] = True
    provenance = dict(prior["provenance"] or {})
    provenance["operator"] = operator
    provenance["via"] = "authoring"
    written = store.upsert_knowledge_unit(
        conn,
        kind=kind,
        external_key=external_key,
        body=prior["body"],
        namespace=domain["key"],
        tags=tags,
        attrs=prior["attrs"],
        tier=prior["tier"],
        source_path=prior["source_path"],
        provenance=provenance,
        commit=False,
    )
    _commit_with_event(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        op="delete",
        before=_copy_unit(prior),
        after=None,
        operator=operator,
    )
    return written


# -------------------------------------------------------------------- units


def authoring_create_unit(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
) -> dict:
    """Create (or, if the key already exists, effectively update) one unit.

    The kind must be in the domain's ``entity_types`` vocabulary; anything
    else is refused with the allowed vocabulary named, before anything is
    written (no KU, no event). Returns the stored KU dict.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return _create_unit(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        body=body,
        operator=operator,
        tags=tags,
        attrs=attrs,
        vocab_key="entity_types",
    )


def authoring_create_units(
    conn: Any,
    *,
    domain_key: str,
    units: list[dict],
    operator: str,
) -> list[dict]:
    """Create many units in **one** transaction: all of them or none.

    ``authoring_create_unit`` commits per unit, which is right for a human
    editing one row and wrong for a batch read out of a corpus: half a document's
    articles in the ontology is a state nobody asked for and nobody can explain
    afterwards. Here every kind is gated before the first write, all rows share
    one transaction, and a failure anywhere rolls the whole batch back.

    Each unit is ``{kind, external_key, body, tags?, attrs?}``. Duplicate keys
    inside one batch are refused up front — two rows writing the same key would
    make "which one landed" depend on ordering.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    if not units:
        return []
    seen: set[tuple[str, str]] = set()
    for unit in units:
        kind, key = unit.get("kind"), unit.get("external_key")
        if not kind or not key:
            raise ValueError("every unit needs both 'kind' and 'external_key'")
        if (kind, key) in seen:
            raise ValueError(f"duplicate key in one batch: {kind!r}/{key!r}")
        seen.add((kind, key))
        _gate_kind(conn, domain=domain, kind=kind, vocab_key="entity_types")

    written: list[dict] = []
    try:
        for unit in units:
            prior = store.get_knowledge_unit(
                conn, kind=unit["kind"], external_key=unit["external_key"],
                namespace=domain["key"],
            )
            row = store.upsert_knowledge_unit(
                conn,
                kind=unit["kind"],
                external_key=unit["external_key"],
                body=unit.get("body") or "",
                namespace=domain["key"],
                tags=unit.get("tags"),
                attrs=unit.get("attrs"),
                tier="raw",
                provenance={"operator": operator, "via": "authoring"},
                commit=False,
            )
            _record_event(
                conn,
                domain_id=domain["id"],
                unit_kind=unit["kind"],
                unit_key=unit["external_key"],
                op="create" if prior is None else "update",
                before=_copy_unit(prior) if prior is not None else None,
                after=row,
                operator=operator,
            )
            written.append(row)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    conn.commit()
    return written


def authoring_update_unit(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    external_key: str,
    body: str,
    operator: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
) -> dict:
    """Update one existing unit; the unit must already exist.

    The event carries the full prior state as ``before`` and the written state
    as ``after``. Returns the stored KU dict.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    _gate_kind(conn, domain=domain, kind=kind, vocab_key="entity_types")
    prior = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )
    if prior is None:
        raise ValueError(
            f"unit {kind!r}/{external_key!r} not found in domain {domain_key!r}"
        )
    written = store.upsert_knowledge_unit(
        conn,
        kind=kind,
        external_key=external_key,
        body=body,
        namespace=domain["key"],
        tags=tags,
        attrs=attrs,
        tier="raw",
        provenance={"operator": operator, "via": "authoring"},
        commit=False,
    )
    _commit_with_event(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        op="update",
        before=_copy_unit(prior),
        after=written,
        operator=operator,
    )
    return written


def authoring_delete_unit(
    conn: Any, *, domain_key: str, kind: str, external_key: str, operator: str
) -> dict:
    """Soft-delete one existing unit (keeps the row, flags it deleted).

    Returns the updated KU dict (``tags["deleted"] is True``).
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return _soft_delete_unit(
        conn, domain=domain, kind=kind, external_key=external_key, operator=operator
    )


def authoring_get_unit(
    conn: Any, *, domain_key: str, kind: str, external_key: str
) -> Optional[dict]:
    """Fetch one unit in the domain's namespace; ``None`` when missing.

    Soft-deleted units are returned as-is (``tags["deleted"]`` tells the
    caller); list views are the ones that filter them out.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )


def authoring_list_units(
    conn: Any,
    *,
    domain_key: str,
    kind: Optional[str] = None,
    tier: Optional[str] = None,
    query: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 200,
) -> list[dict]:
    """List the domain's units, most recently updated first.

    Soft-deleted units are excluded unless ``include_deleted`` is set. The
    filtering happens in SQL rather than in Python so a ``limit`` means "the
    newest N matching units" — filtering after a LIMIT returned a short page
    that looked like an empty domain.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    return store.list_knowledge_units(
        conn,
        kind=kind,
        tier=tier,
        query=query,
        namespace=domain["key"],
        include_deleted=include_deleted,
        limit=limit,
    )


def authoring_live_entities(
    conn: Any, *, domain_key: str, limit: int = 1000
) -> list[dict]:
    """The domain's entity units that are not soft-deleted.

    This is the candidate list a relationship picker offers and the set a bulk
    import resolves its endpoints against — one function so the two cannot
    disagree about which entities "exist".
    """
    domain = _load_domain(conn, domain_key=domain_key)
    rows = store.list_knowledge_units(
        conn, namespace=domain["key"], include_deleted=False, limit=limit
    )
    entities = set(_vocabulary(conn, domain=domain, key="entity_types") or ())
    return [u for u in rows if u["kind"] in entities]


def authoring_live_keys(
    conn: Any,
    *,
    domain_key: str,
    kind: Optional[str] = None,
    prefix: Optional[str] = None,
) -> set[str]:
    """Every live unit key in the domain — optionally one kind, one key prefix.

    Deliberately *not* ``authoring_live_entities``: that one is capped at 1000
    rows because it feeds a picker, and reading it as "these exist" silently
    stops being true past the cap. Measured 2026-11-10: adopting a 1,208-article
    code read the first 1000 units, concluded the rest were missing every time,
    and rewrote the same 200 articles until the cap — the loop could never
    finish. A set membership question needs the whole set.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    sql = (
        "SELECT external_key FROM knowledge_units "
        "WHERE namespace = %s AND (tags->>'deleted') IS NULL"
    )
    params: list[Any] = [domain["key"]]
    if kind:
        sql += " AND kind = %s"
        params.append(kind)
    if prefix:
        sql += " AND external_key LIKE %s"
        params.append(prefix.replace("%", r"\%").replace("_", r"\_") + "%")
    return {r["external_key"] for r in conn.execute(sql, tuple(params)).fetchall()}


def authoring_unit_detail(
    conn: Any, *, domain_key: str, kind: str, external_key: str
) -> Optional[dict]:
    """One unit plus the relationships that touch it.

    A relationship stores its endpoints in ``attrs`` (``from_key``/``to_key``),
    so "what is this entity connected to" is a scan over the relationship units
    in the same namespace. Relations whose other end is soft-deleted are still
    returned with ``dangling=True`` — hiding them would make a deleted entity
    look unreferenced.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    unit = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=domain["key"]
    )
    if unit is None:
        return None
    rel_kinds = set(_vocabulary(conn, domain=domain, key="relationship_kinds") or ())
    rels = [
        u
        for u in store.list_knowledge_units(conn, namespace=domain["key"], limit=2000)
        if u["kind"] in rel_kinds
        and external_key
        in (
            (u.get("attrs") or {}).get("from_key"),
            (u.get("attrs") or {}).get("to_key"),
        )
    ]
    live = {
        u["external_key"]
        for u in store.list_knowledge_units(
            conn, namespace=domain["key"], include_deleted=False, limit=2000
        )
    }
    related = []
    for rel in rels:
        attrs = rel.get("attrs") or {}
        other = attrs.get("to_key") if attrs.get("from_key") == external_key else attrs.get("from_key")
        related.append(
            {
                "kind": rel["kind"],
                "external_key": rel["external_key"],
                "from_key": attrs.get("from_key"),
                "to_key": attrs.get("to_key"),
                "other": other,
                "deleted": bool((rel.get("tags") or {}).get("deleted")),
                "dangling": other not in live,
            }
        )
    return {"unit": unit, "related": related,
            "deleted": bool((unit.get("tags") or {}).get("deleted"))}


# ------------------------------------------------------------------- events


def authoring_events_for(
    conn: Any,
    *,
    domain_id: int,
    unit_kind: Optional[str] = None,
    unit_key: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """The domain's change trail, newest first; filters are optional."""
    where, params = ["domain_id = %s"], [domain_id]
    if unit_kind is not None:
        where.append("unit_kind = %s")
        params.append(unit_kind)
    if unit_key is not None:
        where.append("unit_key = %s")
        params.append(unit_key)
    sql = (
        f"SELECT {_EVENT_COLS} FROM authoring_events "
        f"WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC LIMIT %s"
    )
    params.append(limit)
    cur = conn.execute(sql, params)
    return [_event_to_dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------ relationships


def relationship_external_key(*, from_key: str, kind: str, to_key: str) -> str:
    """Deterministic external key for a relationship unit.

    This key convention is a distribution-contract anchor: downstream
    publishing consumers derive relationship identity from it, so changing it
    breaks identity alignment with already-published data.
    """
    return RELATIONSHIP_KEY_TEMPLATE.format(from_key=from_key, kind=kind, to_key=to_key)


def authoring_create_relationship(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    from_key: str,
    to_key: str,
    body: str,
    operator: str,
    attrs: Optional[dict] = None,
) -> dict:
    """Create a relationship unit between two endpoint keys.

    The kind must be in the domain's ``relationship_kinds`` vocabulary (not
    ``entity_types``). The external key is derived via
    :func:`relationship_external_key`, and the structured endpoints are stored
    in ``attrs`` alongside any caller-supplied fields (the structural
    ``from``/``to`` values always win so identity cannot be corrupted through
    the payload). Returns the stored KU dict.
    """
    domain = _load_domain(conn, domain_key=domain_key)
    external_key = relationship_external_key(from_key=from_key, kind=kind, to_key=to_key)
    merged_attrs = dict(attrs or {})
    merged_attrs.update(
        {"from": from_key, "to": to_key, "from_key": from_key, "to_key": to_key}
    )
    return _create_unit(
        conn,
        domain=domain,
        kind=kind,
        external_key=external_key,
        body=body,
        operator=operator,
        tags=None,
        attrs=merged_attrs,
        vocab_key="relationship_kinds",
    )


def authoring_delete_relationship(
    conn: Any,
    *,
    domain_key: str,
    kind: str,
    from_key: str,
    to_key: str,
    operator: str,
) -> dict:
    """Soft-delete a relationship unit by its endpoints. Returns the KU dict."""
    domain = _load_domain(conn, domain_key=domain_key)
    external_key = relationship_external_key(from_key=from_key, kind=kind, to_key=to_key)
    return _soft_delete_unit(
        conn, domain=domain, kind=kind, external_key=external_key, operator=operator
    )


# -------------------------------------------------------------------- tasks


def authoring_create_task(
    conn: Any,
    *,
    domain_id: int,
    assignee: str,
    title: str,
    detail: Optional[str],
    target_kind: Optional[str],
    target_key: Optional[str],
    created_by: str,
) -> dict:
    """Create one work task in status ``pending`` with the first trail entry."""
    if not assignee or not title:
        raise ValueError("assignee and title are required")
    entry = {"from": None, "to": "pending", "by": created_by, "at": _now()}
    cur = conn.execute(
        f"INSERT INTO authoring_tasks "
        f"(domain_id, assignee, title, detail, target_kind, target_key, "
        f"status, transitions, created_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_TASK_COLS}",
        (
            domain_id,
            assignee,
            title,
            detail,
            target_kind,
            target_key,
            "pending",
            json.dumps([entry]),
            created_by,
        ),
    )
    task = _task_to_dict(cur.fetchone())
    conn.commit()
    return task


def authoring_list_tasks(
    conn: Any,
    *,
    domain_id: int,
    assignee: Optional[str] = None,
    status: Optional[str] = None,
) -> list[dict]:
    """List the domain's tasks, newest first; filters are optional."""
    where, params = ["domain_id = %s"], [domain_id]
    if assignee is not None:
        where.append("assignee = %s")
        params.append(assignee)
    if status is not None:
        where.append("status = %s")
        params.append(status)
    cur = conn.execute(
        f"SELECT {_TASK_COLS} FROM authoring_tasks "
        f"WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC",
        params,
    )
    return [_task_to_dict(r) for r in cur.fetchall()]


def authoring_get_task(conn: Any, *, task_id: int) -> Optional[dict]:
    """Fetch one task; ``None`` when missing."""
    cur = conn.execute(
        f"SELECT {_TASK_COLS} FROM authoring_tasks WHERE id = %s", (task_id,)
    )
    row = cur.fetchone()
    return _task_to_dict(row) if row else None


def authoring_transition_task(
    conn: Any, *, task_id: int, to_status: str, actor: str
) -> dict:
    """Move a task to ``to_status`` and append the trail entry.

    One statement updates ``status``, ``updated_at`` and appends the
    ``transitions`` entry (``{"from", "to", "by", "at"}``), so the trail can
    never diverge from the status. Unknown task or unknown status is refused.
    """
    if to_status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {list(TASK_STATUSES)}")
    current = authoring_get_task(conn, task_id=task_id)
    if current is None:
        raise ValueError(f"task {task_id} not found")
    moment = _now()
    entry = {"from": current["status"], "to": to_status, "by": actor, "at": moment}
    cur = conn.execute(
        f"UPDATE authoring_tasks SET status = %s, updated_at = %s, "
        f"transitions = transitions || %s::jsonb "
        f"WHERE id = %s RETURNING {_TASK_COLS}",
        (to_status, moment, json.dumps([entry]), task_id),
    )
    task = _task_to_dict(cur.fetchone())
    conn.commit()
    return task
