"""Persist generated contract docx/pdf to MinIO + a ``contract_artifacts`` DB row.

Content-addressed by ``md5(body_text)``: identical inputs (same contract_type +
scenario + stance + custom_clause_ids -> same assembled body) reuse the same
artifact row. Missing formats are filled in on demand; already-stored formats
are never regenerated or re-uploaded - so a consumer can download a previously
generated contract without regenerating it.

The MinIO client mirrors :mod:`src.clauses.corpus` (native ``minio`` SDK, the
``NO_PROXY=*`` workaround, ``MINIO_*`` settings). DB access mirrors
:mod:`src.clauses.store` (borrowed ``connect``, ``ensure_schema``).
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

# botocore/minio honor the macOS system proxy, which 502s against MinIO; bypass
# proxies entirely for the S3 client (same workaround as src/clauses/corpus).
os.environ.setdefault("NO_PROXY", "*")

from minio import Minio
from psycopg.types.json import Jsonb

from src.clauses import generate_contract_assembled
from src.contracts import get_template
from src.eval.db import connect, now_iso
from src.eval.errors import NotFoundError
from src.eval.store import ensure_schema
from src.settings import (
    MINIO_ACCESS_KEY,
    MINIO_ARTIFACTS_PREFIX,
    MINIO_BUCKET,
    MINIO_PUBLIC_ENDPOINT,
    MINIO_PUBLIC_SECURE,
    MINIO_SECRET_KEY,
)

_FORMATS = ("docx", "pdf", "both", "markdown")


def _client() -> Minio:
    """Build a MinIO client from settings (mirrors ``src.clauses.corpus._client``).

    Uses the *public* endpoint (``MINIO_PUBLIC_*``), which falls back to the
    origin ``MINIO_*`` values when ``MINIO_PUBLIC_HOST`` is unset (task 5.2).
    On the origin that fallback makes this identical to the pre-5.2 behavior; on
    the public pod the public endpoint points at the China-local MinIO mirror so
    reads/downloads stream local bytes with no per-request border crossing.
    Uploads (``_upload``) only run on the origin — the public pod has no
    generate routes mounted — so routing them through the public endpoint is a
    no-op there (the fallback is the origin MinIO).
    """
    if not MINIO_PUBLIC_ENDPOINT:
        raise RuntimeError("minio_host is not set (MinIO unreachable).")
    return Minio(
        MINIO_PUBLIC_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_PUBLIC_SECURE,
        cert_check=False,
    )


def _ensure_bucket(client: Minio) -> None:
    """Create the bucket if missing (idempotent)."""
    try:
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
    except Exception:
        # Bucket existence is best-effort; ``fput_object`` will surface real errors.
        pass


def _object_key(contract_type: str, artifact_id: int, ext: str) -> str:
    return f"{MINIO_ARTIFACTS_PREFIX}{contract_type}/{artifact_id}.{ext}"


def _upload(contract_type: str, artifact_id: int, path: str, ext: str) -> str:
    """Upload a local file to MinIO; return the object key."""
    client = _client()
    _ensure_bucket(client)
    key = _object_key(contract_type, artifact_id, ext)
    client.fput_object(MINIO_BUCKET, key, path)
    return key


def _download_url(artifact_id: int, fmt: str) -> str:
    return f"/api/contracts/artifacts/{artifact_id}/download?format={fmt}"


def _select_row(conn, body_hash: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM contract_artifacts WHERE body_hash = %s", (body_hash,)
    ).fetchone()
    return dict(row) if row else None


def _set_key(conn, artifact_id: int, fmt: str, key: str) -> None:
    col = f"{fmt}_key"
    conn.execute(
        f"UPDATE contract_artifacts SET {col} = %s, updated_at = %s WHERE id = %s",
        (key, now_iso(), artifact_id),
    )


def generate_stored(
    contract_type: str,
    *,
    scenario: str | None = None,
    stance: str | None = None,
    custom_clause_ids: list[int] | None = None,
    format: str = "docx",
    db: Any = None,
    force: bool = False,
) -> dict:
    """Generate a contract, upload docx/pdf to MinIO, record a DB row.

    Content-addressed by ``md5(body_text)``: if an artifact with the same body
    already exists, it is reused (``reused: true``); only requested formats
    missing from the existing row are generated + uploaded. With ``force=True``
    the requested formats are re-uploaded (overwriting the MinIO object) even
    when the artifact already exists — use this to refresh formatting/visuals
    whose change does not alter ``body_text``. Returns
    ``{artifact_id, docx_url, pdf_url, body_text, slots, reused}`` where URLs
    are the HTTP download endpoints (``null`` when a format was not produced).
    """
    if format not in _FORMATS:
        raise ValueError(f"unsupported format: {format!r}; use one of {_FORMATS}")

    result = generate_contract_assembled(
        contract_type,
        scenario=scenario,
        stance=stance,
        custom_clause_ids=custom_clause_ids,
        format=format,
        db=db,
    )
    body_text = result.get("body_text") or ""
    body_hash = hashlib.md5(body_text.encode("utf-8")).hexdigest()
    slots = result.get("slots") or []
    want_docx = format in ("docx", "both")
    want_pdf = format in ("pdf", "both")

    conn = connect(db)
    try:
        ensure_schema(conn)
        existing = _select_row(conn, body_hash)
        now = now_iso()
        if existing:
            artifact_id = existing["id"]
            reused = True
            need_docx = want_docx and (force or not existing.get("docx_key"))
            need_pdf = want_pdf and (force or not existing.get("pdf_key"))
            if need_docx and result.get("docx_path"):
                _set_key(conn, artifact_id, "docx", _upload(contract_type, artifact_id, result["docx_path"], "docx"))
            if need_pdf and result.get("pdf_path"):
                _set_key(conn, artifact_id, "pdf", _upload(contract_type, artifact_id, result["pdf_path"], "pdf"))
            conn.commit()
        else:
            reused = False
            cur = conn.execute(
                "INSERT INTO contract_artifacts "
                "(contract_type, scenario, stance, custom_clause_ids, body_hash, "
                " body_text, slots, docx_key, pdf_key, minio_bucket, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    contract_type, scenario, stance,
                    Jsonb(custom_clause_ids) if custom_clause_ids else None,
                    body_hash, body_text, Jsonb(slots),
                    None, None, MINIO_BUCKET, now, now,
                ),
            )
            artifact_id = cur.fetchone()["id"]
            if want_docx and result.get("docx_path"):
                _set_key(conn, artifact_id, "docx", _upload(contract_type, artifact_id, result["docx_path"], "docx"))
            if want_pdf and result.get("pdf_path"):
                _set_key(conn, artifact_id, "pdf", _upload(contract_type, artifact_id, result["pdf_path"], "pdf"))
            conn.commit()
    finally:
        conn.close()

    return {
        "artifact_id": artifact_id,
        "docx_url": _download_url(artifact_id, "docx") if want_docx else None,
        "pdf_url": _download_url(artifact_id, "pdf") if want_pdf else None,
        "body_text": body_text,
        "slots": slots,
        "reused": reused,
    }


def _distinct_tags(conn, key: str, dim: str, source: str) -> list[str]:
    """Distinct values of a tag ``dim`` on clauses of ``source`` for ``key``."""
    rows = conn.execute(
        f"SELECT DISTINCT tags->>'{dim}' AS v FROM clauses "
        "WHERE contract_type = %s AND tags->>'source' = %s AND tags ? %s ORDER BY 1",
        (key, source, dim),
    ).fetchall()
    return [r["v"] for r in rows if r["v"]]


def _combos(scenarios: list[str], stances: list[str]) -> list[tuple[str | None, str | None]]:
    """Full scenario x stance x base combination space for one contract type."""
    combos: list[tuple[str | None, str | None]] = [(None, None)]
    combos += [(s, None) for s in scenarios]
    combos += [(None, st) for st in stances]
    combos += [(s, st) for s in scenarios for st in stances]
    return combos


def generate_all_stored(
    contract_type: str,
    *,
    format: str = "docx",
    db: Any = None,
    force: bool = False,
) -> dict:
    """Generate + store **every** scenario x stance x base combination for a type.

    For each combination (base; each scenario; each stance; each scenario x
    stance pair), call :func:`generate_stored`. Content-addressed dedup means
    combinations that produce the same body reuse one artifact. Pass
    ``force=True`` to re-upload the requested formats for every existing
    artifact (refresh visuals without changing ``body_text``). Returns a
    summary ``{contract_type, format, artifacts: [...], count, new, reused,
    failed, failures}`` where each artifact entry is
    ``{artifact_id, scenario, stance, docx_url, pdf_url, reused}``. Raises
    :class:`NotFoundError` (-> 404) for an unknown contract type.
    """
    if format not in _FORMATS:
        raise ValueError(f"unsupported format: {format!r}; use one of {_FORMATS}")
    get_template(contract_type)  # validate type -> NotFoundError (404) if unknown
    conn = connect(db)
    try:
        scenarios = _distinct_tags(conn, contract_type, "scenario", "tagged")
        stances = _distinct_tags(conn, contract_type, "stance", "custom")
    finally:
        conn.close()

    combos = _combos(scenarios, stances)
    artifacts: list[dict] = []
    new = reused = failed = 0
    failures: list[str] = []
    for s, st in combos:
        try:
            r = generate_stored(contract_type, scenario=s, stance=st, format=format, db=db, force=force)
            artifacts.append(
                {
                    "artifact_id": r["artifact_id"],
                    "scenario": s,
                    "stance": st,
                    "docx_url": r.get("docx_url"),
                    "pdf_url": r.get("pdf_url"),
                    "reused": r["reused"],
                }
            )
            if r["reused"]:
                reused += 1
            else:
                new += 1
        except Exception as exc:  # noqa: BLE001 - per-combo failures are reported, not fatal
            failed += 1
            failures.append(f"scen={s or '-'}|stance={st or '-'}: {str(exc)[:80]}")
    return {
        "contract_type": contract_type,
        "format": format,
        "artifacts": artifacts,
        "count": len(artifacts),
        "new": new,
        "reused": reused,
        "failed": failed,
        "failures": failures,
    }


_LIST_COLS = (
    "id, contract_type, scenario, stance, custom_clause_ids, body_hash, "
    "slots, docx_key, pdf_key, minio_bucket, created_at, updated_at"
)


def list_artifacts(contract_type: str | None = None, db: Any = None) -> list[dict]:
    """Artifact metadata rows (no ``body_text``), newest first."""
    conn = connect(db)
    try:
        if contract_type:
            rows = conn.execute(
                f"SELECT {_LIST_COLS} FROM contract_artifacts WHERE contract_type = %s ORDER BY id DESC",
                (contract_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_LIST_COLS} FROM contract_artifacts ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_artifact(artifact_id: int, db: Any = None) -> dict | None:
    """Full artifact row (incl. ``body_text``), or ``None`` if missing."""
    conn = connect(db)
    try:
        row = conn.execute(
            "SELECT * FROM contract_artifacts WHERE id = %s", (artifact_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def download(artifact_id: int, format: str, db: Any = None) -> tuple[Any, str, str]:
    """Stream a stored artifact from MinIO.

    Returns ``(minio_response, content_type, filename)``. Raises
    :class:`NotFoundError` if the artifact or the requested format is missing.
    The caller is responsible for closing the response (see the HTTP route's
    streaming generator).
    """
    if format not in ("docx", "pdf"):
        raise ValueError(f"unsupported format: {format!r}; use docx or pdf")
    artifact = get_artifact(artifact_id, db=db)
    if not artifact:
        raise NotFoundError(f"artifact not found: {artifact_id}")
    key = artifact.get(f"{format}_key")
    if not key:
        raise NotFoundError(
            f"artifact {artifact_id} has no stored {format} (generate it first)"
        )
    client = _client()
    response = client.get_object(MINIO_BUCKET, key)
    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if format == "docx"
        else "application/pdf"
    )
    filename = f"{artifact['contract_type']}.{format}"
    return response, content_type, filename


# --- samples-library read helpers (browse + download UI) ---------------------
# Additive, read-only, and do not touch the existing ``list_artifacts`` /
# ``get_artifact`` / ``download`` functions above. They mirror the module's
# DB-access pattern: ``connect(db)`` + ``try/finally: conn.close()`` and
# parameterized queries (``%s`` placeholders only - never string-interpolate
# user input, so there is no SQL-injection surface).


def distinct_scenarios(contract_type: str, db: Any = None) -> list[str]:
    """Distinct non-null ``scenario`` values for one contract type, ordered.

    Excludes base variants (NULL ``scenario``). Used to populate the scenario
    dropdown on the samples page once a contract type is selected.
    """
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT DISTINCT scenario FROM contract_artifacts "
            "WHERE contract_type = %s AND scenario IS NOT NULL ORDER BY 1",
            (contract_type,),
        ).fetchall()
        return [r["scenario"] for r in rows]
    finally:
        conn.close()


def distinct_stances(contract_type: str, db: Any = None) -> list[str]:
    """Distinct non-null ``stance`` values for one contract type, ordered.

    Excludes base variants (NULL ``stance``).
    """
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT DISTINCT stance FROM contract_artifacts "
            "WHERE contract_type = %s AND stance IS NOT NULL ORDER BY 1",
            (contract_type,),
        ).fetchall()
        return [r["stance"] for r in rows]
    finally:
        conn.close()


def list_samples(
    contract_type: str | None = None,
    scenario: str | None = None,
    stance: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Any = None,
) -> tuple[list[dict], int]:
    """Filtered + paginated artifact metadata (no ``body_text``).

    Each of ``contract_type`` / ``scenario`` / ``stance``, when non-None, adds
    an equality filter; so selecting a specific scenario excludes base rows
    with NULL scenario. Absent filters apply no clause, so base/NULL rows are
    included. Returns ``(rows, total)`` where ``total`` is the *filtered* count
    (same WHERE, no LIMIT/OFFSET). Filters compose via AND. An ``offset``
    beyond the filtered total yields an empty row list with the unchanged
    total. Rows are newest first (``ORDER BY id DESC``).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if contract_type:
        clauses.append("contract_type = %s")
        params.append(contract_type)
    if scenario:
        clauses.append("scenario = %s")
        params.append(scenario)
    if stance:
        clauses.append("stance = %s")
        params.append(stance)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = connect(db)
    try:
        # Alias + string key (not ``[0]``) because the shared/borrowed connection
        # uses ``dict_row`` (see ``list_artifacts`` / ``get_artifact`` above) -
        # integer indexing would raise ``KeyError: 0``.
        total = conn.execute(
            f"SELECT COUNT(*) AS total FROM contract_artifacts{where}", params
        ).fetchone()["total"]
        rows = conn.execute(
            f"SELECT {_LIST_COLS} FROM contract_artifacts{where} "
            "ORDER BY id DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows], int(total)
    finally:
        conn.close()
