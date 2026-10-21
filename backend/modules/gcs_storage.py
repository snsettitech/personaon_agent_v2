"""GCS storage helpers for PersonaOn file uploads.

Uses Application Default Credentials — no key file required.
On Cloud Run, ADC resolves to the attached service account automatically.
Locally, run: gcloud auth application-default login
"""
from __future__ import annotations

import datetime
import logging
import os

logger = logging.getLogger(__name__)

GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "personaon-uploads")

_gcs_client = None


def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        from google.cloud import storage
        _gcs_client = storage.Client()
    return _gcs_client


def upload_file_bytes(
    *,
    file_bytes: bytes,
    tenant_id: str,
    twin_id: str,
    source_id: str,
    filename: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload raw bytes to GCS. Returns gs:// URI. Raises on failure."""
    client = _get_gcs_client()
    blob_path = f"{tenant_id}/{twin_id}/{source_id}/{filename}"
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(file_bytes, content_type=content_type)
    uri = f"gs://{GCS_BUCKET_NAME}/{blob_path}"
    logger.info("[GCS] uploaded %d bytes to %s", len(file_bytes), uri)
    return uri


def generate_signed_url(
    gcs_uri: str,
    expiration_seconds: int = 3600,
) -> str:
    """Generate a V4 signed GET URL from a gs:// URI (expires in 1h by default).

    Requires roles/iam.serviceAccountTokenCreator on the service account.
    """
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {gcs_uri!r}")
    without_scheme = gcs_uri[5:]
    bucket_name, blob_path = without_scheme.split("/", 1)
    client = _get_gcs_client()
    blob = client.bucket(bucket_name).blob(blob_path)
    return blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=expiration_seconds),
        method="GET",
    )
