## 1. Phase 0 — Baseline commit (revert point)

- [x] 1.1 Reconcile `openspec/changes/add-contract-generation-modes/tasks.md`: memory says "done & green" but openspec shows 0/25 checked. Either check off genuinely-completed tasks or note the discrepancy. Decide whether Phase 0 commits a "complete" or "in-progress" baseline.
- [x] 1.2 Verify the in-flight feature works: run the generation-modes test suite (`tests/test_generation_modes.py`) and confirm green before committing.
- [x] 1.3 Stage the 7 untracked files (`src/web/routes/generation.py`, `src/web/static/generation-panel.js`, `tests/test_generation_modes.py`, `openspec/changes/add-contract-generation-modes/`) and the 11 modified files (`scripts/generate_contract_templates_llm.py`, `src/eval/store.py`, `src/settings.py`, `src/web/app.py`, `src/web/models.py`, `src/web/static/style.css`, `src/web/templates/contract_detail.html`, `tests/conftest.py`, `tests/test_clauses_tag_review.py`, `tests/test_contract_context_api.py`, `tests/test_v3_rubrics.py`).
- [x] 1.4 Commit as a single baseline commit. Do NOT include refactor or auth work. Commit message records the tasks.md reconciliation outcome.

## 2. Phase 1 — Router registration & dependency typing (code, no behavior change)

- [x] 2.1 Remove the `try/except ImportError` block in `src/web/app.py:133-147`; replace with explicit unconditional `include_router` for all 7 HTML routers (`pages`, `law_info`, `search`, `contracts`, `clauses`, `dashboard` — confirm the full set). A missing router now fails loudly at startup.
- [x] 2.2 Define a `DbConn` Protocol in `src/web/deps.py` describing the borrowed-connection surface (`cursor()`, `commit()`, context-manager protocol). Keep `get_db()` returning a real Postgres connection; annotate its return as `DbConn`.
- [x] 2.3 Replace `db: Path` annotations in `src/web/routes/pages.py` (~13 handlers) with `db: DbConn = Depends(get_db)`.
- [x] 2.4 Align `contract_context.py` and `generation.py` from `db: Any` to `db: DbConn` for consistency.
- [x] 2.5 Run the full test suite; confirm green. Commit as "refactor: explicit router registration + honest DB typing".

## 3. Phase 1 — Naming collision & audit ownership

- [x] 3.1 Move `src/docs/` (the code package: `__init__.py`, `slots.py`, `generator.py`) to `src/generator/`. Update all `from src.docs...` / `import src.docs` references across `src/`, `scripts/`, `tests/`. NOTE: left a thin `src/docs/__init__.py` compatibility shim so out-of-scope siblings (`contract-review-agent`, `fd-coding-law-bench-mcp`) that still `from src.docs import ...` keep resolving without a code change.
- [x] 3.2 Sharpen the `audit.py` boundary: add module docstrings to `src/clauses/audit.py` (clause-library audit: rows, tag hygiene, dedup) and `src/contracts/audit.py` (assembled-contract audit: section coverage, slot fill, coherence). No merge.
- [x] 3.3 Run the full test suite; confirm green. Commit as "refactor: resolve src/docs name collision + audit ownership docstrings". (committed 61e4020; subset runs green, full-suite baseline = 9 pre-existing content-count drift failures, unchanged from pre-refactor.)

## 4. Phase 1 — Repo hygiene: archive, delete clutter, harden .gitignore

- [x] 4.1 Create `scripts/archive/` and move historical migration scripts (`backfill_*`, `seed_*`, `retag_*`) and leading-underscore probes (`_p2_*.py`, `_probe_models.py`, `_regression_gate.py`, `_seed_subtypes.py`, `_verify_catb_assembly.py`) there. Keep git-tracked (not deleted). (26 scripts moved; the `seed_contract_rubrics.py` ↔ `seed_sample_local_rubric.py` sibling-import pair moved together so the bare `from seed_sample_local_rubric import` still resolves.)
- [x] 4.2 Delete one-shot debug scripts in `output/` (`_fix_*.py`, `_inspect_*.py`, `_*_rollback.json`, `_create_gap_fill_*.py`) — `grep` confirmed zero imports. Deleted all 10 (untracked under gitignored `output/`).
- [x] 4.3 Delete stray root files: `test_analysis.json`, `prompts.md` (0-byte), `extract_batch_results.py`, all `.DS_Store` (src+root scope; none were git-tracked).
- [x] 4.4 Zombie-DB sweep: `git rm`'d the 6 zero-reference SQLite DBs (`db/evaluation.db`, `db/lawbench.db`, `data/app.db`, `data/law_bench.db`, `data/lawbench.db`, `data/evaluation.db`). KEPT `db/evaluation_rules.db` — it is the `DEFAULT_DB` sentinel referenced in ~40 function default-args and compared via `db is DEFAULT_DB` in `src/eval/db.py`; `db.py` redirects it to Postgres at runtime, so the file itself is never opened but must exist as a sentinel value.
- [x] 4.5 `.gitignore` already had `__pycache__/`, `*.egg-info/`, `.DS_Store`, `**/.DS_Store`, `output/`, `output/contracts/`. No tracked files under those patterns needed `git rm --cached` (the tracked zombie DBs were handled in 4.4; no tracked `.DS_Store` or `output/` files existed). Commit as "chore: archive migration scripts, remove debug scratch + zombie DBs, harden gitignore".

