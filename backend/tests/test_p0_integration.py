"""
P0 Integration Tests - Day 5
Tests the 5 golden flows to ensure reliability and security.

Golden Flows:
1. Signup/login/invite + tenant isolation
2. Create twin + onboarding completes
3. Upload doc → chunks/embeddings → retrieval works
4. Chat → verified hit OR vector fallback (no empty responses)
5. Graph learning job → nodes/edges written → retrievable
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from datetime import datetime


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client."""
    with patch('modules.observability.supabase') as mock:
        with patch('modules.jobs.supabase', new=mock):
            mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
            mock.table.return_value.insert.return_value.execute.return_value.data = [{"id": "test-id"}]
            yield mock


@pytest.fixture
def mock_openai():
    """Mock OpenAI client."""
    with patch('modules.clients.get_async_openai_client') as mock_async, \
         patch('modules._core.scribe_engine.get_async_openai_client') as mock_scribe_async, \
         patch('modules.embeddings.get_openai_client') as mock_embeddings_client:
        client = AsyncMock()
        mock_async.return_value = client
        mock_scribe_async.return_value = client

        # Sync client for embeddings/expansion paths
        sync_client = MagicMock()
        sync_client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 3072)]
        )
        mock_embeddings_client.return_value = sync_client

        yield client




# ============================================================================
# Golden Flow 1: Signup/login/invite + tenant isolation
# ============================================================================

def test_tenant_isolation(mock_supabase):
    """Test that users can only access their own tenant's data."""
    from modules.auth_guard import verify_twin_ownership

    # User from tenant A
    user_a = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "role": "owner"
    }

    # Twin belongs to tenant B
    # Tenant mismatch should result in no record due to tenant_id filter in query
    # verify_twin_ownership uses get_supabase_client() and .maybe_single()
    # (0 rows -> data None -> clean 404 rather than a PGRST116 500).
    client = MagicMock()
    twins_query = client.table.return_value.select.return_value
    eq_tenant = twins_query.eq.return_value.eq
    eq_tenant.return_value.maybe_single.return_value.execute.return_value.data = None

    # Should raise 404 (not found or access denied)
    with patch("modules.observability.get_supabase_client", return_value=client):
        with pytest.raises(HTTPException) as exc_info:
            verify_twin_ownership("twin-1", user_a)

    assert exc_info.value.status_code == 404
    assert "not found or access denied" in exc_info.value.detail.lower()
    # The query must be scoped by the caller's tenant, not just the twin id.
    eq_tenant.assert_called_once_with("tenant_id", "tenant-a")


def test_source_ownership_verification(mock_supabase):
    """Test that source ownership is verified."""
    from modules.auth_guard import verify_source_ownership

    user = {
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "role": "owner"
    }

    # Source belongs to twin in different tenant
    sources_query = MagicMock()
    sources_query.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "source-1",
        "twin_id": "twin-2"
    }
    twins_query = MagicMock()
    twins_query.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = None

    def side_effect(table_name):
        if table_name == "sources":
            return sources_query
        if table_name == "twins":
            return twins_query
        return MagicMock()

    mock_supabase.table.side_effect = side_effect

    with pytest.raises(HTTPException) as exc_info:
        verify_source_ownership("source-1", user)

    assert exc_info.value.status_code == 404


# ============================================================================
# Golden Flow 2: Create twin + onboarding completes
# ============================================================================

def test_create_twin_flow(mock_supabase):
    """Test creating a twin and verifying it's accessible."""
    from modules.auth_guard import verify_twin_ownership

    user = {
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "role": "owner"
    }

    # Twin belongs to user's tenant
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "twin-1",
        "tenant_id": "tenant-1"
    }

    # Should not raise exception
    verify_twin_ownership("twin-1", user)


# ============================================================================
# Golden Flow 3: Upload doc → chunks/embeddings → retrieval works
# ============================================================================

# test_ingestion_retrieval_flow and test_chat_retrieval_fallback removed:
# they tested modules.retrieval which was replaced by agent_service + vector_store.

# ============================================================================
# Golden Flow 5: Graph learning job → nodes/edges written → retrievable
# ============================================================================

def test_graph_extraction_job_enqueue(mock_supabase):
    """Test that graph extraction jobs are enqueued correctly."""
    from modules._core.scribe_engine import enqueue_graph_extraction_job
    from modules.jobs import JobType, JobStatus

    # Mock job creation
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
        "id": "job-1",
        "twin_id": "twin-1",
        "job_type": JobType.GRAPH_EXTRACTION.value,
        "status": JobStatus.QUEUED.value,
        "priority": 0,
        "metadata": {},
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "started_at": None,
        "completed_at": None,
        "error_message": None
    }]

    # Mock idempotency check (no existing jobs)
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    # Enqueue job
    job_id = enqueue_graph_extraction_job(
        twin_id="twin-1",
        user_message="What is AI?",
        assistant_message="AI is artificial intelligence.",
        conversation_id="conv-1",
        tenant_id="tenant-1"
    )

    assert job_id is not None
    assert job_id == "job-1"


