"""把政务公开语料里的公文按「文档 + 发文机关 + 签发关系」取进本体。

    python3 scripts/adopt_gov_documents.py --dry-run --limit 40
    python3 scripts/adopt_gov_documents.py --limit 40

为什么不需要模型：每份公文的元数据里就写着发文机关（``metadata.issuer``）、文种
（``doc_type``）、成文日期（``doc_date``）与官方链接（``provenance.stable_id``）。
这些是事实，读出来就是；让模型「判断」发文机关只会引入编造。

三条纪律：

1. **只走内核写路径**：文档经 ``corpus_catalog.adopt_document``，机关与关系经
   ``authoring``；脚本不直接写 ``knowledge_units``。
2. **键确定性**：文档键按政务线的归名规则（``packs.gov.entity_keys``），机关键就是
   机关名本身（同一机关在所有公文里必须是同一个键）。
3. **幂等**：重复跑不产生第二条；关系键由内核按 (from, kind, to) 生成。

机关名的清洗只做两件事，都在这里写明：去掉结尾的「办公厅/办公室」不做的——那是
不同的机构；「其他」不是机关，跳过并计数。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import packs.gov  # noqa: E402,F401  （注册政务线的归名规则）
from src.bench import authoring, corpus_catalog, libraries  # noqa: E402

#: 公文元数据里出现的占位值：不是机关，建成单位只会污染词表。
ISSUER_PLACEHOLDERS = frozenset({"其他", "未知", "", "-", "—"})

#: 文档正文里没有「第N条」时不影响取入，只标注；政务公文的条款结构不统一。


def _read_metadata(conn, *, library_key: str, source_key: str, doc_ids: list[str]) -> dict:
    """Read issuer/type/date/url for the given document ids, read-only."""
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        raise SystemExit(f"library {library_key!r} not found")
    mapping = corpus_catalog.document_mapping(
        next(s for s in libraries.list_sources(conn, library_id=lib["id"])
             if s["source_key"] == source_key)
    )
    table = mapping.get("table") or "corpus_documents"
    loc = libraries.resolve_location(lib)

    import psycopg
    from psycopg.rows import dict_row

    out: dict[str, dict] = {}
    with psycopg.connect(loc["dsn_env"], connect_timeout=10, row_factory=dict_row) as ext:
        rows = ext.execute(
            f"SELECT {mapping['id']} AS doc_id, metadata, provenance, title, status "
            f"FROM {table} WHERE {mapping['id']} = ANY(%s)",
            ([int(d) for d in doc_ids],),
        ).fetchall()
    for row in rows:
        meta = row.get("metadata") or {}
        prov = row.get("provenance") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        if isinstance(prov, str):
            prov = json.loads(prov)
        out[str(row["doc_id"])] = {
            "issuer": (meta.get("issuer") or "").strip(),
            "doc_type": (meta.get("doc_type") or "").strip(),
            "doc_date": (meta.get("doc_date") or "").strip(),
            "index_no": (meta.get("index_no") or "").strip(),
            "stable_id": (prov.get("stable_id") or "").strip(),
            "title": row.get("title") or "",
            "status": row.get("status") or "",
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="gov")
    ap.add_argument("--library", default="text-library")
    ap.add_argument("--source", default="gov")
    ap.add_argument("--limit", type=int, default=40, help="最多取入多少份文档（按体量）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        page = corpus_catalog.documents(
            conn, library_key=args.library, source_key=args.source,
            limit=max(1, min(args.limit, 200)), domain_key=args.domain,
        )
        rows = page["rows"]
        if not rows:
            print("no documents in scope", file=sys.stderr)
            return 1
        meta = _read_metadata(conn, library_key=args.library, source_key=args.source,
                              doc_ids=[r["id"] for r in rows])
        print(f"documents in scope: {page['total']}; taking {len(rows)} "
              f"(partial={page['partial']})")

        adopted = agencies = relations = skipped_issuer = 0
        for row in rows:
            info = meta.get(row["id"], {})
            issuer = info.get("issuer") or ""
            if args.dry_run:
                print(f"  DRY {row['id']} {row['title'][:40]} | issuer={issuer or '—'} "
                      f"| {info.get('doc_type') or '—'} | {info.get('doc_date') or '—'}")
                continue
            out = corpus_catalog.adopt_document(
                conn, domain_key=args.domain, library_key=args.library,
                source_key=args.source, doc_id=row["id"], operator="adopt_gov",
            )
            adopted += 1
            doc_key = out["key"]

            if not issuer or issuer in ISSUER_PLACEHOLDERS:
                skipped_issuer += 1
                continue
            authoring.authoring_create_unit(
                conn, domain_key=args.domain, kind="agency", external_key=issuer,
                body=f"# {issuer}",
                operator="adopt_gov",
                attrs={"role": "issuer",
                       **({"index_no": info["index_no"]} if info.get("index_no") else {})},
            )
            agencies += 1
            authoring.authoring_create_relationship(
                conn, domain_key=args.domain, kind="issued_by",
                from_key=doc_key, to_key=issuer,
                body=f"{doc_key} issued_by {issuer}",
                operator="adopt_gov",
            )
            relations += 1

        if args.dry_run:
            print("[dry-run] nothing written")
            return 0

        counts = conn.execute(
            "SELECT kind, COUNT(*) AS n FROM knowledge_units WHERE namespace=%s "
            "AND (tags->>'deleted') IS NULL GROUP BY kind ORDER BY kind",
            (args.domain,),
        ).fetchall()
        print(f"documents adopted: {adopted}; agencies upserted: {agencies}; "
              f"issued_by created: {relations}; issuer missing/placeholder: {skipped_issuer}")
        print("live units:", {r["kind"]: r["n"] for r in counts})
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
