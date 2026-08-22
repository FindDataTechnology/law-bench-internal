# contract-artifact-storage Delta Spec

## MODIFIED Requirements

### Requirement: Contract Artifacts Table
The system SHALL maintain the `contract_artifacts` table with the existing columns and SHALL additionally carry `docx_key_slotted` (text, nullable) and `pdf_key_slotted` (text, nullable). The `docx_key`/`pdf_key` columns hold the MinIO object keys for the **final** variant (non-slotted, rendered with `slot_style="underline"`); `docx_key_slotted`/`pdf_key_slotted` hold the keys for the **slotted** variant (fillable, rendered with `slot_style="highlight"`). Both pairs are nullable so a row may carry one, the other, or both. `ensure_schema()` SHALL add the two new columns idempotently via `ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS`. The unique constraint on `body_hash` is unchanged.

#### Scenario: Fresh database has the slotted columns
- **WHEN** `ensure_schema()` runs against a fresh database
- **THEN** the `contract_artifacts` table has `docx_key_slotted` and `pdf_key_slotted` columns (nullable), in addition to all previously listed columns and the unique index on `body_hash`

#### Scenario: Existing rows have null slotted keys until refreshed
- **WHEN** an existing artifact row (created before this change) is read
- **THEN** its `docx_key_slotted` and `pdf_key_slotted` are null until a subsequent `generate_stored` (or `--force`) run produces the slotted variant for that row

### Requirement: Content-Addressed Dedup
The system SHALL compute `body_hash = md5(body_text)` for every generated contract. The body is variant-independent: clause assembly produces one `body_text`, and the final vs. slotted variants differ only in the `slot_style` passed to `create_docx`. Before inserting, the system SHALL `SELECT` by `body_hash`. If a row exists it is reused (`reused: true`), and for each requested format the system SHALL ensure BOTH the final key (`{fmt}_key`) and the slotted key (`{fmt}_key_slotted`) are present — generating + uploading whichever is missing; already-stored keys are not regenerated or re-uploaded. If no row exists, it inserts a new one (`reused: false`) with both key pairs populated for each requested format. With `force=True`, both the final and slotted keys for each requested format are re-uploaded (overwriting the MinIO objects). In the by-type path, dedup applies per combination, so combinations producing the same body collapse to one artifact carrying both variants.

#### Scenario: Same inputs reuse the artifact and skip re-upload of both variants
- **WHEN** `POST /api/contracts/sale/generate-stored` is called twice with `{"scenario": "生鲜乳购销", "format": "docx"}`
- **THEN** both responses return the same `artifact_id`; the second has `reused: true`; no new MinIO object is uploaded on the second call (neither final nor slotted)

#### Scenario: Missing slotted variant is filled on an existing artifact
- **WHEN** an artifact row exists with `docx_key` non-null but `docx_key_slotted` null, and `POST /api/contracts/sale/generate-stored` is called again with `{"scenario": "...", "format": "docx"}`
- **THEN** the response returns the same `artifact_id`; the row's `docx_key_slotted` becomes non-null; `docx_key` is not re-uploaded

### Requirement: Generate-and-Store Endpoint
The by-tag and by-type paths SHALL produce BOTH variants for each requested format from the same assembled `body_text`: the final variant (`slot_style="underline"`, uploaded under `MINIO_ARTIFACTS_PREFIX`) and the slotted variant (`slot_style="highlight"`, uploaded under `MINIO_ARTIFACTS_SLOTTED_PREFIX`). The by-tag response SHALL additionally include `docx_url_slotted` and `pdf_url_slotted` (the `?variant=slotted` download URLs, or `null` when that format was not produced); the by-type summary's per-artifact entries SHALL likewise include `docx_url_slotted` and `pdf_url_slotted`. For `format: "markdown"` no files are uploaded and `docx_url`/`pdf_url`/`docx_url_slotted`/`pdf_url_slotted` are all `null` (the row still records `body_text`/`body_hash`). Coherence-gate (422 by-tag), unknown-type (404), and per-combo-failure (reported in `failures`) semantics are unchanged.

#### Scenario: By-tag generates both variants and returns slotted URLs
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"scenario": "生鲜乳购销", "format": "both"}`
- **THEN** it returns 200 with `{artifact_id, docx_url, pdf_url, docx_url_slotted, pdf_url_slotted, body_text, slots, reused}` where `docx_url_slotted` and `pdf_url_slotted` are `/api/contracts/artifacts/{id}/download?format=...&variant=slotted` URLs; the row has non-null `docx_key`, `pdf_key`, `docx_key_slotted`, and `pdf_key_slotted`

#### Scenario: By-type summary entries carry slotted URLs
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "docx"}`
- **THEN** the summary's `artifacts` entries each have `docx_url` and `docx_url_slotted` (both non-null), in addition to `artifact_id`, `scenario`, `stance`, and `reused`

