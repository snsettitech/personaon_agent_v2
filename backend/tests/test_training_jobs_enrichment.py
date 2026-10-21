"""Tests for profile_enrichment job handler."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _job_data(job_id: str = "job-1", source_id: str = "src-1", twin_id: str = "twin-1") -> dict:
    return {
        "id": job_id,
        "source_id": source_id,
        "twin_id": twin_id,
        "job_type": "ingestion",
        "status": "pending",
        "metadata": {
            "enrichment_type": "profile_enrichment",
            "name": "Alice Smith",
            "context": "CEO at Acme",
            "linkedin_url": "https://www.linkedin.com/in/alicesmith",
            "linkedin_snapshot": {},
            "tenant_id": "tenant_abc",
        },
        "provider": None,
    }


def _source_data(source_id: str = "src-1", twin_id: str = "twin-1") -> dict:
    return {
        "id": source_id,
        "twin_id": twin_id,
        "filename": "Profile Enrichment",
        "content_text": "",
        "citation_url": None,
    }


def _active_outcome() -> dict:
    return {
        "state": "active",
        "db_status": "active",
        "chunk_count": 3,
        "vector_indexed": True,
        "publishable": True,
        "failure_reason": None,
    }


def _needs_input_outcome(reason: str = "empty_profile_text") -> dict:
    return {
        "state": "needs_input",
        "db_status": "claims_ready",
        "chunk_count": 0,
        "vector_indexed": False,
        "publishable": False,
        "failure_reason": reason,
    }


def _wire_training_job_selects(mock_sb: MagicMock, rows: list[dict]) -> None:
    idx = 0

    def side_effect():
        nonlocal idx
        result = MagicMock(data=rows[idx])
        idx += 1
        return result

    (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.side_effect
    ) = side_effect


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, db: "_FakeSupabase", table_name: str):
        self.db = db
        self.table_name = table_name
        self.operation = "select"
        self.payload = None

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        if self.operation == "select" and self.table_name == "twins":
            return _FakeResult({"settings": {"widget_settings": {"public_share_enabled": False}}})
        if self.operation == "update":
            self.db.updates.append((self.table_name, self.payload))
        if self.operation == "insert":
            self.db.inserts.append((self.table_name, self.payload))
        return _FakeResult({})


class _FakeSupabase:
    def __init__(self):
        self.updates: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, dict]] = []

    def table(self, table_name: str):
        return _FakeQuery(self, table_name)


@pytest.mark.asyncio
async def test_run_extraction_vector_failure_returns_non_publishable_and_claims_ready():
    """Vector failures must not leave the twin active/publishable."""
    fake_sb = _FakeSupabase()
    profile = {
        "name": "Alice Smith",
        "occupation": "CEO",
        "short_description": "Experienced operator.",
        "areas_of_expertise": ["strategy"],
    }

    with patch("routers.auto_create.get_supabase_client", return_value=fake_sb), \
         patch("routers.auto_create.extract_profile", return_value=profile), \
         patch("routers.auto_create.is_profile_rich", return_value=True), \
         patch("routers.auto_create.profile_to_text", return_value="Alice Smith is a CEO."), \
         patch("routers.auto_create._generate_suggested_questions", return_value=[]), \
         patch("routers.auto_create.upsert_text_chunks", new_callable=AsyncMock) as mock_upsert:
        mock_upsert.side_effect = RuntimeError("pinecone unavailable")

        from routers.auto_create import _run_extraction

        outcome = await _run_extraction(
            twin_id="twin-1",
            name="Alice Smith",
            context="CEO at Acme",
            linkedin_url=None,
            linkedin_snapshot=None,
            tenant_id="tenant_abc",
        )

    assert outcome["publishable"] is False
    assert outcome["state"] == "needs_input"
    assert outcome["db_status"] == "claims_ready"
    assert outcome["vector_indexed"] is False
    assert outcome["failure_reason"] == "vector_upsert_failed"
    final_twin_update = [payload for table, payload in fake_sb.updates if table == "twins"][-1]
    assert final_twin_update["status"] == "claims_ready"


@pytest.mark.asyncio
async def test_profile_enrichment_job_runs_extraction():
    """profile_enrichment job metadata must route to _run_extraction handler."""
    job_data = _job_data()
    source_data = _source_data()
    twin_settings_data = {
        "status": "active",
        "settings": {"enrichment_status": "pending", "widget_settings": {"public_share_enabled": False}},
    }

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(mock_sb, [job_data, source_data, twin_settings_data])
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-1")

    assert result is True
    mock_extract.assert_called_once()
    call_kwargs = mock_extract.call_args.kwargs
    assert call_kwargs["twin_id"] == "twin-1"
    assert call_kwargs["name"] == "Alice Smith"


@pytest.mark.asyncio
async def test_profile_enrichment_flips_public_share_enabled_after_publishable_completion():
    """After publishable enrichment, public_share_enabled flips to True."""
    updated_settings = {}

    def capture_update(data):
        if "settings" in data:
            updated_settings.update(data["settings"])
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock()
        return m

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-2", "src-2", "twin-2"),
                _source_data("src-2", "twin-2"),
                {"status": "active", "settings": {"enrichment_status": "pending", "widget_settings": {"public_share_enabled": False}}},
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-2")

    assert result is True
    assert updated_settings.get("enrichment_status") == "completed"
    widget = updated_settings.get("widget_settings", {})
    assert widget.get("public_share_enabled") is True


@pytest.mark.asyncio
async def test_profile_enrichment_needs_input_does_not_publish_or_retry():
    """Non-transient needs_input finishes the job but keeps public sharing disabled."""
    updated_settings = {}

    def capture_update(data):
        if "settings" in data:
            updated_settings.update(data["settings"])
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock()
        return m

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status") as mock_update_status, \
         patch("modules.training_jobs._update_source_row") as mock_update_source, \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-3", "src-3", "twin-3"),
                _source_data("src-3", "twin-3"),
                {"status": "claims_ready", "settings": {"enrichment_status": "pending", "widget_settings": {"public_share_enabled": False}}},
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _needs_input_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-3")

    assert result is True
    mock_update_source.assert_called_with(
        "src-3",
        {"status": "failed", "last_step": "needs_input", "health_status": "unhealthy"},
    )
    mock_update_status.assert_any_call(
        "job-3",
        "complete",
        metadata={"enrichment_type": "profile_enrichment", "reason": "empty_profile_text"},
    )
    assert updated_settings.get("enrichment_status") == "needs_input"
    assert updated_settings.get("widget_settings", {}).get("public_share_enabled") is False


@pytest.mark.asyncio
async def test_profile_enrichment_vector_failure_fails_closed_for_retry():
    """Vector failures should fail the job for retry/backoff and never publish."""
    updated_settings = {}

    def capture_update(data):
        if "settings" in data:
            updated_settings.update(data["settings"])
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock()
        return m

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status") as mock_update_status, \
         patch("modules.training_jobs._update_source_row") as mock_update_source, \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-4", "src-4", "twin-4"),
                _source_data("src-4", "twin-4"),
                {"status": "claims_ready", "settings": {"enrichment_status": "pending", "widget_settings": {"public_share_enabled": False}}},
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _needs_input_outcome("vector_upsert_failed")

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-4")

    assert result is False
    mock_update_source.assert_called_with(
        "src-4",
        {"status": "failed", "last_step": "extraction_failed", "health_status": "unhealthy"},
    )
    mock_update_status.assert_any_call(
        "job-4",
        "failed",
        metadata={"enrichment_type": "profile_enrichment", "reason": "vector_upsert_failed"},
    )
    assert updated_settings.get("enrichment_status") == "needs_input"
    assert updated_settings.get("widget_settings", {}).get("public_share_enabled") is False


def _cas_update_side_effect(updated_settings: dict, *, cas_matches: bool):
    """Mock supabase.table('twins').update(...) covering both chains the CAS
    write can take: update().eq().execute() (already_notified branch, and the
    "lost race" follow-up write) and update().eq().is_().execute() (the
    conditional analytics-flag write). `cas_matches` controls whether the
    .is_() filter "matches" (True -> non-empty .data, this call won the race).
    """

    def side_effect(data):
        if "settings" in data:
            updated_settings.update(data["settings"])
        m = MagicMock()
        m.eq.return_value.execute.return_value = MagicMock(data=[{"id": "twin"}])
        m.eq.return_value.is_.return_value.execute.return_value = MagicMock(
            data=[{"id": "twin"}] if cas_matches else [],
        )
        return m

    return side_effect


@pytest.mark.asyncio
async def test_profile_enrichment_fires_onboarding_extraction_complete_on_first_completion():
    """First-ever publishable completion notifies PostHog with the twin owner's distinct_id."""
    updated_settings = {}
    capture_update = _cas_update_side_effect(updated_settings, cas_matches=True)

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("modules.training_jobs.ph_capture") as mock_ph_capture, \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-5", "src-5", "twin-5"),
                _source_data("src-5", "twin-5"),
                {
                    "status": "active",
                    "settings": {
                        "enrichment_status": "pending",
                        "widget_settings": {"public_share_enabled": False},
                        "owner_user_id": "user-abc-123",
                    },
                },
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-5")

    assert result is True
    mock_ph_capture.assert_called_once()
    call_kwargs = mock_ph_capture.call_args.kwargs
    assert call_kwargs["user_id"] == "user-abc-123"
    assert call_kwargs["event"] == "onboarding_extraction_complete"
    assert call_kwargs["properties"]["twin_id"] == "twin-5"
    assert call_kwargs["properties"]["chunk_count"] == 3
    assert call_kwargs["properties"]["vector_indexed"] is True
    assert updated_settings.get("analytics_extraction_complete_sent") is True


