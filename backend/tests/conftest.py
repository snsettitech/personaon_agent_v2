# backend/tests/conftest.py
"""Pytest configuration for backend tests.

Adds the backend directory to Python path so tests can import modules.
Registers custom pytest markers.
"""

import sys
import os
import pytest
from types import SimpleNamespace

# Add backend directory to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Ensure feature flags and dev mode are consistent for tests
os.environ.setdefault("ENABLE_ENHANCED_INGESTION", "true")
os.environ.setdefault("DEV_MODE", "false")
os.environ.setdefault("DEEP_RESEARCH_ENABLED", "true")
# Meeting intelligence routes are gated by this flag and routers/meetings.py
# evaluates it at module-import time. Set it BEFORE any test module imports
# routers.* (including transitive imports via routers/__init__.py) so the
# GET /v2/meetings/* endpoints stay routable across the whole test session.
os.environ.setdefault("MEETING_INTELLIGENCE_ENABLED", "true")

# main.py refuses to import without these (_check_required_env). Unit tests must
# never need real credentials, so fall back to inert placeholders. Real values
# from the environment (e.g. the opt-in SMOKE suite) still win.
for _key, _value in {
    "SUPABASE_URL": "http://127.0.0.1:9",
    "SUPABASE_SERVICE_KEY": "test-service-key",
    "GOOGLE_API_KEY": "test-google-key",
    "JWT_SECRET": "test-jwt-secret-not-real-0123456789abcdef",
    "STRIPE_SECRET_KEY": "sk_test_placeholder",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_placeholder",
}.items():
    os.environ.setdefault(_key, _value)

# Unit tests must never ship analytics. With a POSTHOG_API_KEY set, the real
# SDK's consumer thread uploads in the background and _network_guard fails
# whichever test happens to be running at that moment. (The repeated-lifespan
# shutdown deadlock this once also hid, #330, is fixed in posthog_analytics
# and covered by tests/test_posthog_analytics.py.)
os.environ.pop("POSTHOG_API_KEY", None)
os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
# The ADK session store defaults to sqlite file backend/adk_sessions.db, which is
# tracked in git; keep test sessions in memory so runs don't dirty the checkout.
os.environ.setdefault("ADK_SESSION_DB_URL", "sqlite+aiosqlite:///:memory:")

from tests import _network_guard  # noqa: E402  (backend/ is on sys.path above)

_network_guard.install()

# Ensure langfuse decorator doesn't break FastAPI signatures in tests
def _noop_observe(*args, **kwargs):
    def decorator(func):
        return func
    return decorator

sys.modules.setdefault("langfuse", SimpleNamespace(observe=_noop_observe, get_client=lambda: None))

_STRICT_GATE_ENABLED = os.getenv("REGRESSION_GATE_STRICT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_STRICT_GATE_REQUIRED_FILES: set[str] = {
    "test_founder_clarifier_replay_e2e.py",
    "test_e2e_loop_replay.py",
    "test_e2e_action_lane_replay.py",
    "test_public_action_query_is_disabled.py",
}
_strict_gate_seen_files: set[str] = set()
_strict_gate_failed_nodeids: list[str] = []


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "network: mark test as requiring network access (skipped in CI)"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test requiring external services"
    )
    config.addinivalue_line(
        "markers",
        "smoke: end-to-end pipeline test against real staging services — opt-in via SMOKE=1",
    )


