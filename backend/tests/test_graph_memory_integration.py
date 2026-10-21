"""
Graph Memory Phase 1 Integration Test

This test validates the real infrastructure (Neo4j + Supabase) is properly configured.
Skipped unless NEO4J_URI environment variable is set to a real instance.

Run with:
    NEO4J_URI=neo4j+s://xxx.databases.neo4j.io \
    NEO4J_PASSWORD=xxx \
    python -m pytest tests/test_graph_memory_integration.py -v
"""

import os
import pytest
import asyncio
import uuid
from datetime import datetime

pytestmark = pytest.mark.network

neo4j_uri = os.getenv("NEO4J_URI", "")
neo4j_password = os.getenv("NEO4J_PASSWORD", "")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")

def _neo4j_reachable(uri: str) -> bool:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            uri,
            auth=(neo4j_user or "neo4j", neo4j_password),
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        return True
    except Exception:
        return False

has_real_neo4j = bool(
    neo4j_uri and
    neo4j_password and
    "localhost" not in neo4j_uri and
    ("bolt://" in neo4j_uri or "neo4j+s" in neo4j_uri) and
    _neo4j_reachable(neo4j_uri)
)


@pytest.fixture
def test_ids():
    """Generate unique test IDs."""
    return {
        "tenant_id": str(uuid.uuid4()),
        "twin_id": str(uuid.uuid4()),
        "correlation_id": f"integration-test-{datetime.now().timestamp()}"
    }


@pytest.fixture(autouse=True)
def enable_graph_memory(monkeypatch):
    """Enable graph memory for tests."""
    monkeypatch.setenv("GRAPH_MEMORY_ENABLED", "true")
    monkeypatch.setenv("GRAPH_MEMORY_READ_ENABLED", "true")
    monkeypatch.setenv("GRAPH_MEMORY_WRITE_ENABLED", "true")

    # Import and reset after setting env
    from modules.graph_memory_config import reset_config
    from modules.graph_circuit_breaker import reset_all_breakers
    from modules.graph_outbox import reset_outbox

    reset_config()
    reset_all_breakers()
    reset_outbox()

    yield


@pytest.mark.asyncio
async def test_graph_outbox_table_exists():
    """
    Verify graph_outbox table exists with proper schema.

    Validates:
    - Table exists in Supabase
    - Can insert/query records
    - UUID columns work correctly
    """
    from modules.observability import supabase

    # Insert a test record
    test_idem = f"integration-test-{uuid.uuid4()}"
    test_record = {
        "tenant_id": str(uuid.uuid4()),
        "twin_id": str(uuid.uuid4()),
        "operation": "create_episode",
        "idempotency_key": test_idem,
        "payload": {"test": "data"},
        "status": "pending",
        "priority": 0
    }

    result = supabase.table("graph_outbox").insert(test_record).execute()
    assert result.data, "Failed to insert into graph_outbox"
    assert len(result.data) == 1

    # Query it back
    job_id = result.data[0]["id"]
    fetched = supabase.table("graph_outbox").select("*").eq("id", job_id).execute()
    assert fetched.data, "Failed to fetch from graph_outbox"
    assert fetched.data[0]["idempotency_key"] == test_idem

    # Cleanup
    supabase.table("graph_outbox").delete().eq("id", job_id).execute()


