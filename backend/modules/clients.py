import logging
import os
import asyncpg
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

try:
    import cohere
except ImportError:
    cohere = None

load_dotenv()

_openai_client = None
_async_openai_client = None
_gemini_client = None
_async_gemini_client = None
_pgvector_pool: asyncpg.Pool | None = None
_cohere_client = None

def get_cohere_client(required: bool = False):
    """
    Get or create singleton Cohere client.

    Args:
        required: If True, raises error if client cannot be created

    Returns:
        Cohere client instance or None (if not required)

    Raises:
        ValueError: If required=True and COHERE_API_KEY not set or cohere package missing
    """
    global _cohere_client
    if _cohere_client is None:
        api_key = os.getenv("COHERE_API_KEY")

        # Validation with clear error messages
        if not api_key:
            error_msg = (
                "COHERE_API_KEY environment variable not set. "
                "Reranking requires Cohere API key. "
                "Get one at: https://dashboard.cohere.com/api-keys"
            )
            if required:
                raise ValueError(error_msg)
            logger.warning("[Cohere] %s", error_msg)
            return None

        if cohere is None:
            error_msg = (
                "cohere package not installed. "
                "Run: pip install cohere"
            )
            if required:
                raise ValueError(error_msg)
            logger.warning("[Cohere] %s", error_msg)
            return None

        try:
            _cohere_client = cohere.ClientV2(api_key=api_key)
            logger.info("[Cohere] Client initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize Cohere client: {e}"
            if required:
                raise ValueError(error_msg) from e
            logger.warning("[Cohere] %s", error_msg)
            return None

    return _cohere_client


def validate_cohere_config(strict: bool = True) -> bool:
    """
    Validate Cohere configuration and raise clear errors if invalid.

    Args:
        strict: If True, raises ValueError on any issue

    Returns:
        True if valid, False if not (only when strict=False)
    """
    api_key = os.getenv("COHERE_API_KEY")

    if not api_key:
        if strict:
            raise ValueError(
                "RERANKING ERROR: COHERE_API_KEY environment variable not set. "
                "Reranking is REQUIRED for production. "
                "Get your API key at: https://dashboard.cohere.com/api-keys "
                "Set it with: export COHERE_API_KEY='your-key-here'"
            )
        return False

    if cohere is None:
        if strict:
            raise ValueError(
                "RERANKING ERROR: cohere package not installed. "
                "Run: pip install cohere"
            )
        return False

    # Try to create client to validate key format
    try:
        _ = cohere.ClientV2(api_key=api_key)
        logger.info("[Cohere] Configuration validated successfully")
        return True
    except Exception as e:
        if strict:
            raise ValueError(f"RERANKING ERROR: Invalid Cohere API key: {e}")
        return False

def get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

def get_async_openai_client():
    global _async_openai_client
    if _async_openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")
        _async_openai_client = AsyncOpenAI(api_key=api_key)
    return _async_openai_client

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        base_url = os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        _gemini_client = OpenAI(api_key=api_key, base_url=base_url)
    return _gemini_client

def get_async_gemini_client():
    global _async_gemini_client
    if _async_gemini_client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        base_url = os.getenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        _async_gemini_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _async_gemini_client

_genai_client = None

def get_gemini_genai_client():
    """Get a native google.genai Client (not OpenAI-compat wrapper)."""
    global _genai_client
    if _genai_client is None:
        import google.genai as genai
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client


# pgvector Connection Pool (asyncpg)

async def get_pgvector_pool() -> asyncpg.Pool:
    """Get or create singleton asyncpg connection pool for pgvector operations.

    Uses PGVECTOR_DATABASE_URL which MUST be on port 5432 (direct connection).
    Port 6543 (pgbouncer) breaks asyncpg prepared statements.
    """
    global _pgvector_pool
    if _pgvector_pool is None:
        dsn = os.getenv("PGVECTOR_DATABASE_URL")
        if not dsn:
            raise ValueError(
                "PGVECTOR_DATABASE_URL not set. "
                "Required for pgvector operations. "
                "Must use port 5432 (direct), NOT 6543 (pgbouncer)."
            )
        if ":6543" in dsn:
            raise ValueError(
                "PGVECTOR_DATABASE_URL uses port 6543 (pgbouncer). "
                "asyncpg requires port 5432 (direct connection). "
                "pgbouncer transaction mode breaks prepared statements."
            )
        _pgvector_pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("[pgvector] Connection pool created (port 5432 direct)")
    return _pgvector_pool


async def close_pgvector_pool() -> None:
    """Close the pgvector connection pool (for graceful shutdown)."""
    global _pgvector_pool
    if _pgvector_pool is not None:
        await _pgvector_pool.close()
        _pgvector_pool = None
        logger.info("[pgvector] Connection pool closed")
