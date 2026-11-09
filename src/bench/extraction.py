"""Ontology candidate extraction: corpus → candidates → human review queue (§§1-4).

The shape of this module is a direct consequence of one fact: **a model can
invent evidence**. Everything here exists to keep that from reaching the
ontology:

- every candidate must carry a ``quote``, and the quote is looked up **verbatim**
  (whitespace-normalised) inside the chunk it claims to come from. No similarity
  threshold: a paraphrase is exactly what a hallucination looks like.
- nothing is written to ``knowledge_units``. Candidates go to the proposal layer
  as pending rows, so a human decides. The kernel remains the only write path.
- kinds must be in the domain's declared vocabularies, and a relationship's
  endpoints must exist or be nominated in the same batch (else a same-batch
  ``A→B`` could never be proposed, because ``B`` is not confirmed yet).
- caps on chunks, candidates-per-chunk and total candidates; hitting one stops
  the run and says so, rather than quietly costing more.

What it deliberately does *not* do: judge whether a well-quoted conclusion is
correct. That is why ``impact`` carries the quoted text — the reviewer reads the
source, not a summary.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

import httpx

from src.bench import authoring, libraries, ontology_import, proposals

#: Bumped whenever the prompt changes — recorded on every proposal so a batch can
#: be traced back to the instruction that produced it.
PROMPT_VERSION = "2026-11-09.1"

#: Hard ceilings. The parameters can lower them, never raise them.
MAX_CHUNKS = 200
MAX_PER_CHUNK = 8
MAX_TOTAL = 500

_WS = re.compile(r"\s+")


class ExtractionError(ValueError):
    """The request cannot be run (bad scope, no chunks, no model configured)."""


# ── sampling ────────────────────────────────────────────────────────────────


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()


def sample_chunks(
    conn: Any,
    *,
    domain_path: str,
    sources: Optional[list[str]] = None,
    limit: int = 20,
    cursor: Any = None,
) -> dict:
    """Page through a domain's subscribed corpus, oldest point id first.

    Sampling (not similarity search) because extraction wants coverage: a top-k
    query would keep returning the same nearest chunks and the ontology would
    grow only around whatever the query happened to say.

    Only ``qdrant`` libraries are supported here: they are the ones with a
    paging API. A domain whose scope has no qdrant library raises rather than
    silently returning nothing.
    """
    limit = max(1, min(int(limit), MAX_CHUNKS))
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    if not scope:
        raise ExtractionError(f"domain {domain_path!r} subscribes to no corpus")
    if sources:
        unknown = sorted(set(sources) - {s for v in scope.values() for s in v})
        if unknown:
            raise ExtractionError(
                f"source(s) not in this domain's scope: {', '.join(unknown)}; "
                f"available: {sorted({s for v in scope.values() for s in v})}"
            )
    collected: list[dict] = []
    next_cursor = cursor
    for library_key, granted in sorted(scope.items()):
        lib = libraries.get_library(conn, library_key=library_key)
        if lib is None or (lib.get("backend") or "") != "qdrant":
            continue
        wanted = set(sources) if sources else set(granted)
        wanted &= set(granted)
        if not wanted:
            continue
        loc = libraries.resolve_location(lib)
        filt = _filter_for(conn, lib=lib, allowed=wanted)
        # Fetch a wider window than the page size: spreading across documents
        # needs candidates beyond the first few, and scroll is document-ordered.
        want = max(1, limit - len(collected))
        body: dict[str, Any] = {"limit": min(MAX_CHUNKS, want * 4), "with_payload": True}
        if filt is not None:
            body["filter"] = filt
        if next_cursor is not None:
            body["offset"] = next_cursor
        data = _post(loc["url_env"], f"/collections/{loc['collection']}/points/scroll", body)
        result = data.get("result") or {}
        window: list[dict] = []
        for point in result.get("points") or []:
            payload = point.get("payload") or {}
            text = payload.get("chunk_text") or ""
            if not text or ontology_import.is_smoke({"external_key": str(point.get("id")), "body": text}):
                continue
            window.append(
                {
                    "chunk_id": str(point.get("id")),
                    "library": library_key,
                    "source_key": _source_of(conn, lib=lib, payload=payload),
                    "law_id": payload.get("law_id"),
                    "title": payload.get("title"),
                    "chunk_no": payload.get("chunk_no"),
                    "text": text,
                }
            )
        next_cursor = result.get("next_page_offset")
        collected.extend(_spread(window, limit - len(collected)))
        if len(collected) >= limit:
            break
    return {"chunks": collected[:limit], "cursor": next_cursor}


def _spread(chunks: list[dict], limit: int, *, per_doc: int = 2) -> list[dict]:
    """Pick chunks spread across documents instead of in ingest order.

    Qdrant scroll is ordered by point id, and points are written document by
    document — so a naive page of 20 chunks can be 2 laws (measured: 20 chunks
    from 2 `law_id`s). Extraction wants coverage, so take at most ``per_doc``
    chunks from each document, round robin, until the page is full.

    Chunks left over in the window are dropped rather than re-queued: this is
    sampling, not an exhaustive walk, and the cursor already moved past them.
    """
    if limit <= 0:
        return []
    by_doc: dict[Any, list[dict]] = {}
    order: list[Any] = []
    for chunk in chunks:
        doc = chunk.get("law_id") or chunk.get("chunk_id")
        if doc not in by_doc:
            by_doc[doc] = []
            order.append(doc)
        if len(by_doc[doc]) < per_doc:
            by_doc[doc].append(chunk)
    picked: list[dict] = []
    for round_no in range(per_doc):
        for doc in order:
            if round_no < len(by_doc[doc]):
                picked.append(by_doc[doc][round_no])
                if len(picked) >= limit:
                    return picked
    if len(picked) < limit:
        # The window was dominated by a few documents: top up in window order so
        # the caller still gets the page size it asked for. A short page here
        # would silently reduce coverage without saying so.
        taken = {id(c) for c in picked}
        for chunk in chunks:
            if id(chunk) in taken:
                continue
            picked.append(chunk)
            if len(picked) >= limit:
                break
    return picked


def _filter_for(conn: Any, *, lib: dict, allowed: set[str]) -> Optional[dict]:
    from src.search import library_index

    return library_index.qdrant_filter(
        libraries.list_sources(conn, library_id=lib["id"]), allowed
    )


def _source_of(conn: Any, *, lib: dict, payload: dict) -> str:
    from src.search import library_index

    return library_index._source_for_payload(
        libraries.list_sources(conn, library_id=lib["id"]), payload
    )


# ── evidence gate ───────────────────────────────────────────────────────────


def verify_quote(quote: str, chunk_text: str) -> bool:
    """True when ``quote`` really is a verbatim slice of ``chunk_text``.

    Whitespace is normalised on both sides (models reflow lines); nothing else
    is forgiven. A single changed character or a truncated phrase must fail —
    that is the whole point.
    """
    q, t = _norm(quote), _norm(chunk_text)
    if not q or not t:
        return False
    return q in t


# ── prompt & parsing ────────────────────────────────────────────────────────


def build_prompt(*, schema: dict, chunks: list[dict]) -> str:
    """Instruction + the chunk texts, constrained to the domain's vocabularies."""
    entity_types = sorted((schema or {}).get("entity_types") or [])
    relation_kinds = sorted((schema or {}).get("relationship_kinds") or [])
    blocks = []
    for c in chunks:
        blocks.append(
            f"[chunk_id={c['chunk_id']}] title={c.get('title')} "
            f"source={c['source_key']}\n{c['text'][:1200]}"
        )
    return f"""你是本体候选抽取器（prompt_version={PROMPT_VERSION}）。

只允许使用下面这些类型：
- 实体类型 entity_types: {entity_types}
- 关系类型 relationship_kinds: {relation_kinds}

从给定语料块中抽取候选实体与候选关系。类型只从上面两组词表里选，不认识的不要造。硬性要求：
1. 每条候选必须给出 quote 字段，且 quote 必须是所引块里**逐字出现**的一段原文（不要改写、不要概括、不要拼接跨段内容）。
2. 实体候选：kind 必须属于 entity_types，name 用原文里的称呼。
3. 关系候选：kind 必须属于 relationship_kinds，from_name/to_name 用实体候选或已有实体的名称。
4. 不确定就不要输出。宁少不滥。

只输出 JSON，形如：
{{"entities": [{{"kind": "...", "name": "...", "chunk_id": "...", "quote": "..."}}],
  "relationships": [{{"kind": "...", "from_name": "...", "to_name": "...", "chunk_id": "...", "quote": "..."}}]}}

语料块：
{chr(10).join(blocks)}
"""