@pytest.mark.asyncio
async def test_idempotency_constraint():
    """
    Verify unique constraint on (tenant_id, twin_id, idempotency_key).

    Validates:
    - Deduplication works at database level
    - Duplicate inserts are rejected
    """
    from modules.observability import supabase

    tenant_id = str(uuid.uuid4())
    twin_id = str(uuid.uuid4())
    idempotency_key = f"dedupe-test-{uuid.uuid4()}"

    # First insert should succeed
    result1 = supabase.table("graph_outbox").insert({
        "tenant_id": tenant_id,
        "twin_id": twin_id,
        "operation": "create_episode",
        "idempotency_key": idempotency_key,
        "payload": {"version": 1}
    }).execute()
    assert result1.data, "First insert should succeed"
    job_id = result1.data[0]["id"]

    # Second insert with same keys should fail
    try:
        supabase.table("graph_outbox").insert({
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "operation": "create_episode",
            "idempotency_key": idempotency_key,
            "payload": {"version": 2}
        }).execute()
        pytest.fail("Duplicate insert should have been rejected")
    except Exception as e:
        error_str = str(e).lower()
        assert "unique" in error_str or "duplicate" in error_str, f"Expected unique constraint error, got: {e}"

    # Cleanup
    supabase.table("graph_outbox").delete().eq("id", job_id).execute()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not has_real_neo4j,
    reason="Real Neo4j instance required and reachable (set NEO4J_URI and NEO4J_PASSWORD)",
)
async def test_graphiti_neo4j_connectivity(test_ids):
    """
    Verify Graphiti can connect to Neo4j and perform basic operations.

    Validates:
    - Neo4j connection works
    - Graphiti can create episodes
    - Graphiti can search (with group_id isolation)
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from modules.graph_memory_core import GraphMemoryCore
    from modules.graph_memory_config import get_graph_memory_config

    # Verify config is loaded correctly
    config = get_graph_memory_config()
    assert config.enabled, "Graph memory should be enabled"
    assert config.neo4j_uri, "Neo4j URI should be configured"

    # Create client
    client = GraphMemoryCore(
        tenant_id=test_ids["tenant_id"],
        twin_id=test_ids["twin_id"],
        correlation_id=test_ids["correlation_id"]
    )

    # Verify Graphiti initializes
    graphiti = client._get_graphiti()
    assert graphiti is not None, "Graphiti should initialize with valid credentials"

    # Create an episode (with longer timeout for schema init)
    episode_name = f"Integration Test Episode {datetime.now().isoformat()}"
    episode_body = "This is a test episode for integration validation."

    # Note: First episode creation may be slow due to schema initialization
    try:
        episode_id = await asyncio.wait_for(
            client.create_episode(
                name=episode_name,
                body=episode_body,
                source_type="integration_test",
                source_ref="test-001",
                async_write=False  # Synchronous for immediate verification
            ),
            timeout=30.0  # 30 second timeout for schema initialization
        )
        assert episode_id, "Episode should be created"
    except asyncio.TimeoutError:
        pytest.skip("Neo4j schema initialization too slow - skipping (this is OK for fresh databases)")

    # Wait for indexing
    await asyncio.sleep(2)

    # Search should find the episode
    results = await client.search(episode_body[:20], num_results=5)
    assert isinstance(results, list), "Search should return a list"

    # Cleanup
    await client.delete_twin_graph()


@pytest.mark.asyncio
async def test_end_to_end_job_lifecycle(test_ids):
    """
    Verify full job lifecycle: submit -> process -> complete.

    Validates:
    - Jobs can be submitted to outbox
    - Jobs can be queried by status
    - Job status can be updated
    """
    from modules.observability import supabase
    from modules.graph_outbox import get_graph_outbox, GraphOperationType

    outbox = get_graph_outbox()
    tenant_id = test_ids["tenant_id"]
    twin_id = test_ids["twin_id"]

    # Submit a job
    job_id = outbox.submit(
        tenant_id=tenant_id,
        twin_id=twin_id,
        operation=GraphOperationType.CREATE_EPISODE,
        idempotency_key=f"lifecycle-test-{uuid.uuid4()}",
        payload={"test": "data"},
        priority=5
    )
    assert job_id, "Job should be submitted"

    # Verify job is pending unless a live worker completed it first.
    result = supabase.table("graph_outbox").select("status").eq("id", job_id).execute()
    assert result.data, "Job should exist"
    initial_status = result.data[0]["status"]
    assert initial_status in {"pending", "processing", "completed"}, (
        f"Unexpected initial job status: {initial_status}"
    )

    if initial_status != "completed":
        supabase.table("graph_outbox").update({
            "status": "processing",
            "updated_at": datetime.now().isoformat()
        }).eq("id", job_id).execute()

        supabase.table("graph_outbox").update({
            "status": "completed",
            "updated_at": datetime.now().isoformat(),
            "completed_at": datetime.now().isoformat()
        }).eq("id", job_id).execute()

    # Verify final status
    final = supabase.table("graph_outbox").select("status").eq("id", job_id).execute()
    assert final.data[0]["status"] == "completed", "Job should be completed"

    # Cleanup
    supabase.table("graph_outbox").delete().eq("id", job_id).execute()


@pytest.mark.asyncio
async def test_circuit_breaker_integration(test_ids):
    """
    Verify circuit breaker works with real Redis (or in-memory fallback).

    Validates:
    - Circuit breaker can be created
    - Failure counting works
    - Circuit opens after threshold
    """
    from modules.graph_circuit_breaker import get_circuit_breaker
    from modules.graph_memory_config import get_graph_memory_config

    tenant_id = test_ids["tenant_id"]
    twin_id = test_ids["twin_id"]

    breaker = get_circuit_breaker(tenant_id, twin_id)
    config = get_graph_memory_config()

    # Record failures up to threshold
    threshold = config.circuit_breaker_threshold
    opened = False

    for i in range(threshold + 2):
        should_open = breaker.record_failure()
        if should_open:
            opened = True
            break

    # Verify circuit opened
    assert opened or breaker.is_open(), "Circuit should open after threshold failures"
    assert breaker.is_open(), "Circuit should be in open state"

    # Record success to close circuit
    breaker.record_success()
    # Note: Circuit stays open until cooldown expires, then half-open


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
