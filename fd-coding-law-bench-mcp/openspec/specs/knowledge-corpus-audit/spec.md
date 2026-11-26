# knowledge-corpus-audit Specification

## Purpose
Keep the `kind='clause'` corpus in `knowledge_units` measurable and content-faithful: a deterministic, zero-LLM measurement pass scopes which defect classes are real before any costly work, a consumption survey decides whether a rewrite has any observable downstream, and PDF extraction line-break artifacts — the one class the statute-article corpus actually carries — are repaired deterministically at ingestion and backfilled, without ever touching bloodline fields.

## Requirements

### Requirement: Phase 0 real-data measurement precedes scoping

The system MUST run a deterministic, zero-LLM measurement pass over all `kind='clause'` knowledge units before any audit rule, threshold, or rewrite task is scoped, and the measurement report MUST be committed as an artifact of this change. Audit scope MUST include only defect classes whose measurement is non-zero, with the measured counts cited.

#### Scenario: Defect class measured zero is closed with evidence
- **WHEN** the Phase 0 scan reports 0 hits for a candidate defect class (slot placeholders, region content leakage, exact duplicate bodies) on the live corpus
- **THEN** that class is excluded from the audit scope in this change
- **AND** the measurement report records the class and the zero count

#### Scenario: Region residual is classified before counting as a defect
- **WHEN** region_lint matches a body string that is a legitimate national-law reference (a SAR/region a statute names by necessity, e.g. 台湾地区 in a cross-strait scope rule) or a scraped page footer (publisher signature line)
- **THEN** the match is classified as `legit_region` or `attribution` and reported separately from content-level region leakage
- **AND** content-level leakage count — not the raw match count — drives the audit scope

### Requirement: Consumption survey gates audit depth

The system MUST identify, with code-level evidence committed to the change notes, every consumer of `kind='clause'` knowledge units before any rewrite executes, and MUST scope whether a rewrite is worthwhile by that survey.

#### Scenario: Downstream-snapshot corpus with no live serving consumer
- **WHEN** the survey finds that `knowledge_units` is a downstream copy of the serving corpus (Qdrant `law-library`) read by `search_clauses`, with no `knowledge_units → Qdrant` re-embed path and no direct `kind='clause'` reader with a caller
- **THEN** LLM rewrite of the bodies is deferred (no observable downstream effect)
- **AND** the survey evidence is recorded in the change notes with `file:line` citations

### Requirement: Deterministic repair at the ingestion boundary

The system MUST repair the one defect class Phase 0 measured firing — PDF extraction line-break breakage inside article bodies — deterministically (no LLM), by the same normaliser applied both at ingestion time and to existing rows, and MUST NOT alter any non-whitespace character.

#### Scenario: Article body wrapped by PDF is joined
- **WHEN** a clause body contains interior newlines that are PDF line wraps (statutory Chinese is one paragraph per article)
- **THEN** the interior newlines are removed and the article-number separator line becomes a single space
- **AND** no CJK character is moved or dropped (only whitespace changes)
- **AND** the normaliser is wired into clause splitting so future adoptions carry no breakage

### Requirement: Lineage-safe, reversible writes

The system MUST NOT modify `provenance`, `derived_from`, `attrs`, `tags`, `tier`, or the `(kind, namespace, external_key)` upsert identity when repairing a body, and MUST persist the original body to `output/audit-ku/<id>.json` before any database write.

#### Scenario: Rollback per unit
- **WHEN** an applied repair needs reverting
- **THEN** the original body is restored from the audit result file by unit id
- **AND** only `body` and `updated_at` were ever written by the repair

### Requirement: Region lint gate as completion metric

The system MUST re-run the deterministic region lint after the repair batch and report per-class residuals (content vs legit_region/attribution) alongside completion, as a quality metric rather than a hard block.

#### Scenario: Post-batch lint report
- **WHEN** the repair batch completes
- **THEN** the terminal measurement lists residual region-lint matches per class, with content-level leakage separated from legitimate references
- **AND** extraction-artifact count is reported as the post-batch terminal value
