# syntax=docker/dockerfile:1
#
# Evaluation Rules Manager (FastAPI web app) image.
# Serves `src.web.app:app` on 0.0.0.0:8010.
#
# The SQLite DB ships at /app/db/evaluation_rules.db as seed data (rubrics,
# criteria, prompts). Mount a named volume at /app/db to persist eval runs and
# rubric edits across restarts — Docker copies the seeded file into the volume
# on first use.
#
#   docker build -t law-template .
#   docker run --rm -p 8010:8010 law-template
#
# With persistence + LLM creds (needed only for drafting / evaluation, not for
# browsing rubrics):
#   docker run --rm -p 8010:8010 -v law-bench-db:/app/db \
#     -e OPENAI_API_KEY=... -e OPENAI_API_BASE=... \
#     -e INTAKE_MODEL=... -e DRAFTER_MODEL=... -e AUDITOR_MODEL=... law-template

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app

# Headless LibreOffice for DOCX -> PDF conversion (src.docs.converter). Only
# the writer module is needed; it pulls in `soffice` via libreoffice-core.
# fonts-noto-cjk: the DOCX declares 宋体/黑体 (SimSun/SimHei, proprietary, not
# in Debian); LibreOffice substitutes them with Noto CJK for PDF rendering, but
# only if a CJK font is installed. Without this, Chinese PDFs render as boxes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (cacheable layer). --no-install-project avoids
# needing a [build-system]: only the locked third-party deps are installed.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Application sources + seed data.
COPY src ./src
COPY main.py ./
COPY templates ./templates
COPY db ./db
COPY scripts ./scripts

# Run the server as a non-root user.
RUN useradd --create-home --uid 1001 appuser \
    && chmod +x scripts/docker-entrypoint.sh \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8010

# Self-heal harbor rubrics from the bundled seed on every boot (harbor isn't
# installed in the image), then serve. See scripts/docker-entrypoint.sh.
CMD ["./scripts/docker-entrypoint.sh"]
