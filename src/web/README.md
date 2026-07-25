# Evaluation Rules Manager (web)

A local web app to browse and manage the evaluation rubrics and criteria stored
in `db/evaluation_rules.db` (the same SQLite file the contract-eval pipeline
uses). Built with FastAPI + Jinja2 — a single `uv run` process, no JavaScript
build step.

## Run it

```bash
bash scripts/serve_web.sh
# or pick a port:
RULES_WEB_PORT=8088 bash scripts/serve_web.sh
```

Then open <http://127.0.0.1:8010>. It binds to `127.0.0.1` only (local dev tool,
no auth).

## What you can do

- **Browse** all rubrics (harbor + local) and drill into a rubric's criteria.
- **Manage local rubrics**: create, edit metadata, delete; add / edit / reorder
  / delete criteria.
- **Harbor rubrics are read-only** (shown with a purple badge). Refresh them with
  the “Re-extract harbor” button, which re-runs `scripts/extract_harbor_rules.py`
  and leaves local rubrics untouched. Harbor must be installed
  (`uv tool install harbor`) for that button to succeed.

## JSON API

Everything the UI does is also exposed as JSON under `/api` (interactive docs at
[`/api/docs`](http://127.0.0.1:8010/api/docs)):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/rubrics` | list rubrics with criterion counts |
| GET | `/api/rubrics/{name}` | a rubric + its ordered criteria |
| POST | `/api/rubrics` | create a local rubric (with optional criteria) |
| PATCH | `/api/rubrics/{name}` | update a local rubric's metadata |
| DELETE | `/api/rubrics/{name}` | delete a local rubric (cascades to criteria) |
| POST | `/api/rubrics/{name}/criteria` | add a criterion |
| PATCH | `/api/rubrics/{name}/criteria/{cid}` | update a criterion |
| DELETE | `/api/rubrics/{name}/criteria/{cid}` | delete a criterion |
| POST | `/api/rubrics/{name}/criteria/reorder` | reorder criteria by id list |
| POST | `/api/harbor/extract` | re-run harbor extraction |

Errors return a JSON `{"error": "..."}` with status `400` (validation),
`403` (harbor read-only), `404` (not found), or `409` (duplicate name).

## Layout

```
src/web/
  app.py            # FastAPI app factory, static mount, exception handlers
  models.py         # Pydantic request models
  routes/api.py     # JSON API under /api (+ shared harbor-extraction helper)
  routes/pages.py   # server-rendered HTML routes
  templates/        # Jinja2: base, rubrics_list, rubric_detail, rubric_form
  static/           # style.css, app.js
src/eval/manage.py  # CRUD service (harbor-immutability, uniqueness, cascade)
```
