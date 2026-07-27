#!/usr/bin/env python3
"""Upload contract templates and generated drafts into MinIO (S3-compatible).

Pushes ``templates/*.md`` -> ``<bucket>/templates/`` and ``output/*.md`` ->
``<bucket>/drafts/`` so the RAG ingestion pipeline has a corpus to read. Creates
the bucket if it does not exist. Idempotent (S3 PUT overwrites).

Run:
    uv run python scripts/seed_minio.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3

# botocore honors the macOS system proxy (which 502s against MinIO); bypass it.
os.environ.setdefault("NO_PROXY", "*")

from src.settings import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_DRAFTS_PREFIX,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    MINIO_TEMPLATES_PREFIX,
    REPO_ROOT,
    TEMPLATES_DIR,
)


def _client():
    scheme = "https" if MINIO_SECURE else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=boto3.session.Config(signature_version="s3v4", s3={"addressing_style": "path"}, proxies={}),
        verify=False,
    )


def _upload_dir(client, directory: Path, prefix: str) -> int:
    n = 0
    for f in sorted(directory.glob("*.md")):
        key = f"{prefix}{f.name}"
        client.put_object(
            Bucket=MINIO_BUCKET, Key=key, Body=f.read_bytes(), ContentType="text/markdown"
        )
        print(f"  uploaded {key}")
        n += 1
    return n


def main() -> int:
    client = _client()
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except Exception:
        client.create_bucket(Bucket=MINIO_BUCKET)
        print(f"created bucket {MINIO_BUCKET}")

    n1 = _upload_dir(client, TEMPLATES_DIR, MINIO_TEMPLATES_PREFIX)
    n2 = _upload_dir(client, REPO_ROOT / "output", MINIO_DRAFTS_PREFIX)
    print(f"Uploaded {n1} templates + {n2} drafts to bucket {MINIO_BUCKET!r}.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
