# prompt-compare Delta — async-compare-run-identity

## MODIFIED Requirements

### Requirement: Compare JSON API
The system SHALL provide a JSON API under `/api/compare` in the existing FastAPI app: `POST /api/compare` to create and run a compare (body: contract_type, rubric_name, task_desc, prompt names, mode, n_drafts, an optional integer `concurrency` bounding parallel draft generation, clamped to [1, 8] with default 1, and an optional boolean `async`), `GET /api/compare` to list recent compares, `GET /api/compare/{id}` to fetch the full grouped result, and `GET /api/compare/{id}/run/{run_id}/draft` to lazy-fetch a single run's `draft_text`. Each handler SHALL take the standard `db` dependency so tests can point it at a throwaway DB. The `concurrency` and `async` fields SHALL be additive: requests without them behave exactly as before.

When `async` is true, the endpoint SHALL create the compare row with status `running` before returning `201 {id, status: "running"}` immediately, execute the compare in a background thread, and record the final status (`done` or `failed`) when execution ends. When `async` is absent or false, the endpoint SHALL run the compare synchronously and return the grouped result with a `compare_id` as today. Every compare payload (single and list) SHALL carry a `status` field: `running`, `done`, `failed`, or `interrupted`. At application startup, any compare whose status is still `running` from a previous process SHALL be marked `interrupted`. `draft_text` SHALL NOT be included in list or detail payloads (lazy-fetch only), and runs SHALL NOT exist for `interrupted` compares beyond what completed before the interruption.

#### Scenario: Create and run a compare via API
- **WHEN** `POST /api/compare` is called with a valid area, prompt set, mode, and n_drafts (no `async` field)
- **THEN** the compare runs synchronously and returns the grouped result with a `compare_id`, exactly as before this change
- **AND** `GET /api/compare/{id}` returns the same grouped result thereafter

#### Scenario: Async create returns immediately with identity
- **WHEN** `POST /api/compare` is called with `async: true`
- **THEN** the response is `201 {id, status: "running"}` returned before any drafting begins (or within a small fixed bound)
- **AND** `GET /api/compare/{id}` returns `status: "running"` until execution ends, then `done` (or `failed`) with the full grouped result

#### Scenario: A refresh-visible run cannot be orphaned
- **WHEN** an async compare is `running` and the client disconnects or refreshes
- **THEN** the compare row remains visible in `GET /api/compare` with `status: "running"` and can be fetched again by id

#### Scenario: Interrupted runs are marked at startup
- **WHEN** the app starts and a compare row has `status: "running"` from a previous process
- **THEN** that compare is marked `interrupted` and its detail endpoint returns the partial state with that status instead of claiming it is running

#### Scenario: Create with a concurrency override
- **WHEN** `POST /api/compare` is called with `concurrency: 4` for 3 prompts × 2 drafts
- **THEN** the compare runs with at most 4 drafts generated simultaneously and the grouped result is identical in content and row order to a concurrency-1 run of the same inputs

#### Scenario: Concurrency outside the range is clamped
- **WHEN** `POST /api/compare` is called with `concurrency: 99`
- **THEN** the compare runs with effective concurrency 8 and succeeds

#### Scenario: Lazy-fetch a draft
- **WHEN** `GET /api/compare/7/run/42/draft` is called
- **THEN** the `draft_text` for run 42 is returned
- **AND** `draft_text` is NOT included in the default `GET /api/compare/{id}` payload (kept compact)

#### Scenario: API delegates to the service layer
- **WHEN** any compare endpoint runs
- **THEN** it delegates to `src/eval/compare.py` and maps service errors to HTTP statuses via the existing `app.py` handlers
