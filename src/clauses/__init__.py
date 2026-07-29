"""Clause knowledge base: extract reusable contract clauses from the 823 示范文本
corpus in MinIO, store them in Postgres (base / tagged / custom), and assemble
contracts from base + provincial-tagged + custom clauses around the existing
``{{slot}}`` model.
"""

from __future__ import annotations

from .assemble import generate_contract_assembled
from .corpus import iter_unique_documents, list_corpus_documents, read_document
from .extract import SECTION_ORDER, extract_clauses, extract_document, section_rank
from .store import (
    count_clauses,
    counts_by_type,
    create_clause,
    delete_auto_clauses,
    delete_clause,
    delete_clauses,
    get_custom_clause,
    list_clauses,
    list_extracted_source_paths,
    search_clauses,
    update_clause,
    upsert_clause,
    upsert_clauses,
)

__all__ = [
    "SECTION_ORDER",
    "count_clauses",
    "counts_by_type",
    "create_clause",
    "delete_auto_clauses",
    "delete_clause",
    "delete_clauses",
    "extract_clauses",
    "extract_document",
    "generate_contract_assembled",
    "get_custom_clause",
    "iter_unique_documents",
    "list_clauses",
    "list_corpus_documents",
    "list_extracted_source_paths",
    "read_document",
    "search_clauses",
    "section_rank",
    "update_clause",
    "upsert_clause",
    "upsert_clauses",
]
