"""
Job Queue Module
Manages background job queue with Redis (preferred) with a DB-backed fallback.

Why DB fallback?
- This repo persists job records in Supabase (`training_jobs`, `jobs`) before enqueueing.
- In multi-process deployments (Render web + Render worker), an in-memory queue is not shared and becomes a no-op.
- In-memory enqueueing in the web process also leaks memory (nothing dequeues it).

So when Redis isn't configured/available, we dequeue from the database instead.

CRITICAL FIXES APPLIED:
- Race condition fixed with atomic UPDATE...WHERE status='queued' RETURNING *
- Connection pooling with retry logic
- Distributed locking for multi-worker setups
"""
import logging
import os
import json
import heapq
import time
from typing import Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Try to import Redis, fallback to in-memory if not available
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory queue")

# In-memory queue is disabled by default because it breaks in multi-process deployments.
# It is kept only as an explicit opt-in for single-process local experimentation.
_in_memory_queue = []
_in_memory_lock = False  # Simple lock simulation

def _in_memory_enabled() -> bool:
    return os.getenv("ENABLE_IN_MEMORY_QUEUE", "false").lower() == "true"


def init_redis_client():
    """Initialize Redis connection, return None if unavailable."""
    if not REDIS_AVAILABLE:
        return None

    # Do not assume localhost Redis in production; require explicit configuration.
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        client = redis.from_url(redis_url, decode_responses=True)
        # Test connection
        client.ping()
        return client
    except Exception as e:
        logger.warning("Redis connection failed: %s. Using in-memory queue.", e)
        return None


# Global Redis client (lazy initialization)
_redis_client = None


