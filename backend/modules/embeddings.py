"""
Embeddings Module: Centralized embedding generation and utilities.

This module provides unified embedding generation functions to avoid duplication
across ingestion, verified_qna, and retrieval modules.

PROVIDER SUPPORT:
- Gemini: gemini-embedding-001 (default, 3072 dims — free with GOOGLE_API_KEY)
- OpenAI: text-embedding-3-large (fallback, 3072 dims)
- Hugging Face: API-backed or local backend (dimension depends on selected model)

Environment Variables:
- EMBEDDING_PROVIDER: "gemini" (default), "openai", or "huggingface"
- HF_EMBEDDING_MODEL: Model name (default: all-MiniLM-L6-v2)
- HF_EMBEDDING_DEVICE: "cpu" or "cuda" (auto-detected if not set)

SECURITY FIXES:
- Added timeout handling for all external API calls (HIGH Bug H2)
- Retry logic with exponential backoff
- Circuit breaker pattern for resilience
- Automatic fallback between providers
"""
import os
import asyncio
import time
import logging
from functools import wraps, lru_cache
from modules.clients import get_openai_client

# Configure logger
logger = logging.getLogger(__name__)

# =============================================================================
# PROVIDER CONFIGURATION (NEW)
# =============================================================================

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()
EMBEDDING_FALLBACK_ENABLED = os.getenv("EMBEDDING_FALLBACK_ENABLED", "true").lower() == "true"
OPENAI_BATCH_EMBEDDINGS_ENABLED = os.getenv("OPENAI_BATCH_EMBEDDINGS_ENABLED", "false").lower() == "true"
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2-preview")

# Validate provider
if EMBEDDING_PROVIDER not in ["gemini", "openai", "huggingface"]:
    logger.warning(f"[Embeddings] Unknown provider '{EMBEDDING_PROVIDER}', using 'gemini'")
    EMBEDDING_PROVIDER = "gemini"

logger.info(f"[Embeddings] Using provider: {EMBEDDING_PROVIDER}")

# =============================================================================
# TIMEOUT AND RETRY CONFIGURATION (CRITICAL BUG FIX: H2)
# =============================================================================

# Default timeouts (seconds)
EMBEDDING_TIMEOUT = int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30"))
EMBEDDING_RETRY_ATTEMPTS = int(os.getenv("EMBEDDING_RETRY_ATTEMPTS", "3"))
EMBEDDING_RETRY_DELAY = float(os.getenv("EMBEDDING_RETRY_DELAY", "1.0"))
EMBEDDING_RETRY_BACKOFF = float(os.getenv("EMBEDDING_RETRY_BACKOFF", "2.0"))

# Circuit breaker settings
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_TIMEOUT = int(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60"))  # Seconds before reset


class CircuitBreaker:
    """
    Circuit breaker pattern to prevent cascading failures.

    States:
    - CLOSED: Normal operation
    - OPEN: Failing fast (recent failures exceeded threshold)
    - HALF_OPEN: Testing if service recovered
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD, timeout: int = CIRCUIT_BREAKER_TIMEOUT):
        self.threshold = threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = self.STATE_CLOSED

    def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        if self.state == self.STATE_OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                self.state = self.STATE_HALF_OPEN
            else:
                raise Exception("Circuit breaker is OPEN - service temporarily unavailable")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call."""
        self.failure_count = 0
        self.state = self.STATE_CLOSED

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.threshold:
            self.state = self.STATE_OPEN


# Global circuit breaker for embeddings
_embedding_circuit_breaker = CircuitBreaker()


def with_retry_and_timeout(max_attempts: int = None, timeout_seconds: int = None):
    """
    Decorator to add retry logic with timeout to embedding operations.

    Args:
        max_attempts: Maximum retry attempts
        timeout_seconds: Timeout per attempt in seconds
    """
    max_attempts = max_attempts or EMBEDDING_RETRY_ATTEMPTS
    timeout_seconds = timeout_seconds or EMBEDDING_TIMEOUT

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = EMBEDDING_RETRY_DELAY
            last_error = None

            for attempt in range(max_attempts):
                try:
                    # Use asyncio.wait_for for timeout if in async context
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(func, *args, **kwargs)
                        return future.result(timeout=timeout_seconds)

                except concurrent.futures.TimeoutError:
                    last_error = TimeoutError(f"Embedding request timed out after {timeout_seconds}s")
                    logger.warning("[Embedding] Timeout on attempt %s/%s", attempt + 1, max_attempts)
                except Exception as e:
                    last_error = e
                    error_msg = str(e).lower()

                    # Don't retry on auth errors or invalid input
                    non_retryable = ["authentication", "invalid", "not found", "permission"]
                    if any(nr in error_msg for nr in non_retryable):
                        raise

                    logger.warning("[Embedding] Error on attempt %s/%s: %s", attempt + 1, max_attempts, e)

                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= EMBEDDING_RETRY_BACKOFF

            raise last_error or Exception("Embedding failed after all retries")

        return wrapper
    return decorator


# =============================================================================
# PROVIDER-SPECIFIC IMPLEMENTATIONS
# =============================================================================

def _get_embedding_gemini(text: str) -> list[float]:
    """Generate embedding using Gemini API (free with GOOGLE_API_KEY)."""
    import google.genai as genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not found in environment")

    target_dim = _resolve_target_dimension()

    def _fetch():
        client = genai.Client(api_key=api_key)
        config = {}
        if target_dim and target_dim < 3072:
            config["output_dimensionality"] = int(target_dim)
        result = client.models.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            contents=text,
            config=config if config else None,
        )
        return list(result.embeddings[0].values)

    return _embedding_circuit_breaker.call(_fetch)