def parse_candidates(raw: str) -> dict:
    """Parse the model's answer; tolerate fences and surrounding prose.

    A malformed *row* is dropped (and counted by the caller); a malformed
    *answer* yields empty lists. Neither raises — one bad answer must not abort
    a 200-chunk run.
    """
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {"entities": [], "relationships": [], "bad_rows": 0}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"entities": [], "relationships": [], "bad_rows": 0}
    if not isinstance(data, dict):
        return {"entities": [], "relationships": [], "bad_rows": 0}
    entities, bad = [], 0
    for row in data.get("entities") or []:
        if isinstance(row, dict) and row.get("kind") and row.get("name") and row.get("quote"):
            entities.append(row)
        else:
            bad += 1
    relationships = []
    for row in data.get("relationships") or []:
        if all(isinstance(row, dict) and row.get(k) for k in ("kind", "from_name", "to_name", "quote")):
            relationships.append(row)
        else:
            bad += 1
    return {"entities": entities, "relationships": relationships, "bad_rows": bad}


_ILLEGAL = re.compile(r"[\s\u3000/\\:：·、，,（）()\[\]【】《》]+")


def normalize_entity_key(name: str) -> str:
    """Stable external key for an entity name.

    Two spellings of the same name must land on one key or the same entity gets
    proposed twice and the reviewer sees a duplicate. Full-width spaces,
    punctuation and separators are folded away; length is capped.
    """
    key = _ILLEGAL.sub("-", (name or "").strip())
    key = re.sub(r"-{2,}", "-", key).strip("-")
    return key[:80] or "unnamed"