@pytest.mark.asyncio
async def test_profile_enrichment_skips_ph_capture_when_already_notified():
    """Re-enrichment (POST /v2/enrich/{twin_id}/profile) must not double-fire the funnel event.

    enrich.py resets enrichment_status to "queued" before re-enqueuing, so that field can't
    signal "already notified" — only the dedicated analytics_extraction_complete_sent flag can.
    """
    updated_settings = {}
    capture_update = _cas_update_side_effect(updated_settings, cas_matches=True)

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("modules.training_jobs.ph_capture") as mock_ph_capture, \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-6", "src-6", "twin-6"),
                _source_data("src-6", "twin-6"),
                {
                    "status": "active",
                    "settings": {
                        # Simulates a re-enrichment: enrichment_status was reset to
                        # "queued" by enrich.py, but the notified flag survived
                        # (enrich.py only overwrites enrichment_status/persona_quality).
                        "enrichment_status": "queued",
                        "widget_settings": {"public_share_enabled": False},
                        "owner_user_id": "user-abc-123",
                        "analytics_extraction_complete_sent": True,
                    },
                },
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-6")

    assert result is True
    mock_ph_capture.assert_not_called()
    # enrichment_status still flips back to completed even though we skip the analytics fire.
    assert updated_settings.get("enrichment_status") == "completed"


