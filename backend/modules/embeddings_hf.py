"""
Hugging Face Embedding Client

Production goal:
- Keep starter-plan deployments stable by avoiding heavyweight local model deps by default.
- Support both lightweight HF Inference API embeddings and optional local sentence-transformers.

Backend modes (HF_EMBEDDING_BACKEND):
- "auto" (default): uses Inference API when HF_API_TOKEN is set, otherwise local backend.
- "inference_api": always call Hugging Face Inference API.
- "local": always use sentence-transformers locally.

Environment variables:
- HF_EMBEDDING_MODEL (default: sentence-transformers/all-MiniLM-L6-v2)
- HF_EMBEDDING_DIMENSION (default: 384)
- HF_EMBEDDING_BACKEND (auto|inference_api|local)
- HF_API_TOKEN or HUGGINGFACEHUB_API_TOKEN (for inference_api)
- HF_EMBEDDING_API_URL (optional custom endpoint)
- HF_EMBEDDING_TIMEOUT_SECONDS (default: 30)
- HF_EMBEDDING_DEVICE (local backend only, cpu|cuda)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSION = 384
DEFAULT_TIMEOUT_SECONDS = 30.0


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except Exception:
        return default


def _safe_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


class HFEmbeddingClient:
    """
    Hugging Face embedding client with singleton lifecycle.
    """

    _instance: HFEmbeddingClient | None = None
    _initialized: bool = False

    def __new__(cls, model_name: str | None = None) -> HFEmbeddingClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, model_name: str | None = None):
        if self._initialized:
            return

        self._model_name = model_name or os.getenv("HF_EMBEDDING_MODEL", DEFAULT_MODEL)
        self._dimension = _safe_int(os.getenv("HF_EMBEDDING_DIMENSION"), DEFAULT_DIMENSION)
        self._timeout = _safe_float(os.getenv("HF_EMBEDDING_TIMEOUT_SECONDS"), DEFAULT_TIMEOUT_SECONDS)

        self._api_token = os.getenv("HF_API_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
        default_api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self._model_name}"
        self._api_url = os.getenv("HF_EMBEDDING_API_URL", default_api_url)

        self._backend = self._resolve_backend()
        self._model = None
        self._device = "cpu"

        if self._backend == "local":
            self._load_local_model()
        else:
            logger.info("[HF Embeddings] Using inference_api backend: model=%s", self._model_name)

        self._initialized = True

    def _resolve_backend(self) -> str:
        raw_backend = (os.getenv("HF_EMBEDDING_BACKEND", "auto") or "auto").strip().lower()
        if raw_backend in {"api", "inference"}:
            raw_backend = "inference_api"
        if raw_backend not in {"auto", "inference_api", "local"}:
            logger.warning("[HF Embeddings] Unknown backend '%s', defaulting to auto", raw_backend)
            raw_backend = "auto"

        if raw_backend == "auto":
            # Starter-plan friendly default: if token exists, use API backend to avoid local model bootstrap.
            return "inference_api" if self._api_token else "local"
        return raw_backend

    def _detect_device(self) -> str:
        try:
            import torch

            if torch.cuda.is_available():
                logger.info("[HF Embeddings] CUDA available: %s", torch.cuda.get_device_name(0))
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _load_local_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise RuntimeError(
                "Local HF embedding backend requires sentence-transformers. "
                "Install: pip install -r requirements-ml-local.txt"
            ) from e

        self._device = os.getenv("HF_EMBEDDING_DEVICE", self._detect_device())
        logger.info("[HF Embeddings] Loading local model=%s device=%s", self._model_name, self._device)
        self._model = SentenceTransformer(self._model_name, device=self._device)
        dim = self._model.get_sentence_embedding_dimension()
        if dim:
            self._dimension = int(dim)
        logger.info("[HF Embeddings] Local model loaded. dimension=%s", self._dimension)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    def _mean_pool(self, token_embeddings: list[list[Any]]) -> list[float]:
        if not token_embeddings:
            return []
        first = token_embeddings[0]
        if not isinstance(first, list) or not first:
            return []
        dim = len(first)
        totals = [0.0] * dim
        rows = 0
        for row in token_embeddings:
            if not isinstance(row, list) or len(row) != dim:
                continue
            try:
                for idx, value in enumerate(row):
                    totals[idx] += float(value)
                rows += 1
            except Exception:
                continue
        if rows == 0:
            return []
        return [v / rows for v in totals]

    def _extract_embedding(self, payload: Any) -> list[float]:
        # Most common direct shape: [float, float, ...]
        if isinstance(payload, list):
            if not payload:
                return []
            if all(isinstance(x, (int, float)) for x in payload):
                return [float(x) for x in payload]
            if all(isinstance(x, list) for x in payload):
                # Token embeddings shape: [[...], [...], ...] -> mean pool.
                return self._mean_pool(payload)  # type: ignore[arg-type]
            if all(isinstance(x, dict) for x in payload):
                for item in payload:
                    emb = self._extract_embedding(item)
                    if emb:
                        return emb
                return []

        if isinstance(payload, dict):
            if "error" in payload and payload["error"]:
                raise RuntimeError(f"HuggingFace API error: {payload['error']}")

            # Known keys across providers/wrappers.
            for key in ("embedding", "vector", "embeddings"):
                if key in payload:
                    emb = self._extract_embedding(payload[key])
                    if emb:
                        return emb

            # OpenAI-style payloads: {"data":[{"embedding":[...]}]}
            if "data" in payload:
                emb = self._extract_embedding(payload["data"])
                if emb:
                    return emb

        return []

    def _embed_via_inference_api(self, text: str) -> list[float]:
        body = {
            "inputs": text,
            "options": {"wait_for_model": True},
        }

        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(self._api_url, headers=self._headers(), json=body)

        if response.status_code >= 400:
            snippet = response.text[:300]
            raise RuntimeError(
                f"HF embedding request failed ({response.status_code}): {snippet}"
            )

        payload = response.json()
        embedding = self._extract_embedding(payload)
        if not embedding:
            raise RuntimeError("HF embedding response did not contain a valid embedding vector")

        self._dimension = len(embedding)
        return embedding

    def embed(self, text: str) -> list[float]:
        clean_text = text if isinstance(text, str) else ""
        if not clean_text:
            clean_text = ""

        if self._backend == "inference_api":
            return self._embed_via_inference_api(clean_text)

        if not self._model:
            raise RuntimeError("HF local model is not initialized")

        try:
            embedding = self._model.encode(
                clean_text,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            return embedding.tolist()
        except Exception as e:
            raise RuntimeError(f"HF local embedding generation failed: {e}") from e

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
        show_progress: bool = False,
    ) -> list[list[float]]:
        if not texts:
            return []
        clean_texts = [t if isinstance(t, str) else "" for t in texts]

        if self._backend == "inference_api":
            # HF Inference API can be sensitive to batch payload shape by model; use safe per-item calls.
            return [self.embed(t) for t in clean_texts]

        if not self._model:
            raise RuntimeError("HF local model is not initialized")

        try:
            embeddings = self._model.encode(
                clean_texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return embeddings.tolist()
        except Exception as e:
            raise RuntimeError(f"HF local batch embedding generation failed: {e}") from e

    def embed_with_retry(self, text: str, max_retries: int = 3) -> list[float] | None:
        for attempt in range(max_retries):
            try:
                return self.embed(text)
            except Exception as e:
                logger.warning("[HF Embeddings] Attempt %s failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    time.sleep(0.15 * (2**attempt))
        logger.error("[HF Embeddings] All retries exhausted")
        return None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def device(self) -> str:
        return self._device

    @property
    def backend(self) -> str:
        return self._backend

    def health_check(self) -> dict:
        return {
            "status": "healthy",
            "backend": self._backend,
            "model": self._model_name,
            "device": self._device,
            "dimension": self._dimension,
            "api_url": self._api_url if self._backend == "inference_api" else None,
            "initialized": self._initialized,
        }

    @classmethod
    def reset(cls) -> None:
        cls._instance = None
        cls._initialized = False
        logger.info("[HF Embeddings] Singleton reset")


def get_hf_embedding(text: str) -> list[float]:
    client = HFEmbeddingClient()
    return client.embed(text)


async def get_hf_embeddings_async(texts: list[str]) -> list[list[float]]:
    client = HFEmbeddingClient()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, client.embed_batch, texts)
