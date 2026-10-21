"""
Content Health Checks Module
Validates content quality before indexing to prevent low-quality data from corrupting the brain.
"""
import hashlib
import logging
from typing import Any
from modules.observability import supabase

logger = logging.getLogger(__name__)


def calculate_content_hash(text: str) -> str:
    """Calculate SHA256 hash of content for duplicate detection."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def check_empty_extraction(source_id: str, extracted_text: str, threshold: int = 100) -> dict[str, Any]:
    """
    Validates that extracted text length exceeds threshold.

    Args:
        source_id: Source UUID
        extracted_text: Extracted text content
        threshold: Minimum text length (default 100)

    Returns:
        Dict with status, message, and metadata
    """
    text_length = len(extracted_text.strip()) if extracted_text else 0
    status = 'pass' if text_length >= threshold else 'fail'
    message = (
        f"Text extraction {'passed' if status == 'pass' else 'failed'}: "
        f"{text_length} characters (threshold: {threshold})"
    )

    return {
        'check_type': 'empty_extraction',
        'status': status,
        'message': message,
        'metadata': {
            'text_length': text_length,
            'threshold': threshold
        }
    }


def check_duplicate_content(source_id: str, twin_id: str, content_hash: str) -> dict[str, Any]:
    """
    Detects duplicate content via hash comparison.

    Args:
        source_id: Current source UUID
        twin_id: Twin UUID
        content_hash: SHA256 hash of content

    Returns:
        Dict with status, message, and metadata
    """
    if not content_hash:
        return {
            'check_type': 'duplicate',
            'status': 'warning',
            'message': 'Content hash not provided, cannot check for duplicates',
            'metadata': {}
        }

    # Check for existing sources with same hash
    existing = supabase.table("sources").select("id, filename, created_at").eq(
        "twin_id", twin_id
    ).eq("content_hash", content_hash).neq("id", source_id).execute()

    if existing.data and len(existing.data) > 0:
        duplicate_ids = [s['id'] for s in existing.data]
        duplicate_filenames = [s['filename'] for s in existing.data]
        return {
            'check_type': 'duplicate',
            'status': 'fail',
            'message': f"Duplicate content detected: {len(existing.data)} existing source(s) with same content hash",
            'metadata': {
                'duplicate_source_ids': duplicate_ids,
                'duplicate_filenames': duplicate_filenames
            }
        }

    return {
        'check_type': 'duplicate',
        'status': 'pass',
        'message': 'No duplicate content detected',
        'metadata': {}
    }


def check_chunk_anomalies(source_id: str, chunk_count: int, expected_range: tuple = (1, 10000)) -> dict[str, Any]:
    """
    Validates chunk count is within expected range.

    Args:
        source_id: Source UUID
        chunk_count: Number of chunks created
        expected_range: Tuple of (min, max) expected chunks (default: 1-10000)

    Returns:
        Dict with status, message, and metadata
    """
    min_chunks, max_chunks = expected_range

    if chunk_count == 0:
        status = 'fail'
        message = "No chunks created from source"
    elif chunk_count < min_chunks:
        status = 'warning'
        message = f"Low chunk count: {chunk_count} (expected at least {min_chunks})"
    elif chunk_count > max_chunks:
        status = 'warning'
        message = f"High chunk count: {chunk_count} (expected at most {max_chunks})"
    else:
        status = 'pass'
        message = f"Chunk count within expected range: {chunk_count}"

    return {
        'check_type': 'chunk_anomaly',
        'status': status,
        'message': message,
        'metadata': {
            'chunk_count': chunk_count,
            'expected_min': min_chunks,
            'expected_max': max_chunks
        }
    }


def check_missing_metadata(source_id: str, source_data: dict[str, Any]) -> dict[str, Any]:
    """
    Validates required metadata fields are present.

    Args:
        source_id: Source UUID
        source_data: Source record data

    Returns:
        Dict with status, message, and metadata
    """
    required_fields = ['filename', 'twin_id']
    missing_fields = [field for field in required_fields if not source_data.get(field)]

    if missing_fields:
        return {
            'check_type': 'missing_metadata',
            'status': 'fail',
            'message': f"Missing required metadata fields: {', '.join(missing_fields)}",
            'metadata': {
                'missing_fields': missing_fields
            }
        }

    return {
        'check_type': 'missing_metadata',
        'status': 'pass',
        'message': 'All required metadata fields present',
        'metadata': {}
    }


def run_all_health_checks(source_id: str, twin_id: str, extracted_text: str,
                          chunk_count: int | None = None,
                          source_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Runs all health checks and records results in content_health_checks table.

    Args:
        source_id: Source UUID
        twin_id: Twin UUID
        extracted_text: Extracted text content
        chunk_count: Number of chunks (optional, for chunk_anomaly check)
        source_data: Source record data (optional, for metadata check)

    Returns:
        Dict with overall status and individual check results
    """
    results = []

    # 1. Empty extraction check
    empty_check = check_empty_extraction(source_id, extracted_text)
    results.append(empty_check)
    _record_health_check(source_id, empty_check)

    # 2. Duplicate check (requires content hash)
    content_hash = calculate_content_hash(extracted_text) if extracted_text else None
    if content_hash:
        duplicate_check = check_duplicate_content(source_id, twin_id, content_hash)
        results.append(duplicate_check)
        _record_health_check(source_id, duplicate_check)

    # 3. Chunk anomaly check (if chunk_count provided)
    if chunk_count is not None:
        chunk_check = check_chunk_anomalies(source_id, chunk_count)
        results.append(chunk_check)
        _record_health_check(source_id, chunk_check)

    # 4. Missing metadata check (if source_data provided)
    if source_data:
        metadata_check = check_missing_metadata(source_id, source_data)
        results.append(metadata_check)
        _record_health_check(source_id, metadata_check)

    # Determine overall status
    has_fail = any(r['status'] == 'fail' for r in results)
    has_warning = any(r['status'] == 'warning' for r in results)

    overall_status = 'failed' if has_fail else ('needs_attention' if has_warning else 'healthy')

    return {
        'overall_status': overall_status,
        'checks': results,
        'content_hash': content_hash
    }


