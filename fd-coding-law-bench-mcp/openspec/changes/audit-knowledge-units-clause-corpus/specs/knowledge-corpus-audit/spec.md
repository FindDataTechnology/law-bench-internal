## ADDED Requirements

### Requirement: Phase 0 real-data measurement precedes scoping

The system MUST run a deterministic, zero-LLM measurement pass over all `kind='clause'` knowledge units before any audit rule, threshold, or rewrite task is scoped, and the measurement report MUST be committed as an artifact of this change. Audit scope MUST include only defect classes whose measurement is non-zero, with the measured counts cited.

#### Scenario: Defect class measured zero is closed with evidence
- **WHEN** the Phase 0 scan reports 0 hits for a candidate defect class (e.g. slot placeholders, if the consumption survey confirms the new corpus shape carries none)
- **THEN** that class is excluded from the audit scope in this change
- **AND** the measurement report records the class, the query used, and the zero count

#### Scenario: Region residual is classified before counting as a defect
- **WHEN** region_lint matches a body string that is a legal-document source attribution (e.g. a law-title citation or issuing-agency signature line) rather than clause content naming a local authority
- **THEN** the match is classified as attribution and reported separately from content-level region leakage
- **AND** content-level leakage count drives the audit scope, not the raw match count

### Requirement: Consumption survey gates audit depth

The system MUST identify, with code-level evidence committed to the change notes, every consumer of `kind='clause'` knowledge units (RAG search path, generation path, publications) before rewrite tasks execute, and MUST scope blast-radius priority by that survey.

#### Scenario: Consumer list determines rewrite eligibility
- **WHEN** a unit is flagged for rewrite
- **THEN** the flag records which surveyed consumers surface that unit
- **AND** units surfaced by zero live consumers are deferred, not rewritten

### Requirement: Multi-model classify with deterministic pre-filter

The system MUST classify each in-scope unit via three models voting by majority into exactly one of `ok`, `region_leak`, `missing_slot`, `wrong_scenario`, `extraction_artifact`, `duplicate`, carrying `suggested_fix` and `confidence`; a deterministic regex/lint pre-filter MUST gate which units reach the LLM stage.

#### Scenario: Pre-filter admits only lint hits
- **WHEN** a unit has zero region_lint matches and no extraction-artifact regex hits
- **THEN** it is not sent to the classify stage unless the Phase 0 measurement established a defect class that the pre-filter cannot detect
- **AND** the classify trio verdicts merge by majority; all-differ or confidence < 0.6 marks the unit `uncertain` and keeps it unchanged

### Requirement: Rewrite verification keeps original on failure

The system MUST verify each rewritten unit body with a different model than the rewriter, checking defect fixed and legal point preserved; failed verification keeps the original body.

#### Scenario: Verify fails
- **WHEN** the verify model reports a dropped legal obligation or unfixed defect
- **THEN** the original body is kept and the unit is logged to the audit result file for manual review

### Requirement: Lineage-safe, reversible writes

The system MUST NOT modify `provenance`, `derived_from`, or the `(kind, namespace, external_key)` upsert identity when writing a rewritten body, and MUST persist the original body plus verdict metadata to `output/audit-ku/<unit_ref>.json` before any database write.

#### Scenario: Rollback per unit
- **WHEN** an applied rewrite needs reverting
- **THEN** the original body is restored from the audit result file by unit reference
- **AND** the re-embed dirty flag for that unit's corpus chunks is re-set

### Requirement: Re-embedding after rewrite

The system MUST mark the affected library corpus chunks dirty after any accepted body rewrite, and the dirty set MUST be re-embedded (or reported as an explicit pending-reembed count with owner) before the audit batch is declared complete.

#### Scenario: Rewritten unit still served stale
- **WHEN** a rewritten unit's corpus chunk has not been re-embedded
- **THEN** the batch completion report lists it under pending-reembed with a count
- **AND** the batch is not marked complete while pending-reembed is non-zero

### Requirement: Duplicate detection via external_key equivalence

The system MUST detect duplicate clause units by grouping on the `body_hash` component of `external_key` (plus `namespace`), and MUST resolve duplicates by demoting non-canonical units without invoking any LLM.

#### Scenario: Exact duplicates share body_hash
- **WHEN** two or more `kind='clause'` units in the same namespace share the same `body_hash` component in `external_key`
- **THEN** all but the canonical (lowest unit id) are demoted from the serving corpus by the mechanism the consumption survey identified (e.g. excluded from library sources or published corpus)
- **AND** no LLM call is made for duplicate detection

### Requirement: Region lint gate as quality metric

The system MUST run the deterministic region lint (31 provinces + agency patterns including 委/局/厅 abbreviations) after every rewrite batch and report per-unit residuals and totals alongside completion, as a quality metric rather than a hard block.

#### Scenario: Post-batch lint report
- **WHEN** an audit batch completes for a namespace
- **THEN** the lint report lists residual matches per unit, with attribution-classified matches separated from content-level leakage
