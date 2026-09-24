"""Durable ADK artifacts in a private per-deployment Cloud Storage bucket."""
from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def create_artifact_service():
    from google.adk.artifacts import GcsArtifactService

    bucket = os.environ.get("CYMBAL_ARTIFACT_BUCKET", "").strip()
    if not bucket or "/" in bucket:
        raise ValueError("Set CYMBAL_ARTIFACT_BUCKET to this deployment's private artifact bucket name.")
    return GcsArtifactService(bucket_name=bucket)
