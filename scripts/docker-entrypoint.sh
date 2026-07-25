#!/bin/sh
# Container entrypoint: self-heal harbor rubrics, then serve the web app.
#
# Harbor is not installed in this image (it is a local `uv tool` only), so a
# stale PVC at /app/db - seeded before harbor extraction ever ran - would
# otherwise hide harbor's rubrics forever. `src.eval.harbor_seed` falls back to
# a bundled seed copy of harbor's rubric TOMLs shipped in the image, so this
# restores them idempotently on every boot. The heal is scoped to
# `source LIKE 'harbor:%'` rows; local rubrics and evaluation-run data are
# never touched.
set -e

.venv/bin/python -m src.eval.harbor_seed --db /app/db/evaluation_rules.db

exec .venv/bin/uvicorn src.web.app:app --host 0.0.0.0 --port 8010