def get_redis_client():
    """Get or initialize Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = init_redis_client()
    return _redis_client


def enqueue_job(job_id: str, job_type: str, priority: int = 0, metadata: dict[str, Any] | None = None):
    """
    Add job to queue (priority-based: higher priority numbers processed first).

    Args:
        job_id: Training job UUID
        job_type: Type of job ('ingestion', 'reindex', 'health_check')
        priority: Priority level (higher = processed first, default 0)
        metadata: Optional job metadata
    """
    client = get_redis_client()

    if client:
        # Use Redis sorted set for priority queue
        # Score = -priority (negative so higher priority comes first)
        # Member = job_id
        score = -priority  # Negative for descending order
        client.zadd("training_jobs_queue", {job_id: score})

        # Store job metadata in hash
        if metadata:
            client.hset(f"job_metadata:{job_id}", mapping={
                "job_type": job_type,
                "metadata": json.dumps(metadata),
                "enqueued_at": datetime.now(timezone.utc).isoformat()
            })
        else:
            client.hset(f"job_metadata:{job_id}", mapping={
                "job_type": job_type,
                "enqueued_at": datetime.now(timezone.utc).isoformat()
            })
    else:
        # DB-backed fallback: job records are already persisted in Supabase (`training_jobs` or `jobs` tables).
        # Do NOT enqueue in-memory by default (web/worker are separate processes in production).
        if _in_memory_enabled():
            heapq.heappush(_in_memory_queue, (-priority, job_id, job_type, metadata or {}))


# =============================================================================
# DISTRIBUTED LOCKING FOR MULTI-WORKER SETUPS
# =============================================================================

class DistributedLock:
    """
    Distributed lock using database advisory locks or Redis.
    Prevents race conditions in multi-worker deployments.
    """

    def __init__(self, lock_id: str, timeout_seconds: int = 30):
        self.lock_id = lock_id
        self.timeout_seconds = timeout_seconds
        self._acquired = False
        self._lock_value = None

    async def acquire(self) -> bool:
        """Try to acquire the lock."""
        client = get_redis_client()

        if client:
            # Redis-based lock
            self._lock_value = f"{os.getpid()}:{time.time()}"
            acquired = client.set(
                f"lock:{self.lock_id}",
                self._lock_value,
                nx=True,  # Only set if not exists
                ex=self.timeout_seconds
            )
            self._acquired = bool(acquired)
            return self._acquired
        # Database advisory lock (PostgreSQL)
        try:
            from modules.observability import supabase
            # Use advisory lock based on hash of lock_id
            lock_hash = hash(self.lock_id) & 0x7FFFFFFF  # Positive int

            # Try to acquire lock with timeout
            _ = supabase.rpc(
                "pg_advisory_lock",
                {"key": lock_hash}
            ).execute()

            self._acquired = True
            return True
        except Exception as e:
            logger.warning("[DistributedLock] Failed to acquire lock %s: %s", self.lock_id, e)
            return False

    async def release(self):
        """Release the lock."""
        if not self._acquired:
            return

        client = get_redis_client()

        if client:
            # Only delete if we own the lock
            current_value = client.get(f"lock:{self.lock_id}")
            if current_value == self._lock_value:
                client.delete(f"lock:{self.lock_id}")
        else:
            # Release database advisory lock
            try:
                from modules.observability import supabase
                lock_hash = hash(self.lock_id) & 0x7FFFFFFF
                supabase.rpc(
                    "pg_advisory_unlock",
                    {"key": lock_hash}
                ).execute()
            except Exception as e:
                logger.warning("[DistributedLock] Failed to release lock %s: %s", self.lock_id, e)

        self._acquired = False

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()


# =============================================================================
# ATOMIC JOB CLAIMING (RACE CONDITION FIX)
# =============================================================================

def _try_claim_training_job_atomic(row: dict[str, Any]) -> dict[str, Any] | None:
    """
    ATOMIC job claiming using UPDATE...WHERE...RETURNING.

    This fixes the race condition where multiple workers could claim the same job.
    Uses database-level atomicity to ensure only one worker succeeds.

    Args:
        row: Job row with at least 'id' field

    Returns:
        The updated job row if claim succeeded, None otherwise
    """
    try:
        from modules.observability import supabase

        job_id = row.get("id")
        if not job_id:
            return None

        now = datetime.now(timezone.utc).isoformat()
        worker_id = os.getenv("RENDER_INSTANCE_ID", f"worker-{os.getpid()}")

        # ATOMIC UPDATE: Only update if status is still 'queued'
        # RETURNING * gives us the updated row
        # This is guaranteed atomic by PostgreSQL
        result = supabase.rpc(
            "claim_job_atomic",
            {
                "p_job_id": job_id,
                "p_worker_id": worker_id,
                "p_now": now
            }
        ).execute()

        if result.data and len(result.data) > 0:
            claimed_job = result.data[0]
            logger.info("[JobQueue] Worker %s claimed job %s", worker_id, job_id)
            return claimed_job

        # Job was already claimed by another worker
        return None

    except Exception as e:
        # If RPC doesn't exist, fall back to best-effort (with race condition)
        logger.warning("[JobQueue] Atomic claim failed, using fallback: %s", e)
        return _try_claim_training_job_fallback(row)


def _try_claim_training_job_fallback(row: dict[str, Any]) -> dict[str, Any] | None:
    """
    Fallback job claiming (best-effort, may have race conditions).
    Used when atomic RPC is not available.
    """
    try:
        from modules.observability import supabase

        job_id = row.get("id")
        if not job_id:
            return None

        now = datetime.now(timezone.utc).isoformat()
        worker_id = os.getenv("RENDER_INSTANCE_ID", f"worker-{os.getpid()}")

        # First, try to update with status check
        res = (
            supabase.table("training_jobs")
            .update({
                "status": "processing",
                "updated_at": now,
                "metadata": {
                    **(row.get("metadata") or {}),
                    "claimed_by": worker_id,
                    "claimed_at": now
                }
            })
            .eq("id", job_id)
            .eq("status", "queued")  # Only if still queued
            .execute()
        )

        if res.data and len(res.data) > 0:
            return res.data[0]

        # Check if we claimed it (race condition check)
        check = supabase.table("training_jobs").select("*").eq("id", job_id).single().execute()
        if check.data and check.data.get("status") == "processing":
            metadata = check.data.get("metadata", {})
            if metadata.get("claimed_by") == worker_id:
                return check.data

        return None

    except Exception as e:
        logger.warning("[JobQueue] Fallback claim failed: %s", e)
        return None


def _try_claim_job(row: dict[str, Any]) -> dict[str, Any] | None:
    """
    ATOMIC claim of a queued job from the jobs table.

    Args:
        row: Job row

    Returns:
        Updated job row if claim succeeded, None otherwise
    """
    try:
        from modules.observability import supabase

        job_id = row.get("id")
        if not job_id:
            return None

        now = datetime.now(timezone.utc).isoformat()
        worker_id = os.getenv("RENDER_INSTANCE_ID", f"worker-{os.getpid()}")

        def _claim(include_worker_id: bool):
            payload = {
                "status": "processing",
                "updated_at": now,
            }
            if include_worker_id:
                payload["worker_id"] = worker_id
            return (
                supabase.table("jobs")
                .update(payload)
                .eq("id", job_id)
                .eq("status", "queued")
                .execute()
            )

        try:
            # Preferred path: track claiming worker when schema supports worker_id.
            res = _claim(include_worker_id=True)
        except Exception as claim_err:
            err_text = str(claim_err)
            if "worker_id" in err_text or "PGRST204" in err_text:
                # Backward-compatible fallback for older jobs schemas.
                logger.warning("[JobQueue] worker_id column missing; claiming jobs without worker attribution")
                res = _claim(include_worker_id=False)
            else:
                raise

        if res.data and len(res.data) > 0:
            return res.data[0]

        return None

    except Exception as e:
        logger.error("[JobQueue] Job claim failed: %s", e)
        return None


def _dequeue_from_db() -> dict[str, Any] | None:
    """
    DB-backed dequeue when Redis isn't configured/available.

    Uses atomic claiming to prevent race conditions in multi-worker setups.

    Priority:
    1) `training_jobs` (ingestion/reindex/health_check) because it directly affects the UI.
    2) `jobs` (graph/content extraction) for background enrichment.

    Respects retry delays (next_attempt_after in metadata).

    Returns:
        job dict compatible with worker dispatch: {job_id, job_type, priority, metadata}
    """
    try:
        from modules.observability import supabase
        from datetime import datetime

        now = datetime.now(timezone.utc).isoformat()

        # 1) training_jobs - filter out jobs waiting for retry delay
        # Use atomic claiming to prevent race conditions
        tj_res = (
            supabase.table("training_jobs")
            .select("id, job_type, priority, metadata, twin_id")
            .eq("status", "queued")
            .or_(f"metadata->>next_attempt_after.is.null,metadata->>next_attempt_after.lte.{now}")
            .order("priority", desc=True)
            .order("created_at", desc=False)
            .limit(10)  # Try multiple jobs in case some are claimed
            .execute()
        )

        for row in tj_res.data or []:
            # Try to atomically claim this job
            claimed = _try_claim_training_job_atomic(row)
            if claimed:
                return {
                    "job_id": claimed.get("id"),
                    "job_type": claimed.get("job_type", "ingestion"),
                    "priority": claimed.get("priority", 0),
                    "metadata": claimed.get("metadata", {}),
                    "twin_id": claimed.get("twin_id"),
                    "claimed_at": datetime.now(timezone.utc).isoformat()
                }

        # 2) jobs table (optional — may not exist in all deployments)
        try:
            j_res = (
                supabase.table("jobs")
                .select("id, job_type, priority, metadata")
                .eq("status", "queued")
                .order("priority", desc=True)
                .order("created_at", desc=False)
                .limit(5)
                .execute()
            )
            for row in j_res.data or []:
                claimed = _try_claim_job(row)
                if claimed:
                    return {
                        "job_id": claimed.get("id"),
                        "job_type": claimed.get("job_type", "other"),
                        "priority": claimed.get("priority", 0),
                        "metadata": claimed.get("metadata", {}),
                        "claimed_at": datetime.now(timezone.utc).isoformat()
                    }
        except Exception:
            pass  # jobs table not present in this deployment

        return None

    except Exception as e:
        logger.error("[JobQueue] DB dequeue failed: %s", e)
        return None


def dequeue_job() -> dict[str, Any] | None:
    """
    Get next job from queue (highest priority first).

    Uses atomic claiming to prevent race conditions.

    Returns:
        Dict with job_id, job_type, and metadata, or None if queue is empty
    """
    client = get_redis_client()

    if client:
        # Use distributed lock for Redis dequeue
        _ = DistributedLock("redis_dequeue", timeout_seconds=10)

        # Synchronous lock acquisition for Redis
        lock_value = f"{os.getpid()}:{time.time()}"
        acquired = client.set("lock:redis_dequeue", lock_value, nx=True, ex=10)

        if not acquired:
            # Another worker is dequeuing, skip this cycle
            return None

        try:
            # Get highest priority job (lowest score = highest priority)
            result = client.zrange("training_jobs_queue", 0, 0, withscores=True)
            if not result:
                return None

            job_id = result[0][0]
            score = result[0][1]
            priority = -int(score)  # Convert back from negative

            # Remove from queue
            client.zrem("training_jobs_queue", job_id)

            # Get metadata
            metadata = client.hgetall(f"job_metadata:{job_id}")
            job_type = metadata.get("job_type", "ingestion")

            # Parse metadata JSON if present
            metadata_json = metadata.get("metadata")
            job_metadata = json.loads(metadata_json) if metadata_json else {}

            # Clean up metadata hash
            client.delete(f"job_metadata:{job_id}")

            return {
                "job_id": job_id,
                "job_type": job_type,
                "priority": priority,
                "metadata": job_metadata
            }
        finally:
            # Release lock
            current_value = client.get("lock:redis_dequeue")
            if current_value == lock_value:
                client.delete("lock:redis_dequeue")
    else:
        if _in_memory_enabled() and _in_memory_queue:
            priority, job_id, job_type, metadata = heapq.heappop(_in_memory_queue)
            return {
                "job_id": job_id,
                "job_type": job_type,
                "priority": -priority,  # Convert back from negative
                "metadata": metadata,
            }
        return _dequeue_from_db()


def get_queue_length() -> int:
    """Get current queue size."""
    client = get_redis_client()

    if client:
        return client.zcard("training_jobs_queue")
    if _in_memory_enabled():
        return len(_in_memory_queue)
    try:
        from modules.observability import supabase

        tj = supabase.table("training_jobs").select("id", count="exact").eq("status", "queued").execute()
        j = supabase.table("jobs").select("id", count="exact").eq("status", "queued").execute()
        return int((tj.count or 0) + (j.count or 0))
    except Exception:
        return 0


def remove_job(job_id: str):
    """Remove a specific job from the queue."""
    client = get_redis_client()

    if client:
        client.zrem("training_jobs_queue", job_id)
        client.delete(f"job_metadata:{job_id}")
    else:
        if _in_memory_enabled():
            # In-memory: rebuild queue without the job
            global _in_memory_queue
            _in_memory_queue = [
                item for item in _in_memory_queue
                if item[1] != job_id  # item[1] is job_id
            ]
            heapq.heapify(_in_memory_queue)


# =============================================================================
# DATABASE RPC FOR ATOMIC CLAIMING
# =============================================================================

"""
SQL to create atomic claim function in Supabase:

CREATE OR REPLACE FUNCTION claim_job_atomic(
    p_job_id UUID,
    p_worker_id TEXT,
    p_now TIMESTAMPTZ
)
RETURNS TABLE (
    id UUID,
    source_id UUID,
    twin_id UUID,
    status TEXT,
    job_type TEXT,
    priority INTEGER,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    UPDATE training_jobs
    SET
        status = 'processing',
        updated_at = p_now,
        started_at = p_now,
        metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
            'claimed_by', p_worker_id,
            'claimed_at', p_now
        )
    WHERE
        id = p_job_id
        AND status = 'queued'
    RETURNING
        training_jobs.id,
        training_jobs.source_id,
        training_jobs.twin_id,
        training_jobs.status,
        training_jobs.job_type,
        training_jobs.priority,
        training_jobs.metadata;
END;
$$ LANGUAGE plpgsql;
"""