def test_graph_extraction_idempotency(mock_supabase):
    """Test that duplicate graph extraction jobs are not created."""
    from modules._core.scribe_engine import enqueue_graph_extraction_job, _generate_idempotency_key
    from modules.jobs import JobType, JobStatus

    # Generate the idempotency key that will be used
    user_msg = "What is AI?"
    assistant_msg = "AI is artificial intelligence."
    idempotency_key = _generate_idempotency_key("conv-1", user_msg, assistant_msg)

    # Mock existing job (already processed) - this will be found by idempotency check
    existing_job = {
        "id": "existing-job-1",
        "twin_id": "twin-1",
        "job_type": JobType.GRAPH_EXTRACTION.value,
        "status": JobStatus.COMPLETE.value,
        "priority": 0,
        "metadata": {
            "idempotency_key": idempotency_key
        },
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": datetime.utcnow().isoformat(),
        "error_message": None
    }

    # Set up mock to return existing job when checking idempotency
    def table_side_effect(table_name):
        mock_table = MagicMock()
        if table_name == "jobs":
            # For select (idempotency check)
            select_mock = MagicMock()
            select_mock.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [existing_job]
            mock_table.select.return_value = select_mock
            # For insert (should not be called, but mock it anyway)
            mock_table.insert.return_value.execute.return_value.data = [{"id": "new-job-1"}]
        return mock_table

    mock_supabase.table.side_effect = table_side_effect

    # Should return existing job ID (idempotent)
    job_id = enqueue_graph_extraction_job(
        twin_id="twin-1",
        user_message=user_msg,
        assistant_message=assistant_msg,
        conversation_id="conv-1",
        tenant_id="tenant-1"
    )

    assert job_id == "existing-job-1"


@pytest.mark.asyncio
async def test_graph_extraction_job_processing(mock_supabase, mock_openai):
    """Test that graph extraction jobs are processed correctly."""
    from modules._core.scribe_engine import process_graph_extraction_job

    # Mock job retrieval
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "id": "job-1",
        "twin_id": "twin-1",
        "status": "queued",
        "metadata": {
            "user_message": "What is AI?",
            "assistant_message": "AI is artificial intelligence.",
            "conversation_id": "conv-1",
            "tenant_id": "tenant-1"
        }
    }

    # Mock OpenAI structured output
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = MagicMock()
    mock_response.choices[0].message.parsed.nodes = []
    mock_response.choices[0].message.parsed.edges = []
    mock_response.choices[0].message.parsed.confidence = 0.9

    mock_openai.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    # Mock RPC calls for graph saving
    mock_supabase.rpc.return_value.execute.return_value.data = [{"id": "node-1", "name": "Node1"}]

    # Mock Insert (for memory events)
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{"id": "evt-1"}]

    # Patch job operations to avoid validation errors
    with patch('modules._core.scribe_engine.start_job') as mock_start, \
         patch('modules._core.scribe_engine.complete_job') as mock_complete, \
         patch('modules._core.scribe_engine.append_log') as mock_append:

        # Process job
        result = await process_graph_extraction_job("job-1")

        # Should complete successfully
        assert result is True
        mock_start.assert_called_once()
        mock_complete.assert_called_once()


def test_security_definer_functions_hardened():
    """Test that SECURITY DEFINER functions have proper hardening."""
    # Read the hardening migration
    import os
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "database",
        "migrations",
        "migration_security_definer_hardening.sql"
    )

    if os.path.exists(migration_path):
        with open(migration_path) as f:
            content = f.read()

            # Check that all functions have SET search_path = ''
            assert "SET search_path = ''" in content or "SET search_path = ''" in content

            # Check that table references are fully qualified
            assert "FROM public.twins" in content or "FROM public.nodes" in content
    else:
        pytest.skip("Hardening migration not found")


# ============================================================================
# Integration Test: End-to-End Chat Flow
# ============================================================================

@pytest.mark.asyncio
async def test_chat_flow_with_graph_extraction(mock_supabase, mock_openai):
    """Test complete chat flow including graph extraction job enqueue."""
    from modules._core.scribe_engine import enqueue_graph_extraction_job

    # Mock conversation creation
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{
        "id": "conv-1",
        "twin_id": "twin-1"
    }]

    # Mock idempotency check
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    # Patch create_job and enqueue_job to avoid validation errors / in-memory queue collisions
    with patch('modules._core.scribe_engine.create_job') as mock_create, \
         patch('modules._core.scribe_engine.enqueue_job') as mock_enqueue:
        mock_create.return_value.id = "job-1"
        mock_enqueue.return_value = None

        # Enqueue graph extraction
        job_id = enqueue_graph_extraction_job(
            twin_id="twin-1",
            user_message="Tell me about AI",
            assistant_message="AI stands for Artificial Intelligence.",
            conversation_id="conv-1",
            tenant_id="tenant-1"
        )

        assert job_id is not None
        assert job_id == "job-1"
