"""
Jobs Service Module

Background job tracking for long-running operations like ingestion,
reindexing, and health checks.
"""

from typing import Any
from datetime import datetime, timezone
from pydantic import BaseModel
from enum import Enum
from modules.observability import supabase


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETE = "complete"
    FAILED = "failed"


class JobType(str, Enum):
    INGESTION = "ingestion"
    REINDEX = "reindex"
    HEALTH_CHECK = "health_check"
    GRAPH_EXTRACTION = "graph_extraction"
    CONTENT_EXTRACTION = "content_extraction"
    FEEDBACK_LEARNING = "feedback_learning"
    OTHER = "other"


class LogLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Job(BaseModel):
    id: str
    twin_id: str | None = None
    source_id: str | None = None
    status: JobStatus
    job_type: JobType
    priority: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobLog(BaseModel):
    id: str
    job_id: str
    log_level: LogLevel
    message: str
    metadata: dict[str, Any] = {}
    created_at: datetime


# ============================================================================
# Job Operations
# ============================================================================

def create_job(
    job_type: JobType,
    twin_id: str | None = None,
    source_id: str | None = None,
    priority: int = 0,
    metadata: dict[str, Any] = None
) -> Job:
    """Create a new job in queued status."""
    data = {
        "job_type": job_type.value,
        "status": JobStatus.QUEUED.value,
        "priority": priority,
        "metadata": metadata or {}
    }

    if twin_id:
        data["twin_id"] = twin_id
    if source_id:
        data["source_id"] = source_id

    result = supabase.table("jobs").insert(data).execute()

    if result.data:
        return Job(**result.data[0])
    raise Exception("Failed to create job")


def start_job(job_id: str) -> Job:
    """Mark a job as processing."""
    result = supabase.table("jobs").update({
        "status": JobStatus.PROCESSING.value,
        "started_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", job_id).execute()

    if result.data:
        return Job(**result.data[0])
    raise Exception(f"Job {job_id} not found")


def complete_job(job_id: str, metadata: dict[str, Any] = None) -> Job:
    """Mark a job as complete."""
    update_data = {
        "status": JobStatus.COMPLETE.value,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }

    if metadata:
        # Merge with existing metadata
        existing = supabase.table("jobs").select("metadata").eq("id", job_id).execute()
        if existing.data:
            existing_metadata = existing.data[0].get("metadata", {})
            update_data["metadata"] = {**existing_metadata, **metadata}

    result = supabase.table("jobs").update(update_data).eq("id", job_id).execute()

    if result.data:
        return Job(**result.data[0])
    raise Exception(f"Job {job_id} not found")


def fail_job(job_id: str, error_message: str) -> Job:
    """Mark a job as failed with an error message."""
    result = supabase.table("jobs").update({
        "status": JobStatus.FAILED.value,
        "error_message": error_message,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", job_id).execute()

    if result.data:
        return Job(**result.data[0])
    raise Exception(f"Job {job_id} not found")


def needs_attention(job_id: str, reason: str) -> Job:
    """Mark a job as needing attention."""
    result = supabase.table("jobs").update({
        "status": JobStatus.NEEDS_ATTENTION.value,
        "error_message": reason
    }).eq("id", job_id).execute()

    if result.data:
        return Job(**result.data[0])
    raise Exception(f"Job {job_id} not found")


def get_job(job_id: str) -> Job | None:
    """Get a job by ID."""
    result = supabase.table("jobs").select("*").eq("id", job_id).execute()

    if result.data:
        return Job(**result.data[0])
    return None


def list_jobs(
    twin_id: str | None = None,
    status: JobStatus | None = None,
    job_type: JobType | None = None,
    limit: int = 50,
    offset: int = 0
) -> list[Job]:
    """List jobs with optional filters."""
    query = supabase.table("jobs").select("*")

    if twin_id:
        query = query.eq("twin_id", twin_id)
    if status:
        query = query.eq("status", status.value)
    if job_type:
        query = query.eq("job_type", job_type.value)

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
    result = query.execute()

    return [Job(**row) for row in result.data] if result.data else []


# ============================================================================
# Log Operations
# ============================================================================

def append_log(
    job_id: str,
    message: str,
    log_level: LogLevel = LogLevel.INFO,
    metadata: dict[str, Any] = None
) -> JobLog:
    """Append a log entry to a job."""
    data = {
        "job_id": job_id,
        "log_level": log_level.value,
        "message": message,
        "metadata": metadata or {}
    }

    result = supabase.table("job_logs").insert(data).execute()

    if result.data:
        return JobLog(**result.data[0])
    raise Exception("Failed to create log entry")


def list_job_logs(
    job_id: str,
    log_level: LogLevel | None = None,
    limit: int = 100
) -> list[JobLog]:
    """List logs for a job, newest first."""
    query = supabase.table("job_logs").select("*").eq("job_id", job_id)

    if log_level:
        query = query.eq("log_level", log_level.value)

    query = query.order("created_at", desc=True).limit(limit)
    result = query.execute()

    return [JobLog(**row) for row in result.data] if result.data else []
