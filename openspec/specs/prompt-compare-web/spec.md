# prompt-compare-web Specification

## Purpose
TBD - created by syncing change prompt-compare-evaluation. Update Purpose after implementation.
## Requirements
### Requirement: Compare JSON API
The system SHALL provide a JSON API under `/api/compare` in the existing FastAPI app: `POST /api/compare` to create and run a compare (body: contract_type, rubric_name, task_desc, prompt names, mode, n_drafts), `GET /api/compare` to list recent compares, `GET /api/compare/{id}` to fetch the full grouped result, and `GET /api/compare/{id}/run/{run_id}/draft` to lazy-fetch a single run's `draft_text`. Each handler SHALL take the standard `db` dependency so tests can point it at a throwaway DB.

#### Scenario: Create and run a compare via API
- **WHEN** `POST /api/compare` is called with a valid area, prompt set, mode, and n_drafts
- **THEN** the compare runs synchronously (or async with a job id - see Open Questions) and returns the grouped result with a `compare_id`
- **AND** `GET /api/compare/{id}` returns the same grouped result thereafter

#### Scenario: Lazy-fetch a draft
- **WHEN** `GET /api/compare/7/run/42/draft` is called
- **THEN** the `draft_text` for run 42 is returned
- **AND** `draft_text` is NOT included in the default `GET /api/compare/{id}` payload (kept compact)

#### Scenario: API delegates to the service layer
- **WHEN** any compare endpoint runs
- **THEN** it delegates to `src/eval/compare.py` and maps service errors to HTTP statuses via the existing `app.py` handlers

### Requirement: Compare Web UI
The system SHALL provide HTML pages (`/compare` list, `/compare/new` build-and-run, `/compare/{id}` result) mirroring the existing rubric/prompt UI pattern, with a `Compare` nav link in `base.html`. The build form SHALL render its `contract_type` field, `rubric` select option labels, and prompt-pick checkbox labels (prompt name and contract_type) with localized labels and localized placeholders per `data-label-i18n` (raw-key fallback for unmapped or user-authored values). The list SHALL render `contract_type`, `rubric_name`, and `mode` as localized labels in the active locale (raw-key fallback). The result page SHALL render a per-criterion matrix: rows = rubric criteria, columns = prompts (header = the localized `prompt_type` label, falling back to the prompt's localized display title per `data-label-i18n`, then the raw prompt `name`), cell = verdict (n_drafts = 1) or `k/N` pass-rate (n_drafts > 1). The result meta line (`{ct} · {rubric} · {mode} · N={n}`) SHALL be localized in the active locale via the client-bootstrapped data-label catalog (`window.__LABELS__`). Each cell SHALL be expandable to show the judge reasoning; each column SHALL offer a "view draft" action that lazy-loads `draft_text`. Run-level `n_passed`/`n_criteria` and mean pass-rate SHALL be shown as secondary headlines.

#### Scenario: Build and run a compare in the browser
- **WHEN** the user selects an area (contract_type, rubric, task), picks ≥2 prompts, sets mode and n_drafts, and submits
- **THEN** the compare runs and the result page renders the criteria × prompts matrix

#### Scenario: The matrix uses localized prompt_type as column headers
- **WHEN** a compare result is rendered for prompts with `prompt_type` set, in locale `zh`
- **THEN** each column header shows the localized label for the prompt's `prompt_type` (e.g. `baseline` -> `基线`)
- **AND** a blank `prompt_type` falls back to the prompt's localized display title, then to the raw prompt `name`

#### Scenario: Inspect a cell and a draft
- **WHEN** the user clicks a matrix cell
- **THEN** the judge reasoning for that criterion/prompt is revealed
- **AND** when the user clicks "view draft" for a column, the `draft_text` is lazy-fetched and shown

#### Scenario: The result meta line is localized
- **WHEN** a compare detail page renders in `zh` for a compare with `contract_type = sale`, `rubric_name = contract_sale_v1`, `gen_mode = drafter-only`, `n_drafts = 1`
- **THEN** the meta line shows `买卖合同 · 买卖合同评价规则 · 仅起草 · N=1`

#### Scenario: The compare list shows localized labels
- **WHEN** a user views `/compare` with locale `zh` for a compare with `contract_type = sale` and `gen_mode = drafter-only`
- **THEN** the contract_type cell shows `买卖合同` and the mode cell shows `仅起草`

#### Scenario: The build form uses localized placeholders
- **WHEN** a user opens `/compare/new` with locale `zh`
- **THEN** the `contract_type` input placeholder is a Chinese example (e.g. `如：买卖合同`)
- **AND** prompt-pick checkboxes show the prompt's localized display title and contract_type label

### Requirement: localStorage Mirror of Compare State
The compare web UI SHALL persist state to browser `localStorage` in two layers: (1) WIP form state - selected prompt names, task, rubric, mode, and n_drafts - saved on every change and restored on page load so a refresh does not lose an in-progress config; (2) a compact results mirror per compare - the matrix (prompt_type headers, criterion titles, verdicts/pass-rates) and judge reasoning - saved under a byte-budget LRU cap (~4 MB, evicting the oldest compares first) and a versioned cache key. `draft_text` SHALL NOT be mirrored. On load, the UI SHALL paint from `localStorage` instantly then reconcile with the server, with the DB as source of truth (DB wins on conflict; a deleted compare is dropped from the cache).

#### Scenario: WIP form state survives refresh
- **WHEN** the user partially configures a compare (selects prompts, types a task) and refreshes the page
- **THEN** the form is restored to its pre-refresh state from `localStorage`

#### Scenario: Results are mirrored for instant review
- **WHEN** a compare completes
- **THEN** its compact matrix + reasoning is written to `localStorage`
- **AND** re-opening `/compare/{id}` paints from `localStorage` before the server responds
- **AND** `draft_text` is not present in the mirrored entry

#### Scenario: Byte-budget eviction keeps the cache under quota
- **WHEN** a `localStorage` write would exceed the ~4 MB budget
- **THEN** the oldest mirrored compares are evicted (LRU) until the write fits
- **AND** the current compare's entry is never partially written

#### Scenario: Stale cache is invalidated by version
- **WHEN** the result shape changes (cache key version bump) and the page loads
- **THEN** the old-version cache entries are discarded, not served

#### Scenario: DB wins on conflict
- **WHEN** the server's compare row is newer than the cached mirror, or the compare was deleted on the server
- **THEN** the UI overwrites the cache from the DB (or drops the entry if deleted) and renders the DB state
