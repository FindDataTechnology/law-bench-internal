"""Client-agnostic promotion machine for external-registry entities.

An *external registry* (an upstream semantic layer, e.g. a wire entity graph)
is the **seed source**: every entity/relation it declares already owns a
stable primary key, and those keys are the reference by which the imported
material can be traced back. It is *not* the authority over published
ontology — that is the platform (``bench-wire-seam``). The bench platform
keeps **no second identity store** — it imports registry declarations, once,
into knowledge units whose upsert identity is ``(kind, namespace,
external_key)`` with ``external_key`` being the registry's own stable id, and
runs them through a human review ladder:

    bronze (machine pre-annotation, the landing tier of a graph seed import)
      -> silver (annotations/tags completed by an operator)
      -> gold   (human verification passed; requires a reviewer identity)

Rules enforced here (contract 柏讯实体升格契约, bench-platform spec):

- Import is idempotent: re-fetching an unchanged registry mutates no rows (no
  ``updated_at`` bump, no tier/provenance churn). Content changes update the
  mirrored body/attrs only — they never demote a promoted unit.
- The import is one-shot, not a sync loop: nothing here schedules it, and the
  platform must not stall when the external registry stops changing.
- Tier moves one way, one adjacent step at a time: bronze→silver,
  silver→gold. Gold never demotes on its own; a demotion is only possible as
  an explicit admin action (``force=True`` + a reviewer stamp) and otherwise
  raises :class:`TierTransitionError` (routes map it to HTTP 409).
- Promotion to gold requires a reviewer identity written into the unit's
  provenance (``review.reviewer`` / ``review.at`` / ``review.note``). Missing
  reviewer => refused. The reviewer is always the session identity of the
  operator — this module only ever receives it as an argument; the web layer
  must never accept it from a form field.
- ``export_gold`` assembles the registry writeback payload: the identity key,
  the ``tier``/``sensitivity`` markers, and the mirrored registry-field
  snapshot so the connector can address the upstream record. NOTE (contract
  gap, discovered from the real upstream entity API): the upstream CRUD
  surface accepts only registry-native fields (name/dataset/pk_columns/
  description/display metadata); it has NO writable ``tier``/``sensitivity``
  column today. The payload shape below is therefore *documented*, and the
  connector writeback encodes the promotion mark into a writable field until
  the upstream side adds first-class tier/sensitivity (see the internal
  wire-connector README).
- ``run_writeback`` calls an injected ``writeback_fn`` per gold payload. A
  payload is marked ``written_back`` ONLY when the call returns without
  raising; failures are recorded per unit and never abort the other units, and
  the result lists (succeeded/failed/skipped) reflect what actually happened.
  The registry key is the writeback idempotency key: a unit already marked
  written back is skipped on rerun unless ``force=True`` re-sends it (the
  idempotency key rides in the payload so an upstream that supports it can
  dedupe).

Traceability: every gold unit carries, in provenance, the registry origin
(``synced_from`` / ``synced_at``), the review stamp, and the writeback receipt
— so a gold unit can always be traced back to its source declaration, its
reviewer, and its writeback outcome.

The module is domain-neutral (kernel) and depends only on the sibling
``store`` and ``tiers`` modules of this package plus the standard library.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import store
from .tiers import TIER_RANK

# --- vocabulary -------------------------------------------------------------

#: Knowledge-unit kinds this machine syncs and promotes.
#:
#: Expanded 2026-11-21 (change ``add-agent-autonomous-iteration``): confirmation
#: now produces ``silver`` for **every** kind a proposal can carry, so the ladder
#: must reach all of them. It previously listed only entity/relation, which meant
#: a confirmed ``dataset``/``crosswalk``/``clause`` unit landed at silver and could
#: never climb — the ladder stopped one step short for half the ontology.
#
#: The sync/promote entry has its own notion of "which kind" (``_get_unit`` reads
#: the raw kind column), so widening this is a permission change, not a schema one.
KIND_ENTITY = "entity"
KIND_RELATION = "relation"
#: Every kind ``proposal_lanes`` can confirm. Kept as a literal tuple rather than
#: importing the proposal module (promotion must not depend on the inbox); the
#: one-way dependency is asserted by ``tests/test_agent_autonomous_iteration.py``.
PROMOTABLE_KINDS = (
    KIND_ENTITY, KIND_RELATION, "crosswalk", "dataset", "concept", "clause",
    "law", "agency", "document", "defines", "issued_by", "superseded_by",
    "n:1", "1:n", "m:n", "has_field", "references",
)

#: The one-way promotion ladder.
#:
#: ``raw`` joined on 2026-11-21: bulk ingest used to be a terminal tier, so a
#: confirmed unit could never climb out of it, and 5,283 raw units in production
#: had no ascent path at all. ``bronze`` stays **outside** the main ladder — it
#: means "machine self-eval, failure analysis only", and letting it ascend would
#: turn self-eval into promotable content, which the tier guards exist to prevent.
CHAIN = ("raw", "silver", "gold")
#: Graph-sync units still land at bronze and are the one kind that starts above
#: raw; ``SYNC_TIER`` documents the entry tier for that path.
SYNC_TIER = "bronze"

#: Sensitivity marker attached to gold payloads for the registry's ACL layer.
#: Kept as an attribute of the *promotion decision* (provenance), never of the
#: mirrored registry attrs, so a re-sync cannot erase it.
DEFAULT_SENSITIVITY = "internal"
SENSITIVITY_LEVELS = ("public", "internal", "confidential")


class TierTransitionError(ValueError):
    """Illegal tier move (demotion, skipped step, same-tier re-promotion)."""


class UnitNotFoundError(KeyError):
    """The (kind, namespace, external_key) triple is not in the unit store."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so anything we persist into JSONB is storable."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# --- registry snapshot rendering --------------------------------------------


