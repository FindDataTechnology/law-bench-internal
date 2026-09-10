# Proposal: async-compare-run-identity

## Why

Both critique runs flagged this P1: the compare run has no identity until the synchronous POST resolves — refresh or tab-close orphans a server-side run the operator can never find again, the cancel copy has to admit "服务器可能仍在运行", and retry after a network error can duplicate a succeeded run. The original `prompt-compare-web` spec left this as an explicit open question ("runs synchronously (or async with a job id - see Open Questions)"); the critique answers it: runs need identity.

## What Changes

- **Async mode (additive)**: `POST /api/compare` accepts an optional `async: true`. When set, it creates the compare row with status `running` immediately, executes in a background thread, and returns `201 {id, status: "running"}`. Without the flag, behavior is byte-for-byte today's synchronous run (MCP/CLI/API callers unaffected).
- **Status on reads**: `GET /api/compare/{id}` and the list payload carry a `status` field (`running` / `done` / `failed` / `interrupted`); done/failed responses include the same grouped result as today. The compares table gains a `status` column (additive migration via `ensure_schema`).
- **Interrupted-run hygiene**: at app startup, any compare left `running` by a dead process is marked `interrupted` (single-operator tool, no cross-process coordination needed).
- **Web UI adopts the run**: the form submits async, polls the compare every ~3s with the existing elapsed timer, and redirects on `done`; on failure it shows the error inline with retry. The compare list renders `running` rows with a status mark so a mid-run refresh reconnects via one click instead of orphaning. The duplicate-submit guard upgrades: same body + a still-`running` compare on the server → offer "watch #N" before starting a new one.
- **Honest cancellation unchanged**: cancel still aborts only the client wait; server-side LLM cancellation is out of scope.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `prompt-compare`: the Compare JSON API requirement gains the additive async mode, status field, and interrupted-run semantics.
- `prompt-compare-web`: the Compare Run Instrumentation requirement gains polling, the in-flight list view, and run adoption after refresh.

## Impact

- `src/eval/compare.py` / `src/eval/store.py` / `src/eval/db.py` — status column, async execution path, startup reaper.
- `src/web/routes/api.py` — async branch on POST; status in payloads.
- `src/web/routes/pages.py` + templates + `app.js` — polling submit, in-flight list marks, adoption link.
- Tests: async lifecycle (running → done / failed / interrupted), sync-path regression (no flag = today's behavior).
