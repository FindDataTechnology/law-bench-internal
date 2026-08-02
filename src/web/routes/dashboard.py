"""Pipeline evaluation dashboard: pass-rate stats, per-type breakdown, trends."""

from __future__ import annotations

from fastapi import APIRouter, Request
from src.eval.db import connect
from src.eval.store import ensure_schema

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", include_in_schema=False)
def dashboard(request: Request):
    """Server-rendered dashboard page with pipeline evaluation stats."""
    from ..app import templates as _templates

    ensure_schema()
    conn = connect()
    try:
        # Overall stats
        overall = conn.execute("""
            SELECT
                COUNT(*) AS total_runs,
                COUNT(*) FILTER (WHERE all_pass = 1) AS all_pass_count,
                COALESCE(AVG(n_passed::float / NULLIF(n_criteria, 0)), 0) AS avg_pass_rate,
                COUNT(DISTINCT contract_type) AS distinct_types
            FROM pipeline_runs
        """).fetchone()

        # Per-type breakdown (best run per type)
        by_type = conn.execute("""
            SELECT DISTINCT ON (contract_type)
                contract_type,
                rubric_name,
                n_passed,
                n_criteria,
                all_pass,
                iteration,
                score,
                ROUND((n_passed::float / NULLIF(n_criteria, 0)) * 100, 1) AS pass_pct,
                created_at
            FROM pipeline_runs
            ORDER BY contract_type, (n_passed::float / NULLIF(n_criteria, 0)) DESC, id DESC
        """).fetchall()

        # v2 vs v3 comparison
        version_comparison = conn.execute("""
            SELECT
                CASE
                    WHEN rubric_name LIKE '%_v3' THEN 'v3'
                    WHEN rubric_name LIKE '%_v2' THEN 'v2'
                    WHEN rubric_name LIKE '%_v1' THEN 'v1'
                    ELSE 'other'
                END AS rubric_version,
                COUNT(*) AS run_count,
                COALESCE(AVG(n_passed::float / NULLIF(n_criteria, 0)), 0) AS avg_pass_rate,
                COUNT(*) FILTER (WHERE all_pass = 1) AS all_pass_count
            FROM pipeline_runs
            GROUP BY rubric_version
            ORDER BY rubric_version
        """).fetchall()

        # Recent 10 runs
        recent = conn.execute("""
            SELECT id, contract_type, rubric_name, n_passed, n_criteria, all_pass,
                   iteration, created_at
            FROM pipeline_runs
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    finally:
        conn.close()

    return _templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "overall": overall,
            "by_type": by_type,
            "version_comparison": version_comparison,
            "recent": recent,
            "total_types": len(by_type),
        },
    )


@router.get("/api/dashboard/stats", include_in_schema=False)
def dashboard_stats():
    """JSON API for dashboard stats (for programmatic access)."""
    ensure_schema()
    conn = connect()
    try:
        overall = conn.execute("""
            SELECT
                COUNT(*) AS total_runs,
                COUNT(*) FILTER (WHERE all_pass = 1) AS all_pass_count,
                COALESCE(AVG(n_passed::float / NULLIF(n_criteria, 0)), 0) AS avg_pass_rate,
                COUNT(DISTINCT contract_type) AS distinct_types
            FROM pipeline_runs
        """).fetchone()

        by_type = conn.execute("""
            SELECT DISTINCT ON (contract_type)
                contract_type,
                n_passed,
                n_criteria,
                all_pass,
                ROUND((n_passed::float / NULLIF(n_criteria, 0)) * 100, 1) AS pass_pct
            FROM pipeline_runs
            ORDER BY contract_type, (n_passed::float / NULLIF(n_criteria, 0)) DESC
        """).fetchall()

        return {
            "overall": dict(overall) if overall else {},
            "by_type": [dict(r) for r in by_type],
            "total_types": len(by_type),
        }
    finally:
        conn.close()