@pytest.mark.asyncio
async def test_profile_enrichment_skips_ph_capture_when_owner_user_id_missing():
    """No owner_user_id (e.g. a legacy/unclaimed twin) must skip analytics, not guess or error."""
    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("modules.training_jobs.ph_capture") as mock_ph_capture, \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-7", "src-7", "twin-7"),
                _source_data("src-7", "twin-7"),
                {
                    "status": "active",
                    "settings": {"enrichment_status": "pending", "widget_settings": {"public_share_enabled": False}},
                },
            ],
        )
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-7")

    assert result is True
    mock_ph_capture.assert_not_called()


@pytest.mark.asyncio
async def test_profile_enrichment_skips_ph_capture_when_concurrent_run_wins_race():
    """Two profile_enrichment jobs for the same twin (e.g. onboarding's initial
    enqueue racing a user-triggered re-enrich before the first job finishes)
    both read analytics_extraction_complete_sent unset. The compare-and-swap
    UPDATE (.is_("settings->>analytics_extraction_complete_sent", "null"))
    means only the winner's write actually matches a row; this run's write
    loses (simulated by cas_matches=False), so it must NOT fire ph_capture
    even though its own pre-write read of already_notified was False.
    """
    updated_settings = {}
    capture_update = _cas_update_side_effect(updated_settings, cas_matches=False)

    with patch("modules.training_jobs.supabase") as mock_sb, \
         patch("modules.training_jobs.update_job_status"), \
         patch("modules.training_jobs._update_source_row"), \
         patch("modules.training_jobs._schedule_metrics_update"), \
         patch("modules.training_jobs.ph_capture") as mock_ph_capture, \
         patch("routers.auto_create._run_extraction", new_callable=AsyncMock) as mock_extract:
        _wire_training_job_selects(
            mock_sb,
            [
                _job_data("job-8", "src-8", "twin-8"),
                _source_data("src-8", "twin-8"),
                {
                    "status": "active",
                    "settings": {
                        "enrichment_status": "pending",
                        "widget_settings": {"public_share_enabled": False},
                        "owner_user_id": "user-abc-123",
                        # Not set yet from THIS run's point of view — a
                        # concurrent run wins the CAS write before this one.
                    },
                },
            ],
        )
        mock_sb.table.return_value.update.side_effect = capture_update
        mock_extract.return_value = _active_outcome()

        from modules.training_jobs import process_training_job

        result = await process_training_job("job-8")

    assert result is True
    mock_ph_capture.assert_not_called()
    # The losing run still applies its own enrichment_status/widget_settings
    # via the non-CAS follow-up write.
    assert updated_settings.get("enrichment_status") == "completed"
    assert updated_settings.get("widget_settings", {}).get("public_share_enabled") is True