# ── model call (injectable) ─────────────────────────────────────────────────


def complete(prompt: str) -> str:
    """Call the project's OpenAI-compatible endpoint. Tests replace this."""
    base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENROUTER_API_BASE")
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("EVAL_MODEL") or os.environ.get("EXTRACT_MODEL")
    if not (base and key and model):
        raise ExtractionError(
            "extraction needs OPENAI_API_BASE + OPENAI_API_KEY + EVAL_MODEL "
            "(or the OPENROUTER_* / EXTRACT_MODEL equivalents)"
        )
    name = model.split("/", 1)[1] if model.startswith("openai/") else model
    # ``max_tokens`` is not optional here. The lane's models are reasoning
    # models: with no explicit budget they spend the allowance on the chain of
    # thought and return ``finish_reason=length`` with ``content=None``
    # (observed on 词元, 2026-11-09). The caller then sees what looks like a
    # timeout and goes hunting for a slow model instead of a short payload.
    budget = int(os.environ.get("EXTRACT_MAX_TOKENS", "1500"))
    call_timeout = float(os.environ.get("EXTRACT_TIMEOUT", "240"))
    resp = httpx.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": name, "temperature": 0.0, "max_tokens": budget,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=call_timeout,
    )
    resp.raise_for_status()
    choices = resp.json().get("choices") or []
    if not choices:
        raise ExtractionError("model returned no choices")
    return (choices[0].get("message") or {}).get("content") or ""


# ── the run ─────────────────────────────────────────────────────────────────


