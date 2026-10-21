import argparse
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

# Configure root logger before any module imports so all loggers inherit it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def validate_worker_environment():
    """
    Validate critical environment variables at startup.
    Fail fast if required variables are missing.
    """
    required_vars = [
        ("SUPABASE_URL", "Database connection"),
        ("PGVECTOR_DATABASE_URL", "pgvector database connection"),
    ]

    optional_vars = [
        ("REDIS_URL", "Redis queue (falls back to DB polling if missing)"),
        ("DATABASE_URL", "LangGraph checkpointer (optional)"),
    ]

    missing = []
    for var, description in required_vars:
        value = os.getenv(var)
        if not value:
            missing.append(f"  - {var}: {description}")

    # Accept either Supabase key variable for compatibility with API service config.
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not supabase_key:
        missing.append("  - SUPABASE_SERVICE_KEY or SUPABASE_KEY: Database authentication")

    # Provider-aware key requirements (Phase 4 hybrid inference support).
    openai_key = os.getenv("OPENAI_API_KEY")
    cerebras_key = os.getenv("CEREBRAS_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    hf_api_token = os.getenv("HF_API_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
    hf_embedding_backend = os.getenv("HF_EMBEDDING_BACKEND", "auto").lower()
    inference_provider = os.getenv("INFERENCE_PROVIDER", "openai").lower()
    asr_provider = os.getenv("YOUTUBE_ASR_PROVIDER", "openai").lower()

    # Require at least one model provider key for LLM operations.
    google_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not any([openai_key, cerebras_key, anthropic_key, google_key]):
        missing.append("  - One of OPENAI_API_KEY/CEREBRAS_API_KEY/ANTHROPIC_API_KEY/GOOGLE_API_KEY is required")

    # Require OPENAI key when active providers explicitly depend on it.
    if embedding_provider == "openai" and not openai_key:
        missing.append("  - OPENAI_API_KEY required when EMBEDDING_PROVIDER=openai")
    if embedding_provider == "huggingface":
        if hf_embedding_backend in {"inference_api", "api", "inference"} and not hf_api_token:
            missing.append(
                "  - HF_API_TOKEN (or HUGGINGFACEHUB_API_TOKEN) required when "
                "EMBEDDING_PROVIDER=huggingface and HF_EMBEDDING_BACKEND=inference_api"
            )
        if hf_embedding_backend == "auto" and not hf_api_token:
            logger.warning(
                "[WARN] EMBEDDING_PROVIDER=huggingface with HF_EMBEDDING_BACKEND=auto "
                "and no HF_API_TOKEN; worker will try local embeddings."
            )
    if inference_provider == "openai" and not openai_key:
        missing.append("  - OPENAI_API_KEY required when INFERENCE_PROVIDER=openai")
    if asr_provider == "openai" and not openai_key:
        missing.append("  - OPENAI_API_KEY required when YOUTUBE_ASR_PROVIDER=openai")

    # pgvector column `chunks.embedding` is vector(768). The embedding
    # generator relies on EMBEDDING_TARGET_DIMENSION to pass the correct
    # output_dimensionality to Gemini (default is 3072 → DataError on INSERT
    # or SELECT against the 768 column). Commit 232b44e deleted the Pinecone
    # fallback; without this env var the worker produces the wrong
    # dimensionality silently. Fail fast instead of at first query.
    expected_dim = "768"
    configured_dim = os.getenv("EMBEDDING_TARGET_DIMENSION")
    if configured_dim != expected_dim:
        missing.append(
            f"  - EMBEDDING_TARGET_DIMENSION must equal '{expected_dim}' to match "
            f"the pgvector column width (chunks.embedding vector(768)). "
            f"Current value: {configured_dim!r}"
        )

    if missing:
        logger.error("=" * 70)
        logger.error("FATAL: Worker missing required environment variables:")
        for m in missing:
            logger.error("%s", m)
        logger.error("=" * 70)
        logger.error("Please set these variables in your worker environment.")
        logger.error("For Render: Check your Background Worker service environment variables.")
        logger.error("For local: Create a .env file with these variables.")
        sys.exit(1)

    # Warn about optional variables
    for var, description in optional_vars:
        if not os.getenv(var):
            logger.warning("[WARN] %s not set: %s", var, description)

    # Validate Supabase connection format
    supabase_url = os.getenv("SUPABASE_URL", "")
    if not supabase_url.startswith("https://"):
        logger.warning("[WARN] SUPABASE_URL should start with https://, got: %s...", supabase_url[:30])

    # Validate OpenAI key format when present
    if openai_key and not openai_key.startswith("sk-"):
        logger.warning("[WARN] OPENAI_API_KEY should start with 'sk-', check your key format")

    logger.info("[OK] Worker environment validation passed")
    return True


# Run validation before importing modules that depend on env vars
validate_worker_environment()

import contextlib

from modules._core.scribe_engine import (
    process_content_extraction_job,
    process_graph_extraction_job,
)
from modules.graph_outbox_worker import (
    process_next_graph_outbox_job,
    reset_zombie_jobs,
    sweep_stuck_recaps,
)
from modules.job_queue import dequeue_job, get_redis_client

# Graceful shutdown
shutdown_event = asyncio.Event()

# Ensure logs are flushed immediately
if sys.platform != "win32":
    # Windows doesn't support line_buffering param in reconfigure easily in all versions,
    # but strictly this is for Render (Linux)
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)