def _get_embedding_openai(text: str) -> list[float]:
    """Generate embedding using OpenAI API."""
    client = get_openai_client()
    target_dim = _resolve_target_dimension()
    requested_dim = (
        int(target_dim)
        if target_dim and 1 <= int(target_dim) <= 3072
        else 3072
    )

    def _fetch():
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-large",
            dimensions=requested_dim
        )
        return response.data[0].embedding

    return _embedding_circuit_breaker.call(_fetch)


def _get_embedding_huggingface(text: str) -> list[float]:
    """Generate embedding using configured Hugging Face backend."""
    from modules.embeddings_hf import HFEmbeddingClient

    client = HFEmbeddingClient()
    return client.embed(text)


@lru_cache(maxsize=1)
def _resolve_target_dimension() -> int | None:
    """Resolve expected vector dimension from EMBEDDING_TARGET_DIMENSION env var."""
    configured_target = os.getenv("EMBEDDING_TARGET_DIMENSION")
    if configured_target:
        try:
            return int(configured_target)
        except ValueError:
            logger.warning(
                "[Embeddings] Invalid EMBEDDING_TARGET_DIMENSION='%s' (must be int). Ignoring.",
                configured_target,
            )
    return None


def _ensure_hf_dimension_compatibility() -> None:
    """
    Ensure HF embedding dimensions match the active vector index.

    If dimensions differ, fallback to OpenAI (if enabled) or raise.
    """
    from modules.embeddings_hf import HFEmbeddingClient

    target_dim = _resolve_target_dimension()
    if not target_dim:
        return

    hf_client = HFEmbeddingClient()
    hf_dim = int(hf_client.dimension)

    if hf_dim == target_dim:
        return

    msg = (
        f"[Embeddings] HuggingFace dimension mismatch: model_dim={hf_dim}, "
        f"target_dim={target_dim}. Configure a matching index/model or set "
        "EMBEDDING_PROVIDER=openai."
    )
    if EMBEDDING_FALLBACK_ENABLED:
        logger.warning("%s Falling back to OpenAI embeddings.", msg)
        raise RuntimeError("HF_DIMENSION_MISMATCH_FALLBACK")

    raise RuntimeError(msg)


# =============================================================================
# UNIFIED EMBEDDING FUNCTIONS WITH PROVIDER SWITCHING
# =============================================================================

@with_retry_and_timeout()
def get_embedding(text: str) -> list[float]:
    """
    Generate embedding for a single text using configured provider.

    Provider is determined by EMBEDDING_PROVIDER environment variable:
    - "openai" (default): Uses OpenAI API (3072 dims, ~340ms)
    - "huggingface": Uses local HF model (dimension depends on selected model)

    With EMBEDDING_FALLBACK_ENABLED=true, automatically falls back to OpenAI
    if Hugging Face fails.

    Args:
        text: Text to embed

    Returns:
        List of floats representing the embedding vector

    Raises:
        TimeoutError: If request exceeds timeout
        Exception: On API errors (if fallback disabled or both fail)
    """
    # Try primary provider
    if EMBEDDING_PROVIDER == "huggingface":
        try:
            _ensure_hf_dimension_compatibility()
            return _get_embedding_huggingface(text)
        except Exception as e:
            if EMBEDDING_FALLBACK_ENABLED:
                logger.warning(f"[Embeddings] HuggingFace failed: {e}")
                logger.info("[Embeddings] Falling back to Gemini")
                return _get_embedding_gemini(text)
            raise

    if EMBEDDING_PROVIDER == "openai":
        return _get_embedding_openai(text)

    # Default: Gemini
    try:
        return _get_embedding_gemini(text)
    except Exception as e:
        if EMBEDDING_FALLBACK_ENABLED:
            logger.warning(f"[Embeddings] Gemini failed: {e}")
            logger.info("[Embeddings] Falling back to OpenAI")
            return _get_embedding_openai(text)
        raise


