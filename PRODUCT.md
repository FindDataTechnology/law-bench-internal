# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A solo operator (the project's developer) using the web workbench end-to-end: curating and reviewing clauses, managing prompts and rubrics, running evaluation pipelines and prompt compares, and generating contract artifacts. No external or team audience is targeted today (confirmed 2026-08-29).

## Product Purpose

An internal workbench for drafting and benchmarking Chinese legal contracts with LLMs. It assembles contracts from a curated, statute-grounded clause corpus, judges drafts against rubrics with an LLM judge, self-heals low-scoring drafts, and compares drafting prompts head-to-head. Success means measurable, reproducible improvements in contract quality per rubric scores, and a steadily deepening clause corpus.

## Positioning

The closed evaluation loop: tag-driven clause assembly, LLM-judge rubric scoring, self-heal pipelines, and prompt A/B compare in one bench. Neighboring contract generators produce drafts; this product measures them (confirmed by the operator).

## Operating Context

- Workflows run through a login-gated FastAPI + Jinja2 web UI (dashboard, clause review/edit, prompts, rubrics, compare runs, contract generation, RAG clause search, law references, samples) and a `law-bench` MCP server for agent-driven operation.
- Evaluation state lives in Postgres (clauses, prompts, rubrics, eval/compare/pipeline runs); artifacts in MinIO; clause retrieval via Elasticsearch.
- Contract artifacts render to Markdown, DOCX, and PDF; deterministic fills default to temperature 0 for reproducibility.
- The system is also deployed as a public API (finddatatech.cloud) on the same core.

## Capabilities and Constraints

- Chinese legal domain (confirmed): the UI stays simplified Chinese; contract content, clause bodies, rubrics, and law references remain PRC-law Chinese.
- Contract types are catalog-driven (sale, lease, employment, …) with tag dimensions such as scenario and stance.
- Undecided: none raised this session.

## Evidence on Hand

- Real evaluation history in Postgres: eval runs, compare runs, and pipeline runs with per-criterion verdicts.
- A curated clause corpus seeded from real contract sources with statute citations; workflow and architecture docs under `docs/` (evaluation-system.md, tag-driven-assembly.md, pipeline-architecture.md, v4-*-results.md).
- Absences future work must not fabricate: no customer testimonials, no external user research, no marketing claims.

## Product Principles

1. Evidence over vibes: drafting changes ship only after rubric-judged evaluation measures them.
2. The corpus is the product: curated, reviewed, statute-grounded clauses with tags beat prompt heroics.
3. Operator speed first: the web UI exists to make one person fast at curating and evaluating.
4. Chinese legal fidelity: contract language stays simplified Chinese and PRC-law accurate.
5. Reproducibility: versioned rubrics, stored artifacts, deterministic fills.