#### Scenario: Markdown format produces no files and null variant URLs
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "markdown"}`
- **THEN** it returns 200 with `docx_url`, `pdf_url`, `docx_url_slotted`, and `pdf_url_slotted` all null; the row has null `docx_key`/`pdf_key`/`docx_key_slotted`/`pdf_key_slotted`

### Requirement: Artifact Download Endpoint
The system SHALL expose `GET /api/contracts/artifacts/{id}/download` accepting a `format` query param (`docx` or `pdf`) and a `variant` query param (`final` (default) or `slotted`). `variant=final` SHALL stream the file at the `{format}_key` column; `variant=slotted` SHALL stream the file at the `{format}_key_slotted` column. The endpoint SHALL set `Content-Type` (`application/vnd.openxmlformats-officedocument.wordprocessingml.document` for docx, `application/pdf` for pdf) and `Content-Disposition: attachment`. A non-existent id, or an id without the requested (format, variant) stored, SHALL produce 404. It SHALL be documented in `/api/docs`.

#### Scenario: Download the slotted docx
- **WHEN** `GET /api/contracts/artifacts/{id}/download?format=docx&variant=slotted` is called for an artifact with `docx_key_slotted` non-null
- **THEN** it returns 200 with the docx content-type and a non-empty body streaming the slotted (highlight) variant

#### Scenario: Download defaults to the final variant
- **WHEN** `GET /api/contracts/artifacts/{id}/download?format=docx` is called (no `variant`)
- **THEN** it streams the file at `docx_key` (the final/underline variant), unchanged from prior behavior

#### Scenario: Download slotted when absent returns 404
- **WHEN** `GET /api/contracts/artifacts/{id}/download?format=docx&variant=slotted` is called for an artifact with `docx_key_slotted` null
- **THEN** it returns 404

### Requirement: MinIO Upload
The system SHALL upload generated docx/pdf files to the configured MinIO bucket (`MINIO_BUCKET`). The final variant SHALL upload under `MINIO_ARTIFACTS_PREFIX` (default `artifacts/`) with key `{prefix}{contract_type}/{artifact_id}.{ext}` (unchanged). The slotted variant SHALL upload under `MINIO_ARTIFACTS_SLOTTED_PREFIX` (default `artifacts-slotted/`) with key `{slotted_prefix}{contract_type}/{artifact_id}.{ext}`. Both variants SHALL use the native `minio` SDK with `MINIO_ENDPOINT`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`/`MINIO_SECURE` and SHALL bypass proxy env (`NO_PROXY=*`).

#### Scenario: Final and slotted files land in distinct prefixes
- **WHEN** `POST /api/contracts/sale/generate-stored` is called with `{"format": "docx"}`
- **THEN** the returned artifact's `docx_key` is `artifacts/sale/{artifact_id}.docx` and `docx_key_slotted` is `artifacts-slotted/sale/{artifact_id}.docx`; both objects exist in `MINIO_BUCKET`

### Requirement: MCP Generate-Stored and Download Tools
The system SHALL expose MCP tools mirroring the HTTP endpoints. `contract_generate_stored(contract_type, format="docx", tags=None, stance=None, custom_clause_ids=None)` SHALL return the slotted URLs (`docx_url_slotted`/`pdf_url_slotted`) alongside the final URLs in both the single-variant and all-combinations responses. `contract_download(artifact_id, format=None, variant="final")` SHALL accept a `variant` argument (`final` default, `slotted`) and return the metadata plus the download URL for the requested variant. Both SHALL be registered with the `contracts` tag.

#### Scenario: contract_download with variant=slotted returns the slotted URL
- **WHEN** `contract_download(artifact_id, variant="slotted")` is called for an artifact with `docx_key_slotted` non-null
- **THEN** it returns the artifact metadata and a `download_url` pointing at `/api/contracts/artifacts/{id}/download?format=docx&variant=slotted`

### Requirement: Settings and Schema Wiring
The system SHALL add `MINIO_ARTIFACTS_SLOTTED_PREFIX` (default `artifacts-slotted/`) to `src/settings.py` and SHALL add `docx_key_slotted`/`pdf_key_slotted` to `src/eval/store.py` — both in the `CONTRACT_ARTIFACTS_SCHEMA` DDL and in `_ADDITIVE_COLUMNS` as `ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS` — so `ensure_schema()` creates them on existing databases. The download endpoint's `?variant=` query param SHALL appear in the OpenAPI schema at `/api/docs`.

#### Scenario: MINIO_ARTIFACTS_SLOTTED_PREFIX defaults to artifacts-slotted/
- **WHEN** `MINIO_ARTIFACTS_SLOTTED_PREFIX` is unset in the environment
- **THEN** `src.settings.MINIO_ARTIFACTS_SLOTTED_PREFIX == "artifacts-slotted/"`

#### Scenario: Variant param appears in the OpenAPI schema
- **WHEN** `GET /openapi.json` is fetched
- **THEN** the `GET /api/contracts/artifacts/{id}/download` path's parameters include a `variant` query parameter