async def _get_embeddings_async_gemini(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using Gemini API (async wrapper)."""
    import google.genai as genai

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not found in environment")

    target_dim = _resolve_target_dimension()
    loop = asyncio.get_event_loop()

    def _fetch():
        client = genai.Client(api_key=api_key)
        config = {}
        if target_dim and target_dim < 3072:
            config["output_dimensionality"] = int(target_dim)
        result = client.models.embed_content(
            model=GEMINI_EMBEDDING_MODEL,
            contents=texts,
            config=config if config else None,
        )
        return [list(e.values) for e in result.embeddings]

    return await loop.run_in_executor(None, lambda: _embedding_circuit_breaker.call(_fetch))


async def _get_embeddings_async_openai(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using OpenAI API (async wrapper)."""
    client = get_openai_client()
    target_dim = _resolve_target_dimension()
    requested_dim = (
        int(target_dim)
        if target_dim and 1 <= int(target_dim) <= 3072
        else 3072
    )
    loop = asyncio.get_event_loop()

    def _fetch():
        response = client.embeddings.create(
            input=texts,
            model="text-embedding-3-large",
            dimensions=requested_dim,
            timeout=EMBEDDING_TIMEOUT
        )
        return [d.embedding for d in response.data]

    return await loop.run_in_executor(None, lambda: _embedding_circuit_breaker.call(_fetch))


async def _get_embeddings_async_huggingface(texts: list[str]) -> list[list[float]]:
    """Generate embeddings using Hugging Face (async wrapper)."""
    from modules.embeddings_hf import HFEmbeddingClient

    client = HFEmbeddingClient()
    loop = asyncio.get_event_loop()

    def _fetch():
        return client.embed_batch(texts)

    return await loop.run_in_executor(None, _fetch)


async def get_embeddings_async(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts asynchronously (batch processing).

    Provider is determined by EMBEDDING_PROVIDER environment variable.
    Supports automatic fallback if enabled.

    Args:
        texts: List of texts to embed

    Returns:
        List of embedding vectors (one per input text)

    Raises:
        TimeoutError: If request exceeds timeout
        Exception: On API errors (if fallback disabled or both fail)
    """
    if not texts:
        return []

    # Try primary provider
    if EMBEDDING_PROVIDER == "huggingface":
        try:
            _ensure_hf_dimension_compatibility()
            return await _get_embeddings_async_huggingface(texts)
        except Exception as e:
            if EMBEDDING_FALLBACK_ENABLED:
                logger.warning(f"[Embeddings] HuggingFace async failed: {e}")
                logger.info("[Embeddings] Falling back to OpenAI")
                return await _get_embeddings_async_openai(texts)
            raise

    if EMBEDDING_PROVIDER == "openai":
        try:
            if OPENAI_BATCH_EMBEDDINGS_ENABLED:
                return await _get_embeddings_async_openai(texts)
            return await asyncio.gather(*[asyncio.to_thread(get_embedding, t) for t in texts])
        except Exception as e:
            if "timeout" in str(e).lower():
                raise TimeoutError(f"Embedding batch request timed out after {EMBEDDING_TIMEOUT}s")
            raise

    # Default: Gemini (batch-native, no per-text overhead)
    try:
        return await _get_embeddings_async_gemini(texts)
    except Exception as e:
        if EMBEDDING_FALLBACK_ENABLED:
            logger.warning(f"[Embeddings] Gemini async batch failed: {e}, falling back to OpenAI")
            return await _get_embeddings_async_openai(texts)
        raise


def get_embedding_with_timeout(text: str, timeout_seconds: int = None) -> list[float] | None:
    """
    Generate embedding with explicit timeout, returns None on failure.

    Args:
        text: Text to embed
        timeout_seconds: Custom timeout (uses default if not specified)

    Returns:
        Embedding vector or None if failed
    """
    timeout = timeout_seconds or EMBEDDING_TIMEOUT

    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(get_embedding, text)
            return future.result(timeout=timeout)
    except Exception as e:
        logger.error("[Embedding] Failed to get embedding: %s", e)
        return None


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Calculate cosine similarity between two embedding vectors.

    Args:
        a: First embedding vector
        b: Second embedding vector

    Returns:
        Cosine similarity score between 0 and 1
    """
    if len(a) != len(b):
        return 0.0

    # Calculate dot product
    dot_product = sum(x * y for x, y in zip(a, b, strict=False))

    # Calculate norms
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    # Avoid division by zero
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot_product / (norm_a * norm_b)


def get_embedding_health_status() -> dict:
    """Get health status of embedding service."""
    target_dim = _resolve_target_dimension()
    return {
        "provider": EMBEDDING_PROVIDER,
        "circuit_breaker_state": _embedding_circuit_breaker.state,
        "failure_count": _embedding_circuit_breaker.failure_count,
        "last_failure": _embedding_circuit_breaker.last_failure_time,
        "target_dimension": target_dim,
        "timeout_config": EMBEDDING_TIMEOUT,
        "retry_config": {
            "attempts": EMBEDDING_RETRY_ATTEMPTS,
            "delay": EMBEDDING_RETRY_DELAY,
            "backoff": EMBEDDING_RETRY_BACKOFF
        }
    }
