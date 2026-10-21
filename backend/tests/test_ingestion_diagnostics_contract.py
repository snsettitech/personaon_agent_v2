

def test_diagnostics_schema_status_caches_missing(monkeypatch):
    # Import inside test so module globals start clean per test session.
    from modules import ingestion_diagnostics as diag

    # We use a lightweight mock that always fails on execute to simulate missing columns/table.
    class _Q:
        def select(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, *_a, **_k):  # noqa: ANN001
            return self

        def execute(self):  # noqa: ANN001
            raise Exception("column sources.last_provider does not exist")

    class _SB:
        def __init__(self):
            self.calls = 0

        def table(self, _name):  # noqa: ANN001
            self.calls += 1
            return _Q()

    sb = _SB()
    monkeypatch.setattr(diag, "supabase", sb)

    ok1, err1 = diag.diagnostics_schema_status(force_refresh=True)
    assert ok1 is False
    assert err1 is not None
    assert sb.calls >= 1

    calls_after_first = sb.calls
    ok2, err2 = diag.diagnostics_schema_status()
    assert ok2 is False
    assert err2 == err1
    assert sb.calls == calls_after_first  # cached


def test_start_step_degrades_to_logs_when_schema_missing(monkeypatch):
    from modules import ingestion_diagnostics as diag

    # Force schema unavailable without hitting Supabase schema checks.
    monkeypatch.setattr(diag, "diagnostics_schema_status", lambda force_refresh=False: (False, "missing"))

    sources_table = type(
        "T",
        (),
        {
            "update": lambda self, _d: self,  # noqa: ANN001
            "eq": lambda self, *_a, **_k: self,  # noqa: ANN001
            "execute": lambda self: type("R", (), {"data": []})(),  # noqa: ANN001
        },
    )()

    class _SB:
        def table(self, name):  # noqa: ANN001
            assert name == "sources"
            return sources_table

    monkeypatch.setattr(diag, "supabase", _SB())

    calls = {"logs": 0}

    def _log_ingestion_event(*_a, **_k):  # noqa: ANN001
        calls["logs"] += 1

    import modules.observability as obs

    monkeypatch.setattr(obs, "log_ingestion_event", _log_ingestion_event)

    event_id = diag.start_step(
        source_id="00000000-0000-0000-0000-000000000000",
        twin_id="00000000-0000-0000-0000-000000000000",
        provider="youtube",
        step="queued",
        correlation_id="test",
        message="queued",
        metadata={"x": 1},
    )
    assert event_id == ""
    assert calls["logs"] == 1


def test_finish_step_degrades_to_logs_when_schema_missing(monkeypatch):
    from modules import ingestion_diagnostics as diag

    monkeypatch.setattr(diag, "diagnostics_schema_status", lambda force_refresh=False: (False, "missing"))

    sources_table = type(
        "T",
        (),
        {
            "update": lambda self, _d: self,  # noqa: ANN001
            "eq": lambda self, *_a, **_k: self,  # noqa: ANN001
            "execute": lambda self: type("R", (), {"data": []})(),  # noqa: ANN001
        },
    )()

    class _SB:
        def table(self, name):  # noqa: ANN001
            assert name == "sources"
            return sources_table

    monkeypatch.setattr(diag, "supabase", _SB())

    calls = {"levels": []}

    def _log_ingestion_event(_source_id, _twin_id, level, _message, metadata=None):  # noqa: ANN001
        calls["levels"].append(level)

    import modules.observability as obs

    monkeypatch.setattr(obs, "log_ingestion_event", _log_ingestion_event)

    diag.finish_step(
        event_id="",
        source_id="00000000-0000-0000-0000-000000000000",
        twin_id="00000000-0000-0000-0000-000000000000",
        provider="linkedin",
        step="fetching",
        status="error",
        correlation_id="test",
        message="fail",
        metadata={},
        error={"code": "X", "message": "Y"},
    )

    assert "error" in calls["levels"]


def test_ingestion_insert_source_row_does_not_require_diagnostics_columns(monkeypatch):
    import routers.ingestion as ingest_router

    inserted = {}

    class _T:
        def insert(self, payload):  # noqa: ANN001
            inserted.update(payload)
            return self

        def execute(self):  # noqa: ANN001
            return type("R", (), {"data": []})()

    class _SB:
        def table(self, name):  # noqa: ANN001
            assert name == "sources"
            return _T()

    monkeypatch.setattr(ingest_router, "supabase", _SB())

    ingest_router._insert_source_row(
        source_id="00000000-0000-0000-0000-000000000000",
        twin_id="00000000-0000-0000-0000-000000000000",
        provider="youtube",
        filename="YouTube: queued",
        citation_url="https://www.youtube.com/watch?v=HiC1J8a9V1I",
    )

    assert "last_provider" not in inserted
    assert "last_step" not in inserted
