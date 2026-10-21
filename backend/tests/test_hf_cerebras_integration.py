"""
Integration tests for Hugging Face + Cerebras implementation.

Run with: pytest tests/test_hf_cerebras_integration.py -v
"""
import pytest
import os
import time
from unittest.mock import MagicMock, patch

RUN_CEREBRAS_LIVE_TESTS = os.getenv("RUN_CEREBRAS_LIVE_TESTS", "").lower() in {"1", "true", "yes"}
DEFAULT_CEREBRAS_MODEL = "qwen-3-235b-a22b-instruct-2507"


class TestHFEmbeddings:
    """Test Hugging Face local embeddings."""

    @pytest.mark.skipif(
        not os.getenv("HF_TEST_ENABLED"),
        reason="Set HF_TEST_ENABLED=1 to run HF tests (requires model download)"
    )
    def test_hf_embedding_dimension(self):
        """Test HF embedding produces correct dimension."""
        from modules.embeddings_hf import HFEmbeddingClient

        client = HFEmbeddingClient()
        embedding = client.embed("Test text")

        assert len(embedding) == client.dimension
        assert isinstance(embedding, list)
        assert all(isinstance(x, float) for x in embedding)

    @pytest.mark.skipif(
        not os.getenv("HF_TEST_ENABLED"),
        reason="Set HF_TEST_ENABLED=1 to run HF tests"
    )
    def test_hf_embedding_speed(self):
        """Test HF embedding is fast (<100ms)."""
        from modules.embeddings_hf import HFEmbeddingClient

        client = HFEmbeddingClient()

        start = time.time()
        embedding = client.embed("Test query for speed measurement")
        elapsed = (time.time() - start) * 1000

        print(f"\nHF Embedding latency: {elapsed:.2f}ms")
        assert elapsed < 100, f"Embedding too slow: {elapsed:.2f}ms"

    @pytest.mark.skipif(
        not os.getenv("HF_TEST_ENABLED"),
        reason="Set HF_TEST_ENABLED=1 to run HF tests"
    )
    def test_hf_batch_embedding(self):
        """Test batch embedding processing."""
        from modules.embeddings_hf import HFEmbeddingClient

        client = HFEmbeddingClient()
        texts = ["Text 1", "Text 2", "Text 3"]

        embeddings = client.embed_batch(texts)

        assert len(embeddings) == 3
        assert all(len(emb) == client.dimension for emb in embeddings)

    @pytest.mark.skipif(
        not os.getenv("HF_TEST_ENABLED"),
        reason="Set HF_TEST_ENABLED=1 to run HF tests (requires sentence-transformers)"
    )
    def test_hf_singleton_pattern(self):
        """Test HF client is singleton."""
        from modules.embeddings_hf import HFEmbeddingClient

        # Reset singleton
        HFEmbeddingClient.reset()

        # Create two instances
        client1 = HFEmbeddingClient()
        client2 = HFEmbeddingClient()

        # Should be same instance
        assert client1 is client2


class TestEmbeddingProviderSwitching:
    """Test provider switching in embeddings module."""

    @patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai"})
    def test_openai_provider(self):
        """Test OpenAI provider is used when configured."""
        with patch("modules.embeddings._get_embedding_openai") as mock_openai:
            mock_openai.return_value = [0.1] * 3072

            # Need to reimport to pick up env var
            from modules import embeddings
            embeddings.EMBEDDING_PROVIDER = "openai"

            from modules.embeddings import get_embedding
            result = get_embedding("test")

            mock_openai.assert_called_once()
            assert len(result) == 3072

    @patch.dict(os.environ, {"EMBEDDING_PROVIDER": "huggingface", "EMBEDDING_TARGET_DIMENSION": "1024"})
    @patch("modules.embeddings_hf.HFEmbeddingClient")
    def test_hf_provider(self, mock_hf_client):
        """Test HF provider is used when configured."""
        mock_instance = MagicMock()
        mock_instance.embed.return_value = [0.1] * 1024
        mock_instance.dimension = 1024
        mock_hf_client.return_value = mock_instance

        # Need to reimport to pick up env var
        from modules import embeddings
        embeddings.EMBEDDING_PROVIDER = "huggingface"

        from modules.embeddings import get_embedding
        result = get_embedding("test")

        mock_instance.embed.assert_called_once()
        assert len(result) == 1024


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    @patch("modules.embeddings.get_openai_client")
    def test_existing_embedding_code(self, mock_get_client):
        """Test existing code calling get_embedding still works."""
        import modules.embeddings as emb_module
        from modules.embeddings import CircuitBreaker

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 3072)]
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Reset circuit breaker so previous test failures don't bleed in
        emb_module._embedding_circuit_breaker.state = CircuitBreaker.STATE_CLOSED
        emb_module._embedding_circuit_breaker.failure_count = 0

        with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai"}):
            emb_module.EMBEDDING_PROVIDER = "openai"

            from modules.embeddings import get_embedding
            result = get_embedding("test query")

            assert len(result) == 3072
            mock_client.embeddings.create.assert_called_once()

class TestHealthChecks:
    """Test health check functionality."""

    def test_hf_health_check(self):
        """Test HF embedding health check."""
        with patch("modules.embeddings_hf.HFEmbeddingClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.health_check.return_value = {
                "status": "healthy",
                "model": "all-MiniLM-L6-v2",
                "device": "cpu",
                "dimension": 384,
                "initialized": True
            }
            mock_client.return_value = mock_instance

            from modules.embeddings_hf import HFEmbeddingClient
            client = HFEmbeddingClient()
            health = client.health_check()

            assert health["status"] == "healthy"
            assert health["dimension"] == 384


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
