"""FastAPI application for browsing and managing evaluation rules.

Run locally with::

    uv run uvicorn src.web.app:app --reload --host 127.0.0.1 --port 8010

The HTML routes (``src/web/routes/pages.py``) are included when present; the
JSON API lives under ``/api`` (``src/web/routes/api.py``). Manage-layer errors
(``src/eval/manage.py``) are mapped to HTTP statuses here so routes stay thin.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.eval import manage as M
from src.eval.manage import (
    ConflictError,
    HarborReadOnlyError,
    ManageError,
    NotFoundError,
    ValidationError,
)

from .i18n import (
    DEFAULT,
    LABELS,
    LOCALES,
    criterion_for,
    label_for,
    resolve_locale,
    source_label,
    title_for_prompt,
    title_for_rubric,
    translate,
)
from .routes import api

_HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"


def _locale_context(request: Request) -> dict:
    """Per-request Jinja context: active locale + catalog + a bound translator.

    ``request.state.lang``/``request.state.t`` are set by the locale middleware
    below; this processor just exposes them (and a ``tr`` helper for flash
    key lookup with interpolation) to every template render.
    """
    lang = getattr(request.state, "lang", DEFAULT)
    t = getattr(request.state, "t", None) or LOCALES[DEFAULT]
    labels = LABELS.get(lang) or LABELS[DEFAULT]
    return {
        "lang": lang,
        "t": t,
        # Pre-serialized for the window.__LOCALE__ bootstrap in base.html,
        # so we don't depend on a tojson filter being registered.
        "t_json": json.dumps(t, ensure_ascii=False),
        "tr": lambda key, **fmt: translate(t, key, **fmt),
        # Data-label localization (see spec `data-label-i18n`): the active
        # locale's label catalog + resolvers bound to this locale, so every
        # template can call label_for/title_for_* without threading lang through.
        # labels_json bootstraps window.__LABELS__ for app.js (matrix meta, etc.).
        "labels": labels,
        "labels_json": json.dumps(labels, ensure_ascii=False),
        "label_for": lambda kind, value: label_for(kind, value, lang),
        "title_for_prompt": lambda name: title_for_prompt(name, lang),
        "title_for_rubric": lambda name: title_for_rubric(name, lang),
        "source_label": lambda source: source_label(source, lang),
        "criterion_for": lambda name, field, fallback="": criterion_for(name, field, lang, fallback),
    }


# Jinja2 templates (lazily loaded at render time; dir created below). The
# context processor injects lang/t/tr into every render so individual handlers
# do not need to thread them through their context dicts.
templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[_locale_context],
)


# ManageError subclass -> HTTP status.
_ERR_STATUS = [
    (NotFoundError, 404),
    (HarborReadOnlyError, 403),
    (ConflictError, 409),
    (ValidationError, 400),
]


def _make_handler(status: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": str(exc)})

    return handler


def create_app() -> FastAPI:
    app = FastAPI(title="Evaluation Rules Manager", docs_url="/api/docs")

    # Ensure the asset dirs exist so the mounts/templating work on first run.
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(api.router)

    # Resolve the active locale once per request, stash it for the template
    # context processor, and persist the choice as a cookie so it sticks.
    @app.middleware("http")
    async def _locale_middleware(request: Request, call_next):
        lang, t = resolve_locale(request)
        request.state.lang = lang
        request.state.t = t
        response = await call_next(request)
        # Refresh the cookie on every response so the resolved locale persists
        # (covers both explicit switches and first-visit defaulting to zh).
        response.set_cookie("lang", lang, samesite="lax", max_age=60 * 60 * 24 * 365)
        return response

    # Optional HTML routes (added by routes/pages.py in the UI build step).
    try:
        from .routes import pages  # noqa: WPS433 (intentional lazy import)
        app.include_router(pages.router)
        from .routes import law_info  # noqa: WPS433 (intentional lazy import)
        app.include_router(law_info.router)
        from .routes import search  # noqa: WPS433 (intentional lazy import)
        app.include_router(search.router)
    except ImportError:
        pass

    # Map manage-layer errors to HTTP statuses.
    for exc_cls, status in _ERR_STATUS:
        app.add_exception_handler(exc_cls, _make_handler(status))

    @app.exception_handler(ManageError)
    async def _fallback(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        """Liveness/readiness probe target: always 200 when the process is up."""
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
