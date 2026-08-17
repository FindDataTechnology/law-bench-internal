"""Jinja2 templates singleton + per-request locale context processor.

Extracted from ``src/web/app.py`` so the HTML route modules can import the
``templates`` renderer without triggering a circular import (routes are now
included at ``app.py`` top level rather than lazily inside ``create_app()``).
The context processor injects the active locale + catalog + bound translators
into every render, so individual handlers do not thread them through.
"""

from __future__ import annotations

import json

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .i18n import (
    DEFAULT,
    LABELS,
    LOCALES,
    criterion_for,
    label_for,
    source_label,
    title_for_prompt,
    title_for_rubric,
    translate,
)
from .paths import TEMPLATES_DIR


def _locale_context(request: Request) -> dict:
    """Per-request Jinja context: active locale + catalog + a bound translator.

    ``request.state.lang``/``request.state.t`` are set by the locale middleware
    in ``app.create_app()``; this processor just exposes them (and a ``tr``
    helper for flash key lookup with interpolation) to every template render.
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


# Jinja2 templates (lazily loaded at render time; dir created by create_app()).
templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR),
    context_processors=[_locale_context],
)