def pytest_collection_modifyitems(session, config, items):
    if not _network_guard.network_allowed():
        skip_live = pytest.mark.skip(
            reason="needs live services; set RUN_NETWORK_TESTS=1 to run"
        )
        for item in items:
            if "network" in item.keywords or "integration" in item.keywords:
                item.add_marker(skip_live)
    if not _STRICT_GATE_ENABLED:
        return
    collected_files = {os.path.basename(str(item.fspath)) for item in items}
    missing = sorted(_STRICT_GATE_REQUIRED_FILES - collected_files)
    if missing:
        raise pytest.UsageError(
            "REGRESSION_GATE_STRICT=true requires replay suites to be collected. Missing: "
            + ", ".join(missing)
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _network_guard.set_current_test(item.nodeid)
    yield
    _network_guard.set_current_test("<between tests>")


def _fail_on_network_attempt(item, report) -> None:
    """Fail a test that tried to reach an external host, even if the code
    under test swallowed the ExternalNetworkBlocked error."""
    hosts = _network_guard.take_attempts(item.nodeid)
    if not hosts or report.failed:
        return
    report.outcome = "failed"
    report.longrepr = (
        f"external network attempt during {report.when}: {', '.join(sorted(set(hosts)))}\n"
        "Mock the client, or mark the test @pytest.mark.network if it really needs the network."
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    # Whatever is left was not attributable to a test (import/collection time).
    attempts = _network_guard.blocked_attempts()
    if not attempts:
        return
    terminalreporter.write_sep("=", "blocked external network attempts outside tests")
    for nodeid, host in sorted(set(attempts)):
        terminalreporter.write_line(f"{nodeid} -> {host}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    _fail_on_network_attempt(item, report)
    if not _STRICT_GATE_ENABLED:
        return
    if report.when != "call":
        return
    filename = os.path.basename(str(item.fspath))
    if filename not in _STRICT_GATE_REQUIRED_FILES:
        return
    _strict_gate_seen_files.add(filename)
    if report.failed:
        _strict_gate_failed_nodeids.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    _ = exitstatus
    if not _STRICT_GATE_ENABLED:
        return

    missing_runs = sorted(_STRICT_GATE_REQUIRED_FILES - _strict_gate_seen_files)
    if missing_runs or _strict_gate_failed_nodeids:
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal:
            terminal.write_sep("=", "REGRESSION_GATE_STRICT FAILED")
            if missing_runs:
                terminal.write_line(
                    "Required replay suites did not run: " + ", ".join(missing_runs)
                )
            if _strict_gate_failed_nodeids:
                terminal.write_line(
                    "Replay failures: " + ", ".join(_strict_gate_failed_nodeids)
                )
        session.exitstatus = 1


# =============================================================================
# pgvector Test Fixtures
# =============================================================================

from unittest.mock import AsyncMock


@pytest.fixture(autouse=True)
def _gcs_unavailable(monkeypatch):
    """GCS is always external. google-api-core treats a refused connection as
    transient and retries for up to 120s inside worker threads, which outlives
    the per-test timeout. Fail fast instead; tests that need an upload result
    stub modules.gcs_storage themselves (their fixtures run after this one)."""

    def _no_gcs():
        raise ConnectionRefusedError("GCS is not available in unit tests")

    monkeypatch.setattr("modules.gcs_storage._get_gcs_client", _no_gcs)


@pytest.fixture
def client():
    """FastAPI test client for billing and other endpoint tests."""
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


@pytest.fixture
def mock_pgvector_pool():
    """Mock asyncpg pool for vector_store tests.

    Returns (pool, conn) tuple where pool.acquire() context manager yields conn.
    """
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


# =============================================================================
# Graph Memory Test Fixtures
# =============================================================================

class MockGraphOutbox:
    """Mock outbox for testing without database."""

    def __init__(self):
        self._jobs = {}
        self._idempotency = {}

    def submit(
        self,
        tenant_id,
        twin_id,
        operation,
        idempotency_key,
        payload,
        priority=0,
        correlation_id=None,
        scope_id=None,
        creator_id=None,
        next_attempt_after=None,
    ):
        """Mock submit that stores in memory."""
        import uuid
        import time

        # Scope-isolated idempotency (matches production behavior)
        dedupe_key = f"{scope_id or twin_id}:{idempotency_key}"
        if dedupe_key in self._idempotency:
            return self._idempotency[dedupe_key]

        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "scope_id": scope_id,
            "creator_id": creator_id,
            "operation": operation.value if hasattr(operation, 'value') else str(operation),
            "idempotency_key": idempotency_key,
            "payload": payload,
            "status": "pending",
            "priority": priority,
            "attempt_count": 0,
            "correlation_id": correlation_id,
            "next_attempt_after": next_attempt_after.isoformat() if hasattr(next_attempt_after, "isoformat") else next_attempt_after,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        self._jobs[job_id] = job
        self._idempotency[dedupe_key] = job_id
        return job_id

    def get_depth(self, scope_id=None) -> int:
        """Get pending job count."""
        return sum(
            1
            for j in self._jobs.values()
            if j.get("status") == "pending" and (scope_id is None or j.get("scope_id") == scope_id)
        )

    def get_stats(self, scope_id=None):
        """Get job statistics."""
        stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for job in self._jobs.values():
            if scope_id is not None and job.get("scope_id") != scope_id:
                continue
            status = job.get("status", "pending")
            if status in stats:
                stats[status] += 1
        return stats

    def get_pending_jobs(self, limit=100, scope_id=None):
        """Get pending jobs."""
        return [
            j
            for j in self._jobs.values()
            if j.get("status") == "pending" and (scope_id is None or j.get("scope_id") == scope_id)
        ][:limit]

    def clear(self):
        """Clear all jobs."""
        self._jobs.clear()
        self._idempotency.clear()


@pytest.fixture(scope="function")
def mock_graph_outbox_table(monkeypatch):
    """
    Mock the graph_outbox table for tests that don't need real database.
    Returns a mock outbox that stores jobs in memory.
    """
    import modules.graph_outbox as outbox_module

    # Create mock instance
    mock_outbox = MockGraphOutbox()

    # Replace the singleton getter
    monkeypatch.setattr(outbox_module, "_outbox_instance", mock_outbox)
    monkeypatch.setattr(outbox_module, "get_graph_outbox", lambda: mock_outbox)

    yield mock_outbox._jobs

    # Cleanup
    mock_outbox.clear()
    outbox_module.reset_outbox()


@pytest.fixture(scope="function")
def mock_graphiti_client(monkeypatch):
    """
    Mock Graphiti client for tests that don't need real Neo4j.
    Returns a mock client with configurable behavior.
    """
    import uuid

    class MockGraphiti:
        def __init__(self, **kwargs):
            self._episodes = {}
            self._initialized = True
            self.init_kwargs = kwargs

        def add_episode(self, name, episode_body, source_description, **kwargs):
            episode_id = str(uuid.uuid4())
            self._episodes[episode_id] = {
                "uuid": episode_id,
                "name": name,
                "body": episode_body,
                "source": source_description
            }
            return {"uuid": episode_id}

        def search(self, query, num_results=10):
            # Return empty list by default, tests can override
            return []

        def delete_by_group_id(self, group_id):
            deleted = 0
            to_delete = [k for k, v in self._episodes.items() if v.get("group_id") == group_id]
            for k in to_delete:
                del self._episodes[k]
                deleted += 1
            return deleted

    import modules.graph_memory_core as core_module

    def mock_get_graphiti(self):
        if not hasattr(self, '_mock_graphiti'):
            self._mock_graphiti = MockGraphiti()
        return self._mock_graphiti

    monkeypatch.setattr(core_module.GraphMemoryCore, "_get_graphiti", mock_get_graphiti)

    yield MockGraphiti


@pytest.fixture(scope="function")
def enable_graph_memory(monkeypatch):
    """Enable graph memory for tests."""
    monkeypatch.setenv("GRAPH_MEMORY_ENABLED", "true")
    monkeypatch.setenv("GRAPH_MEMORY_READ_ENABLED", "true")
    monkeypatch.setenv("GRAPH_MEMORY_WRITE_ENABLED", "true")
    monkeypatch.setenv("NEO4J_URI", "bolt://mock:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "mock-password")

    from modules.graph_memory_config import reset_config
    reset_config()

    yield

    # Cleanup
    reset_config()