def entity_external_key(node: dict) -> str:
    """Stable identity key for a registry entity node (the registry's own id)."""
    if "id" not in node or node["id"] is None:
        raise ValueError("registry entity node has no stable 'id'")
    return str(node["id"])


def relation_external_key(edge: dict) -> str:
    """Stable identity key for a registry relation edge (the registry's own id)."""
    if "id" not in edge or edge["id"] is None:
        raise ValueError("registry relation edge has no stable 'id'")
    return str(edge["id"])


def render_entity_body(node: dict) -> str:
    """Deterministic one-line text mirror of an entity node."""
    ds = node.get("dataset") or {}
    pk = ",".join(node.get("pk_columns") or [])
    return (
        f"entity {node.get('name')} | dataset "
        f"{ds.get('key') or ds.get('id')} rows={ds.get('row_count')} pk=[{pk}]"
    )


def render_relation_body(edge: dict) -> str:
    """Deterministic one-line text mirror of a relation edge (the four-tuple)."""
    return (
        f"relation {edge.get('from_entity_id')}.{edge.get('from_column')} "
        f"-({edge.get('kind')})-> "
        f"{edge.get('to_entity_id')}.{edge.get('to_column')}"
    )


# --- sync ---------------------------------------------------------------------


def _get_unit(conn: Any, *, kind: str, external_key: str, namespace: str) -> dict:
    unit = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=namespace
    )
    if unit is None:
        raise UnitNotFoundError(
            f"no {kind} unit {namespace!r}/{external_key!r} in the store"
        )
    return unit


def _merge_provenance(old: dict, new: dict) -> dict:
    """Shallow-merge provenance; promotion/review/writeback records survive a
    re-sync (sync-owned keys refresh, operator-owned keys are untouched)."""
    merged = {**old}
    for key, value in new.items():
        if key in ("synced_from", "synced_at") or key not in merged:
            merged[key] = value
    return merged