def handle_shutdown(sig, frame):
    logger.info("[Worker] Shutdown signal received. Finishing current job and stopping...")
    shutdown_event.set()


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


async def worker_loop(queue_mode: str = "all"):
    """
    Main worker loop that polls for jobs and executes them.

    queue_mode:
    - all: process graph_outbox + legacy jobs/training queues
    - default: process only legacy jobs/training queues
    - graph_memory: process only graph_outbox
    """
    worker_id = os.getenv("RENDER_INSTANCE_ID", "local-worker")
    logger.info("[Worker] Starting background worker (%s) queue_mode=%s", worker_id, queue_mode)

    # Initialize OTEL tracing — no-op when OTEL_EXPORTER_OTLP_ENDPOINT is
    # unset. Required here (not just in main.py / API service) because the
    # cron path that calls generate_brief runs in this process, and its
    # brief.generate / brief.persist spans would otherwise be dropped.
    try:
        from modules.telemetry import setup_telemetry
        setup_telemetry()
    except Exception as exc:
        logger.warning("[Worker] telemetry init failed: %s", exc)

    # Check Redis connection
    redis_client = get_redis_client()
    if redis_client:
        logger.info("[Worker] Connected to Redis queue")
    else:
        logger.info("[Worker] INFO: REDIS_URL not configured/available - using DB-backed queue polling")
        logger.info("[Worker] TIP: Configure REDIS_URL for lower latency and horizontal scaling")

    consecutive_empty_polls = 0
    jobs_processed = 0
    # Layer 2: run the zombie sweep periodically. Every 60 iterations
    # (~30s at the typical empty-poll cadence) we scan for jobs stuck in
    # 'processing' for >30 min and either re-queue or fail them. The sweep
    # is cheap (one SELECT, bounded LIMIT) and is the safety net for
    # crashed workers, OOM kills, or wedged DB connections inside a handler.
    zombie_sweep_counter = 0
    _ZOMBIE_SWEEP_INTERVAL = int(os.getenv("GRAPH_OUTBOX_ZOMBIE_SWEEP_INTERVAL", "60"))

    # Periodic GLOBAL recap-timeout sweep. The per-meeting recap_timeout_check is
    # armed only at desktop Stop, so bot/Recall recaps that wedge in 'processing'
    # never get failed and linger in the UI forever. This fires the global scan on
    # a slower cadence than the zombie sweep (the SELECT is bounded and stuck
    # recaps are rare).
    recap_sweep_counter = 0
    _RECAP_SWEEP_INTERVAL = int(os.getenv("RECAP_GLOBAL_SWEEP_INTERVAL", "300"))

    while not shutdown_event.is_set():
        try:
            # Periodic zombie sweep (Layer 2). Runs concurrently with normal
            # job processing; not gated by queue_mode because zombies can
            # come from any operation type.
            zombie_sweep_counter += 1
            if queue_mode in {"all", "graph_memory"} and zombie_sweep_counter >= _ZOMBIE_SWEEP_INTERVAL:
                zombie_sweep_counter = 0
                try:
                    reset = await reset_zombie_jobs()
                    if reset:
                        logger.warning(
                            "[Worker] zombie_sweep reset %d stuck job(s)", reset
                        )
                except Exception as exc:
                    logger.warning("[Worker] zombie_sweep raised: %s", exc)

            # Periodic global recap-timeout sweep (flips stuck bot/desktop recaps
            # to 'failed'). Independent of queue draining; never fatal to the loop.
            recap_sweep_counter += 1
            if queue_mode in {"all", "graph_memory"} and recap_sweep_counter >= _RECAP_SWEEP_INTERVAL:
                recap_sweep_counter = 0
                try:
                    await sweep_stuck_recaps()
                except Exception as exc:
                    logger.warning("[Worker] recap_sweep raised: %s", exc)

            graph_job_processed = False
            if queue_mode in {"all", "graph_memory"}:
                graph_job_processed = await process_next_graph_outbox_job(worker_id=worker_id)
                if graph_job_processed:
                    consecutive_empty_polls = 0
                    jobs_processed += 1

            if queue_mode == "graph_memory":
                if graph_job_processed:
                    continue

                consecutive_empty_polls += 1
                sleep_time = min(5, 0.5 + (consecutive_empty_polls * 0.1))
                await asyncio.sleep(sleep_time)
                if consecutive_empty_polls % 60 == 0 and consecutive_empty_polls > 0:
                    logger.debug("[Worker] Heartbeat: waiting for graph_outbox jobs...")
                continue

            if graph_job_processed:
                continue

            # Poll for non-graph jobs
            job = dequeue_job()
            if job:
                consecutive_empty_polls = 0
                jobs_processed += 1

                job_id = job.get("job_id")
                job_type = job.get("job_type")

                logger.info("[Worker] Processing job %s (%s)", job_id, job_type)

                start_time = asyncio.get_event_loop().time()
                success = False

                try:
                    # Dispatch based on job type
                    if job_type == "content_extraction":
                        success = await process_content_extraction_job(job_id)
                    elif job_type == "graph_extraction":
                        success = await process_graph_extraction_job(job_id)
                    elif job_type == "feedback_learning":
                        logger.warning("feedback_learning job type is deprecated, skipping")
                        success = True
                    elif job_type in ["ingestion", "reindex", "health_check"]:
                        from modules.training_jobs import (
                            process_training_job_with_retry,
                        )

                        success = await process_training_job_with_retry(job_id)
                    else:
                        logger.warning("[Worker] Unknown job type: %s", job_type)
                        success = False

                except Exception as e:
                    logger.exception("[Worker] Job %s crashed: %s", job_id, e)
                    success = False

                duration = asyncio.get_event_loop().time() - start_time
                status_label = "[OK]" if success else "[FAIL]"
                logger.info("[Worker] %s Job %s finished in %.2fs", status_label, job_id, duration)
            else:
                consecutive_empty_polls += 1
                sleep_time = min(5, 0.5 + (consecutive_empty_polls * 0.1))
                await asyncio.sleep(sleep_time)

                if consecutive_empty_polls % 60 == 0 and consecutive_empty_polls > 0:
                    logger.debug("[Worker] Heartbeat: waiting for jobs... (queue empty)")

        except Exception as e:
            logger.exception("[Worker] Critical error in loop: %s", e)
            await asyncio.sleep(5)

    logger.info("[Worker] Shutdown complete. Processed %s jobs.", jobs_processed)


async def _health_server():
    """Minimal HTTP server for Cloud Run health checks."""
    from aiohttp import web

    async def health(request):
        return web.json_response({"status": "healthy", "service": "personaon-worker"})

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("[Worker] Health server listening on port %s", port)


async def _main(queue_mode: str):
    """Run health server and worker loop concurrently."""
    try:
        await _health_server()
    except Exception as e:
        logger.warning("[Worker] Health server failed (non-fatal): %s", e)
    await worker_loop(queue_mode=queue_mode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Background worker")
    parser.add_argument(
        "--queue",
        choices=["all", "default", "graph_memory"],
        default=os.getenv("WORKER_QUEUE", "all"),
        help="Queue selection",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(queue_mode=args.queue))