def run(
    conn: Any,
    *,
    domain_key: str,
    sources: Optional[list[str]] = None,
    max_chunks: int = 20,
    max_per_chunk: int = MAX_PER_CHUNK,
    max_total: int = 100,
    batch: Optional[str] = None,
    complete_fn: Optional[Callable[[str], str]] = None,
    submitted_by: str = "extraction",
) -> dict:
    """Extract candidates for one domain and file them as pending proposals.

    Returns a report, never a bare count: a run that produced nothing needs to
    say *why* (bad quotes? out-of-vocabulary kinds? duplicate hits?), otherwise
    the operator cannot tell "the corpus has nothing" from "the prompt is bad".
    """
    from src.bench import templates as bench_templates

    domain = authoring._load_domain(conn, domain_key=domain_key)
    tmpl = bench_templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    entity_types = set(schema.get("entity_types") or [])
    relation_kinds = set(schema.get("relationship_kinds") or [])
    model = os.environ.get("EVAL_MODEL") or os.environ.get("EXTRACT_MODEL") or "unknown"
    batch = batch or f"{domain_key}-{PROMPT_VERSION}"
    call = complete_fn or complete

    sampled = sample_chunks(
        conn, domain_path=domain["path"], sources=sources,
        limit=min(max_chunks, MAX_CHUNKS),
    )
    chunks = sampled["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}

    report = {
        "batch": batch,
        "sampled": len(chunks),
        "produced": 0,
        "submitted": 0,
        "duplicate": 0,
        "skipped": {"bad_quote": 0, "bad_kind": 0, "bad_endpoint": 0, "bad_row": 0},
        "by_kind": {},
        "stopped": None,
        "cursor": sampled["cursor"],
    }

    live = {e["external_key"] for e in authoring.authoring_live_entities(conn, domain_key=domain_key)}
    nominated: set[str] = set()
    total = 0

    for chunk in chunks:
        if total >= min(max_total, MAX_TOTAL):
            report["stopped"] = "cap"
            break
        raw = call(build_prompt(schema=schema, chunks=[chunk]))
        parsed = parse_candidates(raw)
        report["skipped"]["bad_row"] += parsed["bad_rows"]
        produced = parsed["entities"][:max_per_chunk] + parsed["relationships"][:max_per_chunk]
        for row in produced:
            if total >= min(max_total, MAX_TOTAL):
                report["stopped"] = "cap"
                break
            total += 1
            report["produced"] += 1
            kind = str(row.get("kind") or "")
            source_chunk = by_id.get(str(row.get("chunk_id") or chunk["chunk_id"]), chunk)
            if not verify_quote(str(row.get("quote") or ""), source_chunk["text"]):
                report["skipped"]["bad_quote"] += 1
                continue
            is_relation = "from_name" in row or "to_name" in row
            vocab = relation_kinds if is_relation else entity_types
            if kind not in vocab:
                report["skipped"]["bad_kind"] += 1
                continue
            evidence = {
                "chunk_id": source_chunk["chunk_id"],
                "quote": _norm(str(row.get("quote"))),
                "library": source_chunk["library"],
                "source_key": source_chunk["source_key"],
                "batch": batch,
                "model": model,
                "prompt_version": PROMPT_VERSION,
            }
            if is_relation:
                from_key = normalize_entity_key(str(row.get("from_name")))
                to_key = normalize_entity_key(str(row.get("to_name")))
                missing = [k for k in (from_key, to_key) if k not in live and k not in nominated]
                if missing:
                    report["skipped"]["bad_endpoint"] += 1
                    continue
                external_key = authoring.relationship_external_key(
                    from_key=from_key, kind=kind, to_key=to_key
                )
                body = f"{row.get('from_name')} {kind} {row.get('to_name')}"
                evidence["from_key"], evidence["to_key"] = from_key, to_key
            else:
                external_key = normalize_entity_key(str(row.get("name")))
                body = str(row.get("name"))
                nominated.add(external_key)
            try:
                _proposal, created = proposals.submit(
                    conn,
                    domain_key=domain_key,
                    source=f"extract:{model}:{PROMPT_VERSION}",
                    kind=kind,
                    external_key=external_key,
                    body=body,
                    evidence=evidence,
                    impact=f"原文：{evidence['quote']}",
                    submitted_by=submitted_by,
                    with_created=True,
                )
            except ValueError:
                report["skipped"]["bad_row"] += 1
                continue
            if created:
                report["submitted"] += 1
                report["by_kind"][kind] = report["by_kind"].get(kind, 0) + 1
            else:
                report["duplicate"] += 1
    return report


def _post(url: str, path: str, body: dict, timeout: float = 30.0) -> dict:
    from src.search import library_index

    return library_index._qdrant_post(url, path, body, timeout=timeout)