def _sync_one(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    body: str,
    attrs: dict,
    result: dict,
) -> None:
    existing = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=namespace
    )
    stamp = {"synced_from": namespace, "synced_at": _now()}
    if existing is None:
        store.upsert_knowledge_unit(
            conn,
            kind=kind,
            external_key=external_key,
            namespace=namespace,
            body=body,
            tags={"registry": namespace, "origin": "graph_sync"},
            attrs=attrs,
            tier=SYNC_TIER,
            provenance=stamp,
        )
        result["created"].append(external_key)
        return
    if existing["body"] == body and existing["attrs"] == attrs:
        # Unchanged mirror: no write at all (idempotent — no updated_at bump).
        result["unchanged"].append(external_key)
        return
    # Content drifted upstream: refresh the mirror only. tier stays (never
    # demoted by sync), operator tags stay, provenance merges sync keys only.
    store.upsert_knowledge_unit(
        conn,
        kind=kind,
        external_key=external_key,
        namespace=namespace,
        body=body,
        tags=existing["tags"],
        attrs=attrs,
        tier=existing["tier"],
        source_path=existing["source_path"],
        provenance=_merge_provenance(existing["provenance"], stamp),
    )
    result["updated"].append(external_key)


def sync_graph(
    conn: Any,
    *,
    fetch_fn: Callable[[], dict],
    namespace: str,
) -> dict:
    """Import an external-registry entity graph into bronze knowledge units.

    **One-shot seed import, not a mirror.** This is the seed step of the
    promotion ladder (``bench-wire-seam``): run it to bring an external
    registry's declarations in as raw material, then let the platform's own
    authoring and review carry the work. It is deliberately *not* wired to a
    schedule, and it must not become one — the judge is dependency, not
    timers: the platform must not stall when the external registry stops
    changing.

    ``fetch_fn()`` must return ``{"nodes": [...], "edges": [...]}`` in the
    registry's graph shape (entity nodes with id/name/dataset summary/
    pk_columns; relation edges with the four-tuple + kind). Idempotent: an
    unchanged second import touches no rows.
    """
    if not namespace:
        raise ValueError("namespace is required")
    graph = fetch_fn() or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    result: dict = {
        "namespace": namespace,
        "nodes": len(nodes),
        "edges": len(edges),
        "created": [],
        "updated": [],
        "unchanged": [],
    }
    for node in nodes:
        _sync_one(
            conn,
            kind=KIND_ENTITY,
            external_key=entity_external_key(node),
            namespace=namespace,
            body=render_entity_body(node),
            attrs=dict(node),
            result=result,
        )
    for edge in edges:
        _sync_one(
            conn,
            kind=KIND_RELATION,
            external_key=relation_external_key(edge),
            namespace=namespace,
            body=render_relation_body(edge),
            attrs=dict(edge),
            result=result,
        )
    return result


# --- promotion ladder ---------------------------------------------------------


def _restamp(conn: Any, unit: dict, **overrides: Any) -> dict:
    """Re-upsert an existing unit with selective field overrides."""
    fields = {
        "kind": unit["kind"],
        "external_key": unit["external_key"],
        "namespace": unit["namespace"],
        "body": unit["body"],
        "tags": unit["tags"],
        "attrs": unit["attrs"],
        "tier": unit["tier"],
        "source_path": unit["source_path"],
        "provenance": unit["provenance"],
    }
    fields.update(overrides)
    return store.upsert_knowledge_unit(conn, **fields)


def annotate_unit(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
    reviewer: Optional[str] = None,
) -> dict:
    """Attach operator annotations (tags + attrs) to a mirrored unit.

    Annotation placement is sync-safe by construction: operator ``tags`` merge
    into the unit's tags and operator ``attrs`` into
    ``provenance.annotations`` — the mirrored ``attrs`` column itself always
    holds the *registry snapshot verbatim*, so the next ``sync_graph`` can
    overwrite it without losing any human annotation. Annotations do not
    change the tier; the silver step of the ladder is where the queue expects
    them to have been completed. The stamp of who annotated (``annotated_by``)
    is provenance-owned, separate from the mirror.
    """
    if kind not in PROMOTABLE_KINDS:
        raise ValueError(f"kind {kind!r} is not promotable by this machine")
    unit = _get_unit(conn, kind=kind, external_key=external_key, namespace=namespace)
    prov = dict(unit["provenance"])
    if reviewer:
        prov["annotated_by"] = reviewer
        prov["annotated_at"] = _now()
    if attrs:
        prov["annotations"] = {**(prov.get("annotations") or {}), **_json_safe(attrs)}
    updated = _restamp(
        conn,
        unit,
        tags={**unit["tags"], **(tags or {})},
        provenance=prov,
    )
    return updated