## 5. Phase 2 — Auth foundation: config & api_keys table

- [ ] 5.1 Add auth config to `src/settings.py`: `LOGTO_ENDPOINT`, `LOGTO_CLIENT_ID`, `LOGTO_CLIENT_SECRET`, `LOGTO_REDIRECT_URI`, `AUTH_SESSION_SECRET`, `AUTH_SESSION_TTL` (default e.g. 7d). Add to a new `AUTH_REQUIRED_VARS` list with fail-fast `ConfigError` on missing.
- [ ] 5.2 Create the `api_keys` migration: table `api_keys(id, key_hash, user_id, label, scopes, created_at, last_used_at, revoked_at)`. Index on `key_hash`. Run against the Postgres DSN from `settings.DATABASE_URL`.
- [ ] 5.3 Add `itsdangerous` (or confirm `starlette` Session middleware) to `pyproject.toml` dependencies; `uv sync`.

## 6. Phase 2 — Auth package: logto, session, apikey, deps

- [ ] 6.1 `src/web/auth/logto.py`: OIDC discovery fetch, JWKS fetch + cache with refetch-on-unknown-`kid`, `validate_jwt(token)` → claims (checks `iss`, `exp`, signature). Token-exchange helper for the authorization code.
- [ ] 6.2 `src/web/auth/session.py`: session cookie sign/verify using `AUTH_SESSION_SECRET`; `set_session(response, user)` / `get_session(request)` / `clear_session(response)`. Cookie flags: httpOnly, Secure, SameSite=Lax.
- [ ] 6.3 `src/web/auth/apikey.py`: `hash_key(plaintext)` (salted), `create_key(user_id, label, scopes)` (stores hash, returns plaintext once), `verify_key(plaintext)` → user or None (updates `last_used_at`), `revoke_key(id, user_id)`.
- [ ] 6.4 `src/web/auth/deps.py`: `get_current_user(request)` — attempts cookie → Bearer JWT → X-API-Key in order; short-circuits on present-but-invalid (no fallthrough to weaker method); attaches `request.state.user` (dataclass: `sub, name, email, scopes, channel`). `require_scope(scope)` dependency wrapper. Raises `HTTPException(401)` when no valid credential.

## 7. Phase 2 — Auth routes

- [ ] 7.1 `src/web/routes/auth.py`: `GET /auth/login` (PKCE code_challenge, 302 to Logto authorize), `GET /auth/callback` (exchange code, validate ID token, set cookie, 302 to `/`; 400 on invalid state/code), `GET /auth/logout` (clear cookie, redirect to Logto end-session or `/`).
- [ ] 7.2 `POST /api/keys` (create — returns plaintext once, 201), `GET /api/keys` (list caller's keys, no plaintext/hash), `DELETE /api/keys/{id}` (revoke; 404 if not owner, not 403). All require `get_current_user`.
- [ ] 7.3 Register `auth.router` in `app.py` such that `/auth/*` and `/api/keys` are reachable; verify exemption ordering (constructor-level `Depends` must not 401 the login flow).

## 8. Phase 2 — Wire auth into the app & exemption

- [ ] 8.1 In `create_app()`, add `dependencies=[Depends(get_current_user)]` at the `FastAPI(...)` constructor level so every route inherits auth.
- [ ] 8.2 Confirm `/healthz` is exempt (it is a direct `@app.get`, not a router — verify it still returns 200 without credentials; if the constructor dep applies, add an explicit no-op override).
- [ ] 8.3 Verify `/auth/login` returns 302 (not 401) when unauthenticated — write a focused test. If the constructor dep catches it, exclude via `auth.router` `dependencies=[]` override or a `get_current_user` that no-ops on `/auth/*`.

## 9. Phase 2 — Test fixup & auth tests

- [ ] 9.1 Update `tests/conftest.py`: install `app.dependency_overrides[get_current_user] = <stub returning a test user>` so the 54 existing test files keep passing without per-test tokens.
- [ ] 9.2 Write auth-specific tests (`tests/test_web_auth.py` or similar): 401 on protected route without creds; 200 with valid cookie; 200 with valid Bearer; 200 with valid API key; 401 on present-but-invalid Bearer (no fallthrough); `/healthz` open; `/auth/login` 302; key create/list/revoke lifecycle; cross-user revoke returns 404.
- [ ] 9.3 Run the full test suite; confirm green. Commit Phase 2.

## 10. Phase 2 — Sub-project impact verification & live wiring

- [ ] 10.1 Grep `contract-review-agent/` and `fd-coding-law-bench-mcp/` for HTTP calls to the web app (`httpx`, `requests`, `localhost:8010` / configured port). For any caller found: provide an API key or add a documented internal-exempt loopback rule.
- [ ] 10.2 Confirm `fd-coding-law-bench-mcp`'s MCP server connects to Postgres directly (not via `src/web` HTTP). If it does call HTTP, it needs an API key — wire one and document.
- [ ] 10.3 Collect Logto connection details from user (endpoint, client_id/secret, JWKS URI, redirect URI host). Set env vars; smoke-test login → callback → cookie → protected route → logout, and API-key create → use → revoke against the live deploy.
- [ ] 10.4 Final full-suite run on the live-configured app. Commit any follow-up. Mark the change ready to archive.
