"""Portable asset transfer: export/import the audited envelope (change
``add-bench-asset-portability``).

One envelope format for five asset kinds, defined by ``fd-ontology-kernel``:
the digest is the kernel's canonical sha256, so a copy and its source answer
"same version?" with one number. This module owns only what is law-bench
specific — which rows a kind projects from, and how an import lands them.

Scope of v1 (stated, not silent):

- importable: ``ontology-template`` (creates a template row) and ``ruler-set``
  (creates domain rubrics in an explicit target domain);
- export-only: ``vocabulary-release``, ``gold-set``, ``eval-suite``. Their
  import needs a target context that the envelope alone cannot name, so an
  import of those kinds is refused with a readable reason instead of a guess.

Every import is verified whole before any write, and only a successful import
leaves an ``asset_transfer_events`` row.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from fd_ontology_kernel import envelope as kernel_envelope
from fd_ontology_kernel import manifest as kernel_manifest

from . import domain_rubrics, packs, templates, workspaces

#: Asset kinds this instance can export. Kept in step with the kernel.
ASSET_KINDS = kernel_envelope.ASSET_KINDS

#: Kinds v1 can import. The rest are refused loudly on import.
IMPORTABLE_KINDS = ("ontology-template", "ruler-set")

_VOCAB_SCHEMA_KEYS = (
    "entity_types",
    "relationship_kinds",
    "tier_vocabulary",
    "sensitivity_vocabulary",
)


class TransferError(ValueError):
    """An asset transfer is disabled, malformed, inconsistent, or unsupported."""


def enabled() -> bool:
    """The transfer surface is opt-in; default off keeps every existing
    deployment byte-identical."""
    return str(__import__("os").environ.get("BENCH_ASSET_PORTABILITY", "")).strip() in (
        "1",
        "true",
        "yes",
    )


def require_enabled() -> None:
    if not enabled():
        raise TransferError(
            "portable asset transfer is not enabled on this deployment "
            "(set BENCH_ASSET_PORTABILITY=1)"
        )


# ── projection helpers ───────────────────────────────────────────────────────


def _template_vocabulary(schema: Mapping[str, Any]) -> Any:
    """A kernel Vocabulary over the four list vocabularies a template carries."""
    sets = {
        key: list(schema[key])
        for key in _VOCAB_SCHEMA_KEYS
        if isinstance(schema.get(key), list) and schema[key]
    }
    return kernel_envelope.vocabulary_from_release(
        {"release": "template", "sets": sets}
    )


def _domain_path(conn: Any, domain_key: str) -> str:
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise TransferError(f"domain {domain_key!r} not found")
    return domain.get("path") or domain["key"]


def _rubric_payload(conn: Any, domain_key: str) -> dict:
    path = _domain_path(conn, domain_key)
    rows = domain_rubrics.effective_rubrics(conn, domain_path=path)
    full = [domain_rubrics.get_by_id(conn, rubric_id=row["id"]) for row in rows]
    return {
        "domain": domain_key,
        "rubrics": [
            {
                "name": row["name"],
                "context": row["context"],
                "description": row.get("description"),
                "criteria": [
                    {
                        "name": c.get("name"),
                        "description": c.get("description"),
                        "guidance": c.get("guidance"),
                        "ordinal": c.get("ordinal"),
                    }
                    for c in (row.get("criteria") or [])
                ],
            }
            for row in full
        ],
    }


def _gold_payload(conn: Any, domain_key: str) -> dict:
    path = _domain_path(conn, domain_key)
    rows = conn.execute(
        "SELECT kind, external_key, body, tags, attrs, tier, source_path, provenance "
        "FROM knowledge_units WHERE namespace = %s AND tier = 'gold' "
        "ORDER BY kind, external_key",
        (path,),
    ).fetchall()

    def _one(row):
        if isinstance(row, dict):
            data = dict(row)
        else:
            keys = ("kind", "external_key", "body", "tags", "attrs", "tier",
                    "source_path", "provenance")
            data = dict(zip(keys, row))
        for key in ("tags", "attrs", "provenance"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    data[key] = json.loads(value)
                except json.JSONDecodeError:
                    data[key] = None
        return data

    return {"domain": domain_key, "units": [_one(r) for r in rows]}


def _eval_suite_payload(pack_name: str) -> dict:
    manifest = packs.load_pack(pack_name)
    return {
        "pack": pack_name,
        "eval_suites": list(manifest.get("eval_suites") or []),
        "kinds": list(manifest.get("kinds") or []),
    }


# ── export ───────────────────────────────────────────────────────────────────


def export_asset(
    conn: Any,
    *,
    kind: str,
    name: str,
    version: Optional[int] = None,
    domain_key: Optional[str] = None,
) -> dict:
    """Project one asset into a portable envelope (read-only).

    The digest is the kernel's canonical sha256 over the payload, so exporting
    never writes a publication row or a pull footprint.
    """
    require_enabled()
    if kind not in ASSET_KINDS:
        raise TransferError(
            f"kind {kind!r} is not a portable asset kind; allowed: {list(ASSET_KINDS)}"
        )

    lineage = None
    fork_diff = None

    if kind == "ontology-template":
        tmpl = templates.get_template(conn, name=name, version=version)
        if tmpl is None:
            raise TransferError(f"template {name!r} not found")
        payload = dict(tmpl["schema"])
        if tmpl.get("upstream"):
            lineage = {"upstream": dict(tmpl["upstream"])}
            fork_diff = dict(tmpl.get("fork_diff") or {"note": "fork"})
        if version is None:
            version = tmpl["version"]
    elif kind == "vocabulary-release":
        tmpl = templates.get_template(conn, name=name, version=version)
        if tmpl is None:
            raise TransferError(f"template {name!r} not found")
        payload = {
            "release": f"{tmpl['name']}@{tmpl['version']}",
            "sets": {
                key: list(tmpl["schema"][key])
                for key in _VOCAB_SCHEMA_KEYS
                if isinstance(tmpl["schema"].get(key), list)
            },
        }
        version = tmpl["version"]
    elif kind == "ruler-set":
        if not domain_key:
            raise TransferError("ruler-set export needs domain_key")
        payload = _rubric_payload(conn, domain_key)
        version = version or 1
    elif kind == "gold-set":
        if not domain_key:
            raise TransferError("gold-set export needs domain_key")
        payload = _gold_payload(conn, domain_key)
        version = version or 1
    else:  # eval-suite
        payload = _eval_suite_payload(name)
        version = version or 1

    return kernel_envelope.build(
        kind=kind,
        name=name,
        version=int(version),
        payload=payload,
        manifest_shape=2,
        lineage=lineage,
        fork_diff=fork_diff,
    )


# ── import ───────────────────────────────────────────────────────────────────


def _audit(
    conn: Any,
    *,
    env: Any,
    actor: str,
    target_ref: Optional[str],
) -> None:
    conn.execute(
        "INSERT INTO asset_transfer_events "
        "(op, asset_kind, asset_name, asset_version, digest, target_ref, actor) "
        "VALUES ('import', %s, %s, %s, %s, %s, %s)",
        (env.kind, env.name, env.version, env.digest, target_ref, actor),
    )


def _import_template(conn: Any, env: Any, actor: str) -> dict:
    existing = templates.get_template(conn, name=env.name)
    if existing is not None:
        if kernel_manifest.digest_of(existing["schema"]) == env.digest:
            return {"created": False, "kind": env.kind, "name": env.name,
                    "version": existing["version"], "digest": env.digest}
        raise TransferError(
            f"template {env.name!r} already exists with different content; "
            "choose another name or bump the source version"
        )

    # Additive check only when the upstream version is present locally: a fork
    # imported into a fresh instance has no parent to compare against, and the
    # kernel's rule treats "no previous" as legal.
    previous = None
    derived_from = None
    upstream = (env.lineage or {}).get("upstream") if env.lineage else None
    if upstream:
        parent = templates.get_template(
            conn, name=upstream["name"], version=upstream["version"]
        )
        if parent is not None:
            derived_from = parent["id"]
            previous = _template_vocabulary(parent["schema"])
    if previous is not None:
        problem = kernel_envelope.additive_problem(
            previous, _template_vocabulary(env.payload)
        )
        if problem:
            raise TransferError(f"fork is not additive over its upstream: {problem}")

    created = templates.create_template(
        conn,
        name=env.name,
        schema=dict(env.payload),
        created_by=actor,
        derived_from=derived_from,
        fork_diff=dict(env.fork_diff) if env.fork_diff else None,
        upstream=dict(upstream) if upstream else None,
    )
    _audit(conn, env=env, actor=actor, target_ref=str(created["id"]))
    conn.commit()
    return {
        "created": True,
        "kind": env.kind,
        "name": created["name"],
        "version": created["version"],
        "id": created["id"],
        "digest": env.digest,
        "derived_from": derived_from,
    }


def _import_ruler_set(conn: Any, env: Any, actor: str, target_domain_key: str) -> dict:
    domain = workspaces.get_domain(conn, domain_key=target_domain_key)
    if domain is None:
        raise TransferError(f"target domain {target_domain_key!r} not found")
    rubrics = env.payload.get("rubrics")
    if not isinstance(rubrics, list) or not rubrics:
        raise TransferError("ruler-set payload carries no rubrics")

    path = domain.get("path") or domain["key"]
    existing = {r["name"] for r in domain_rubrics.effective_rubrics(conn, domain_path=path)}

    created: list[str] = []
    skipped: list[str] = []
    for rubric in rubrics:
        name = rubric.get("name")
        if not isinstance(name, str) or not name.strip():
            raise TransferError("every rubric needs a non-empty name")
        if name in existing:
            skipped.append(name)
            continue
        domain_rubrics.create_for_domain(
            conn,
            domain_id=domain["id"],
            name=name,
            context=rubric.get("context") or "",
            criteria=rubric.get("criteria") or (),
            description=rubric.get("description"),
            source="import",
            commit=False,
        )
        created.append(name)
    _audit(conn, env=env, actor=actor, target_ref=target_domain_key)
    conn.commit()
    return {
        "created": bool(created),
        "kind": env.kind,
        "domain": target_domain_key,
        "imported": created,
        "skipped": skipped,
        "digest": env.digest,
    }


def import_asset(
    conn: Any,
    *,
    raw: Mapping[str, Any],
    actor: str,
    file_bytes: Optional[Mapping[str, bytes]] = None,
    target_domain_key: Optional[str] = None,
) -> dict:
    """Verify, then land, one envelope. Whole or not at all."""
    require_enabled()
    if not actor:
        raise TransferError("actor is required")
    try:
        env = kernel_envelope.verify(raw, file_bytes=file_bytes)
    except kernel_envelope.EnvelopeError as exc:
        raise TransferError(str(exc)) from None

    if env.kind == "ontology-template":
        return _import_template(conn, env, actor)
    if env.kind == "ruler-set":
        if not target_domain_key:
            raise TransferError("ruler-set import needs target_domain_key")
        return _import_ruler_set(conn, env, actor, target_domain_key)
    raise TransferError(
        f"{env.kind!r} is export-only in v1: importing it needs a target context "
        "the envelope cannot name (attach it through its owning template, domain, "
        "or pack) — refusing rather than guessing"
    )


def export_document(conn: Any, **kwargs: Any) -> str:
    """Convenience: export an asset and return the envelope as pretty JSON."""
    return json.dumps(export_asset(conn, **kwargs), ensure_ascii=False, indent=2)
