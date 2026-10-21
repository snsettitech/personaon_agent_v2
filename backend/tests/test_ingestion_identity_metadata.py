"""persist_source_label_metadata: a missing sources.metadata column is not an error."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError

import modules.ingestion_identity as ingestion_identity


def _api_error(code: str, message: str) -> APIError:
    return APIError({"code": code, "message": message, "hint": None, "details": None})


def _client_raising(exc: Exception) -> MagicMock:
    """Every .execute() raises ``exc`` (label columns and metadata both fail)."""
    m = MagicMock()
    for name in ("table", "select", "update", "eq", "single"):
        getattr(m, name).return_value = m
    m.execute.side_effect = exc
    return m


@pytest.fixture(autouse=True)
def _reset_once_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion_identity, "_metadata_column_missing_logged", False)


def _persist() -> None:
    ingestion_identity.persist_source_label_metadata(
        source_id="src-1", twin_id="twin-1", source_label="identity", identity_confirmed=True
    )


@pytest.mark.parametrize("code", ["42703", "PGRST204"])
def test_missing_column_logs_once_at_info_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: str
) -> None:
    exc = _api_error(code, "column sources.metadata does not exist")
    monkeypatch.setattr(ingestion_identity, "supabase", _client_raising(exc))
    caplog.set_level(logging.DEBUG, logger="modules.ingestion_identity")

    _persist()
    _persist()

    records = [r for r in caplog.records if "sources.metadata column missing" in r.getMessage()]
    assert [r.levelno for r in records] == [logging.INFO, logging.DEBUG]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert all(r.exc_info is None for r in records)


def test_other_errors_are_logged_with_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    exc = _api_error("08006", "connection failure")
    monkeypatch.setattr(ingestion_identity, "supabase", _client_raising(exc))
    caplog.set_level(logging.DEBUG, logger="modules.ingestion_identity")

    _persist()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "could not persist source label" in errors[0].getMessage()
    assert errors[0].exc_info is not None


def test_label_columns_success_skips_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    for name in ("table", "update", "eq"):
        getattr(client, name).return_value = client
    monkeypatch.setattr(ingestion_identity, "supabase", client)

    _persist()

    client.update.assert_called_once_with(
        {"source_label": "identity", "identity_label_confirmed": True}
    )
    client.select.assert_not_called()