def _record_health_check(source_id: str, check_result: dict[str, Any]):
    """Record health check result in database."""
    try:
        supabase.table("content_health_checks").insert({
            "source_id": source_id,
            "check_type": check_result['check_type'],
            "status": check_result['status'],
            "message": check_result['message'],
            "metadata": check_result.get('metadata', {})
        }).execute()
    except Exception as e:
        logger.warning("Error recording health check: %s", e)


def get_source_health_status(source_id: str) -> dict[str, Any]:
    """
    Aggregates health check results into overall status.

    Args:
        source_id: Source UUID

    Returns:
        Dict with overall status and recent checks
    """
    try:
        # Get recent health checks
        checks_response = supabase.table("content_health_checks").select(
            "*"
        ).eq("source_id", source_id).order("created_at", desc=True).limit(20).execute()

        checks = checks_response.data if checks_response.data else []

        # Determine overall status from checks
        if not checks:
            overall_status = 'healthy'  # Default if no checks
        else:
            has_fail = any(c['status'] == 'fail' for c in checks)
            has_warning = any(c['status'] == 'warning' for c in checks)
            overall_status = 'failed' if has_fail else ('needs_attention' if has_warning else 'healthy')

        # Get source health_status
        source_response = supabase.table("sources").select("health_status").eq("id", source_id).single().execute()
        source_health = source_response.data.get('health_status', 'healthy') if source_response.data else 'healthy'

        return {
            'source_id': source_id,
            'overall_status': overall_status,
            'source_health_status': source_health,
            'checks': checks,
            'check_count': len(checks)
        }
    except Exception as e:
        logger.warning("Error getting health status: %s", e)
        return {
            'source_id': source_id,
            'overall_status': 'healthy',
            'source_health_status': 'healthy',
            'checks': [],
            'check_count': 0
        }

