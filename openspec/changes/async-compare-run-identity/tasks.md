# Tasks: async-compare-run-identity

## 1. Store + service layer

- [ ] 1.1 `ensure_schema`: add `status TEXT NOT NULL DEFAULT 'done'` (+ `status_detail TEXT` if no error column fits) to `compares` via idempotent `ADD COLUMN IF NOT EXISTS`
- [ ] 1.2 `run_compare` gains an async execution path: create the row with `status='running'` + return its id immediately; supervise drafts/judging on a daemon thread; write `done`/`failed` (+ detail) at the end; service errors map to `failed`, never crash the thread silently
- [ ] 1.3 Startup reaper in `create_app`: mark still-`running` compares `interrupted` (best-effort try/except)
- [ ] 1.4 `get_compare`/`list_compares` payloads carry `status` (and `status_detail` on failed); `running` detail returns meta + status with empty runs

## 2. API

- [ ] 2.1 `POST /api/compare` accepts `async: bool = False`; true → 201 `{id, status:"running"}` via the new path; false/absent → today's synchronous behavior unchanged
- [ ] 2.2 Tests: async lifecycle (running → done; running → failed with detail; reaper marks interrupted), sync-path regression (response identical in shape and status code to pre-change), status present in list/detail

## 3. Web UI

- [ ] 3.1 `app.js` submit: send `async: true`; poll detail every 3s while `running`; navigate on `done`; inline error + re-enable on `failed`; cancel stops polling and links to the running compare; WIP stores `last_run_id`
- [ ] 3.2 Compare list: `running` rows get a localized status mark (badge family, no new colors); `interrupted` rows show their status honestly
- [ ] 3.3 `/compare/new`: if the last run is still `running`, show a one-click "上次运行 #N 进行中 →" line above the form
- [ ] 3.4 Duplicate guard v2: identical config already `running` → offer to open it or start anyway; keep the failed/cancelled body-hash guard

## 4. Verification

- [ ] 4.1 i18n keys zh/en for all new copy (running mark, interrupted, open-running, already-running confirm)
- [ ] 4.2 Full verify: web suites + new tests, render probe (`/compare` list + form), detector clean, `openspec validate async-compare-run-identity --strict`