def promote_unit(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    to_tier: str,
    reviewer: Optional[str] = None,
    note: str = "",
    sensitivity: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Move one unit along the bronze→silver→gold ladder.

    - Only adjacent forward steps without ``force``: bronze→silver,
      silver→gold. Skipping a step or demoting raises
      :class:`TierTransitionError` (HTTP 409 at the route layer).
    - ``to_tier='gold'`` requires ``reviewer`` (the session identity —
      never a form field); missing reviewer raises ``ValueError`` and the
      unit stays untouched.
    - Demotion (gold→silver etc.) is refused unless ``force=True`` AND a
      ``reviewer`` is given, marking it an explicit admin action recorded in
      provenance (``demoted_by``).
    - The review stamp (reviewer / at / note / sensitivity) is persisted into
      provenance so every gold unit traces back to its human verification.
    """
    if kind not in PROMOTABLE_KINDS:
        raise ValueError(f"kind {kind!r} is not promotable by this machine")
    # Order matters: resolve the unit first so "already at that tier" wins over
    # "that tier is not on the ladder". Asking to stay put at `bronze` is the
    # former — and it must say so, or a caller reads "outside the ladder" as
    # "bronze units are unreachable" when they are reachable (bronze→silver).
    unit = _get_unit(conn, kind=kind, external_key=external_key, namespace=namespace)
    if (unit.get("tags") or {}).get("deleted") is True:
        # 软删单位不在阶梯上：队列已不列它（promotion_queue 同一条过滤），构造
        # URL 或旧页面表单也不该能把一条墓碑升回流通。
        raise TierTransitionError(
            f"unit {namespace!r}/{external_key!r} is soft-deleted; "
            "a tombstone cannot be promoted"
        )
    current = unit["tier"]
    if current == to_tier:
        raise TierTransitionError(f"unit already at tier {to_tier!r}")
    if to_tier not in CHAIN:
        raise TierTransitionError(
            f"tier {to_tier!r} is outside the promotion ladder {CHAIN}"
        )
    # ``bronze`` is the entry tier for graph-sync units and sits *outside* CHAIN
    # (self-eval must not be promotable content). It still needs a way in, or the
    # 10 synced units in production could never ascend: bronze -> silver is that
    # door, and it is the only step bronze may take.
    if current == "bronze":
        if to_tier != "silver":
            raise TierTransitionError(
                f"tier {current!r} 只能升到 'silver'（它是同步入口档，不在主阶梯上）；"
                f"要到 {to_tier!r} 请先升 silver"
            )
        step = 1
    else:
        step = CHAIN.index(to_tier) - CHAIN.index(current)
    moving_up = TIER_RANK[to_tier] < TIER_RANK[current]

    if moving_up:
        if step != 1:
            raise TierTransitionError(
                f"tier moves one adjacent step at a time: {current}→{to_tier} "
                "skips a step; verify at each tier before promoting"
            )
        if to_tier == "gold":
            if not reviewer:
                raise ValueError(
                    "gold promotion requires a reviewer identity (the session "
                    "operator stamp); refusing to promote unverified"
                )
            if sensitivity is not None and sensitivity not in SENSITIVITY_LEVELS:
                raise ValueError(
                    f"unknown sensitivity level {sensitivity!r}; "
                    f"expected one of {SENSITIVITY_LEVELS}"
                )
            prov = dict(unit["provenance"])
            prov["review"] = {
                "reviewer": reviewer,
                "at": _now(),
                "note": note,
            }
            prov["sensitivity"] = sensitivity or DEFAULT_SENSITIVITY
            return _restamp(conn, unit, tier="gold", provenance=prov)
        # bronze→silver: annotation step, operator stamp optional.
        prov = dict(unit["provenance"])
        if reviewer:
            prov.setdefault("silver_by", reviewer)
            prov["silver_at"] = _now()
        return _restamp(conn, unit, tier="silver", provenance=prov)

    # Moving down the ladder (demotion): explicit admin action only.
    if not force:
        raise TierTransitionError(
            f"{current}→{to_tier} would demote a {current} unit; tiers promote "
            "one way (bronze→silver→gold). Use force=True with a reviewer to "
            "record an explicit admin demotion."
        )
    if not reviewer:
        raise ValueError("an admin demotion requires a reviewer identity stamp")
    prov = dict(unit["provenance"])
    prov["demoted"] = {
        "by": reviewer,
        "at": _now(),
        "from": current,
        "to": to_tier,
        "note": note,
    }
    return _restamp(conn, unit, tier=to_tier, provenance=prov)


# --- gold export (registry writeback payloads) ----------------------------------


def export_gold(conn: Any, namespace: str, *, limit: int = 1000) -> list[dict]:
    """Assemble writeback payloads for every gold unit in ``namespace``.

    Payload shape (see module docstring for the contract-gap note — the
    upstream entity API mirrors registry-native fields only, no tier column):

        {
          "idempotency_key":   "<namespace>/<kind>/<external_key>",  # registry
          "registry_namespace": namespace,                           #   key is
          "kind":              "entity" | "relation",                # the
          "external_key":      "<registry stable id>",               # idempotency
          "tier":              "gold",                               # marker
          "sensitivity":       "public|internal|confidential",       # marker
          "registry_fields":   { ...node/edge snapshot... },         # addressable
          "review":            {"reviewer", "at", "note"} | None,    # trace
          "written_back":      bool,                                 # current state
        }
    """
    payloads: list[dict] = []
    for kind in PROMOTABLE_KINDS:
        for unit in store.list_knowledge_units(
            conn, kind=kind, namespace=namespace, tier="gold", limit=limit
        ):
            prov = unit["provenance"] or {}
            payloads.append(
                {
                    "idempotency_key": f"{namespace}/{kind}/{unit['external_key']}",
                    "registry_namespace": namespace,
                    "kind": kind,
                    "external_key": unit["external_key"],
                    "tier": "gold",
                    "sensitivity": prov.get("sensitivity", DEFAULT_SENSITIVITY),
                    "registry_fields": unit["attrs"],
                    "review": prov.get("review"),
                    "written_back": bool(prov.get("written_back")),
                }
            )
    return payloads


# --- writeback -------------------------------------------------------------------


def _record_writeback(conn: Any, unit: dict, *, ok: bool, receipt: Any, error: Any,
                      payload: dict) -> dict:
    """Persist one writeback outcome into the unit's provenance.

    Failure records the attempt but never marks the unit written back (contract:
    回写失败不误标已回写). Success marks ``written_back=True`` plus the receipt
    reference, keyed by the registry idempotency key.
    """
    prov = dict(unit["provenance"])
    attempt = {
        "at": _now(),
        "ok": ok,
        "idempotency_key": payload["idempotency_key"],
    }
    if ok:
        prov["written_back"] = True
        prov["written_back_at"] = attempt["at"]
        prov["writeback_idempotency_key"] = payload["idempotency_key"]
        prov["writeback_receipt"] = _json_safe(receipt)
    else:
        prov["written_back"] = False  # honest, explicit: NOT written back
        prov["last_writeback_error"] = str(error)
    prov["last_writeback"] = attempt
    return _restamp(conn, unit, provenance=prov)


def run_writeback(
    conn: Any,
    namespace: str,
    writeback_fn: Callable[[dict], Any],
    *,
    force: bool = False,
    limit: int = 1000,
) -> dict:
    """Push every gold payload in ``namespace`` back through ``writeback_fn``.

    - Per payload: call ``writeback_fn(payload)``. Return value (if any) is
      stored as the receipt reference; raising anything counts as failure.
    - Success marks the unit written back; failure keeps it un-marked with a
      recorded error — the rest of the batch still runs (no abort).
    - Idempotent by registry key: a unit already marked written back is
      *skipped* on rerun (no second push, so no duplicate rows upstream).
      ``force=True`` re-sends, with the idempotency key riding in the payload.
    - The returned dict states exactly what happened:
      ``{"succeeded": [...], "failed": [{..., "error"}], "skipped": [...],
         "counts": {...}}``.
    """
    payloads = export_gold(conn, namespace, limit=limit)
    succeeded: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []
    for payload in payloads:
        unit = _get_unit(
            conn,
            kind=payload["kind"],
            external_key=payload["external_key"],
            namespace=namespace,
        )
        if payload["written_back"] and not force:
            skipped.append(
                {
                    "kind": payload["kind"],
                    "external_key": payload["external_key"],
                    "reason": "already written back (registry key is the "
                              "idempotency key; force=True to re-send)",
                }
            )
            continue
        try:
            receipt = writeback_fn(payload)
        except Exception as exc:  # noqa: BLE001 — any error means "not written"
            _record_writeback(
                conn, unit, ok=False, receipt=None, error=exc, payload=payload
            )
            failed.append(
                {
                    "kind": payload["kind"],
                    "external_key": payload["external_key"],
                    "error": str(exc),
                }
            )
            continue
        _record_writeback(
            conn, unit, ok=True, receipt=receipt, error=None, payload=payload
        )
        succeeded.append(
            {
                "kind": payload["kind"],
                "external_key": payload["external_key"],
                "receipt": _json_safe(receipt),
            }
        )
    return {
        "namespace": namespace,
        "attempted": len(payloads),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "counts": {
            "succeeded": len(succeeded),
            "failed": len(failed),
            "skipped": len(skipped),
        },
    }


# --- queue view (for the web layer) ----------------------------------------------


def promotion_queue(
    conn: Any,
    *,
    namespace: Optional[str] = None,
    kind: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Paged promotion queue plus per (namespace, kind, tier) counts.

    Each unit row is decorated with the fields the queue page needs: current
    tier, reviewer (if verified), sensitivity, and writeback state — all read
    from provenance so nothing is duplicated outside the unit row.
    """
    # Counts aggregate over namespace+tier (kind is a dimension of the
    # aggregate, so it must not filter it); the paged list adds the kind filter.
    count_where, count_params = [], []
    unit_where, unit_params = [], []
    if namespace is not None:
        count_where.append("namespace = %s")
        count_params.append(namespace)
        unit_where.append("namespace = %s")
        unit_params.append(namespace)
    if tier is not None:
        count_where.append("tier = %s")
        count_params.append(tier)
        unit_where.append("tier = %s")
        unit_params.append(tier)
    # 软删的单位不在可升格池里：它们已经从内容面消失（store.list_knowledge_units
    # 默认同样过滤），把它算进阶梯等于宣称有一批「可以升格」的东西，而实际它们
    # 只剩一个墓碑。2026-11-24 生产实测：legal 队列 total=5547，排除软删后 5145
    # —— 402 条（401 clause + 1 law）已删单位被当成可升格，其中包括测试残留
    # `smoke-clause-001`，随手一升就会把它送回流通。
    count_where.append("COALESCE(tags->>'deleted', 'false') <> 'true'")
    unit_where.append("COALESCE(tags->>'deleted', 'false') <> 'true'")
    if kind is not None:
        unit_where.append("kind = %s")
        unit_params.append(kind)
    else:
        # 分页行与计数必须同口径：分页行此前没有任何 kind 过滤，于是永远爬不上升格梯
        # 的单位会出现在「升格队列」里（2026-11-20 实测：2 行 crosswalk、total=0，
        # 页面显示「本页显示 2 / 0」自相矛盾）。
        # 但口径是 **PROMOTABLE_KINDS**（17 种），不是 entity/relation 两种：上一版把
        # 两边一起收窄成那两种，于是生产里 5,387 条可升格单位（clause 5,386 / law 92 /
        # concept 46 …）在队列里结构性看不见——「升格台账永远是空的」就是它造成的
        # （2026-11-24 实测 legal 域 total=0）。
        unit_where.append(
            "kind IN (" + ", ".join(["%s"] * len(PROMOTABLE_KINDS)) + ")"
        )
        unit_params.extend(PROMOTABLE_KINDS)
    # The aggregate already filters ``kind IN (PROMOTABLE_KINDS)``; operator
    # filters are ANDed on top of it (" AND ...", never a second WHERE).
    counts_clause = (" AND " + " AND ".join(count_where)) if count_where else ""
    unit_clause = (" WHERE " + " AND ".join(unit_where)) if unit_where else ""

    cur = conn.execute(
        "SELECT namespace, kind, tier, count(*) AS n FROM knowledge_units"
        " WHERE kind IN (" + ", ".join(["%s"] * len(PROMOTABLE_KINDS)) + ")"
        + counts_clause
        + " GROUP BY namespace, kind, tier ORDER BY namespace, kind, tier",
        (*PROMOTABLE_KINDS, *count_params),
    )
    counts = [
        dict(r) if isinstance(r, dict)
        else {"namespace": r[0], "kind": r[1], "tier": r[2], "n": r[3]}
        for r in cur.fetchall()
    ]
    if kind is not None:
        total = sum(c["n"] for c in counts if c["kind"] == kind)
    else:
        total = sum(c["n"] for c in counts)

    cur = conn.execute(
        "SELECT id, kind, namespace, external_key, body, tags, attrs, tier, "
        "provenance, updated_at FROM knowledge_units"
        + unit_clause
        + " ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
        (*unit_params, limit, offset),
    )
    rows = cur.fetchall()
    units = []
    for row in rows:
        if isinstance(row, dict):
            r = dict(row)
            prov = r.get("provenance") or {}
            if isinstance(prov, str):
                prov = json.loads(prov)
            units.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "namespace": r["namespace"],
                    "external_key": r["external_key"],
                    "body": r["body"],
                    "tier": r["tier"],
                    # attrs 必须带出来：确定性检查器（packs/<x>/checks.py）读
                    # `attrs.corpus` 判「这条能不能追溯到出处文档」。SQL 早就
                    # select 了 attrs，却没人把它放进返回的 dict —— 于是
                    # corpus-locator 对每一条都误报「缺出处」（2026-11-24 实测
                    # 一条 attrs 齐全的 clause 在页面上报 4/5）。
                    "attrs": (json.loads(r["attrs"])
                              if isinstance(r.get("attrs"), str)
                              else (r.get("attrs") or {})),
                    "tags": json.loads(r["tags"]) if isinstance(r.get("tags"), str) else (r.get("tags") or {}),
                    "reviewer": (prov.get("review") or {}).get("reviewer"),
                    "review_at": (prov.get("review") or {}).get("at"),
                    "sensitivity": prov.get("sensitivity"),
                    "written_back": bool(prov.get("written_back")),
                    "last_writeback_error": prov.get("last_writeback_error"),
                    "synced_from": prov.get("synced_from"),
                    "updated_at": r["updated_at"],
                }
            )
        else:
            prov = json.loads(row[8] or "{}")
            units.append(
                {
                    "id": row[0],
                    "kind": row[1],
                    "namespace": row[2],
                    "external_key": row[3],
                    "body": row[4],
                    "tier": row[7],
                    "attrs": json.loads(row[6] or "{}"),   # see the dict-row note
                    "tags": json.loads(row[5] or "{}"),
                    "reviewer": (prov.get("review") or {}).get("reviewer"),
                    "review_at": (prov.get("review") or {}).get("at"),
                    "sensitivity": prov.get("sensitivity"),
                    "written_back": bool(prov.get("written_back")),
                    "last_writeback_error": prov.get("last_writeback_error"),
                    "synced_from": prov.get("synced_from"),
                    "updated_at": row[9],
                }
            )
    return {"counts": counts, "total": total, "limit": limit, "offset": offset, "units": units}
