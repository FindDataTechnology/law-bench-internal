# Design: async-compare-run-identity

## Context

Today `POST /api/compare` runs synchronously inside the request; the compare row and its runs are persisted by `run_compare` at the end. The web client holds the only knowledge of an in-flight run (a pending fetch). The compares table (`src/eval/store.py`) has no status notion — existence implies completion.

## Goals / Non-Goals

**Goals:** give every web-launched run a durable identity from the moment it starts; make refresh/abandon recoverable; kill the accidental-duplicate path. Keep the synchronous API byte-compatible.

**Non-Goals:** server-side cancellation of in-flight LLM calls; multi-worker coordination (single-operator, one uvicorn process); queuing/retries; progress percentages (status granularity is running/done/failed/interrupted — coarse progress stays out of scope, the elapsed timer carries the wait).

## Decisions

1. **Additive `async` flag on the existing endpoint, not a second endpoint.** One resource, two execution modes; MCP/CLI and any scripts calling without the flag see zero change. A separate `/api/compare/async` would fork the schema of the same resource for no compatibility gain.
2. **Status column on `compares` via `ensure_schema` `ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'done'`.** Default `done` makes every historical row truthful without a backfill and keeps old DBs working the moment the column lands. Alternative rejected: a separate jobs table — the compare row *is* the job; a second table would need its own reconcile logic for what is inherently one lifecycle.
3. **Execution: a daemon `threading.Thread` per async run.** The eval layer already runs drafts on a ThreadPoolExecutor bounded by `concurrency`; one supervising thread per compare composes with it and dies with the run. No celery/queue dependency for a single-operator tool. Error path: catch everything from `run_compare`, write `status='failed'` + the error message into the row (reuse the existing error columns if present, else a `status_detail` column added the same additive way).
4. **Startup reaper marks stragglers `interrupted`.** In `create_app`'s startup (alongside `_load_tag_vocab`, best-effort try/except): `UPDATE compares SET status='interrupted' WHERE status='running'`. Correct because exactly one process writes compares in this deployment; a reaper on a multi-worker deployment would need a heartbeat column — recorded as a scaling note, not built now.
5. **Client: poll `GET /api/compare/{id}` every 3s** while `running` (the endpoint already returns the grouped result; while running it returns meta + status with empty runs — service layer returns early-stage shape). Keep the existing elapsed timer and cancel semantics; cancel stops polling and shows a link to the running compare. WIP gains `last_run_id` so `/compare/new` can render "上次运行 #N 进行中 →" from the list payload without a new endpoint.
6. **Duplicate guard v2**: before async submit, if any listed compare with `status='running'` has the same normalized config (contract_type+rubric+prompts+n_drafts — compare list already carries these fields), prompt: open it or start anyway. The existing body-hash guard remains for the failed/cancelled case.

## Risks / Trade-offs

- [Thread dies mid-run on process crash → stale `running` row until next startup] → Mitigation: the startup reaper; the detail page also treats `running` rows older than a generous bound (e.g. 24h) as suspect and says so, without mutating server state from a read path.
- [List payload grows a status per row] → Negligible; column is already read for ordering.
- [Two browsers submit identical configs concurrently] → Guard v2 is advisory (confirm), not a lock; acceptable for one operator.

## Migration Plan

Deploy: `ensure_schema` adds the column lazily on first connect (idempotent, no downtime); old rows read as `done`. Rollback: the column is ignored by old code; revert is clean.

## Open Questions

- None blocking; the multi-worker heartbeat is explicitly a scaling note, not a now-decision.
