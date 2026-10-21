"""Duplicate uploads of an identity (resume) file still propose Passport claims.

Regression for the content-hash early return in POST /ingest/file/{twin_id}:
a resume first uploaded as knowledge, then re-uploaded as "my resume", used to
return the existing source before resume claim import ran (PON-8).

No network: Supabase is an in-memory fake and the Gemini extractor is stubbed.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.datastructures import Headers, UploadFile

import modules.ingestion_identity as ingestion_identity
import routers.ingestion as ingestion

TWIN_ID = "twin-1"
TENANT_ID = "tenant-1"
USER = {"user_id": "user-1", "tenant_id": TENANT_ID}
RESUME_TEXT = "Ada Lovelace\nAnalytical Engine Programmer\nSkills: Mathematics, Python"
EXTRACTION = {
    "full_name": "Ada Lovelace",
    "headline": "Analytical Engine Programmer",
    "areas_of_expertise": ["Mathematics", "Python"],
}


class _Query:
    """Minimal fluent Supabase query over an in-memory table."""

    def __init__(self, db: _FakeSupabase, table: str) -> None:
        self._db = db
        self._table = table
        self._filters: list[tuple[str, Any]] = []
        self._op = "select"
        self._payload: dict | None = None
        self._single = False

    def select(self, *_args: Any, **_kwargs: Any) -> _Query:
        return self

    def eq(self, column: str, value: Any) -> _Query:
        self._filters.append((column, value))
        return self

    def single(self) -> _Query:
        self._single = True
        return self

    def insert(self, payload: dict) -> _Query:
        self._op, self._payload = "insert", dict(payload)
        return self

    def update(self, payload: dict) -> _Query:
        self._op, self._payload = "update", dict(payload)
        return self

    def _matches(self, row: dict) -> bool:
        return all(row.get(col) == val for col, val in self._filters)

    def execute(self) -> SimpleNamespace:
        rows = self._db.tables.setdefault(self._table, [])
        if self._op == "insert":
            assert self._payload is not None
            fingerprint = self._payload.get("fingerprint")
            if self._table == "profile_claims" and any(
                r.get("fingerprint") == fingerprint for r in rows
            ):
                raise Exception(
                    'duplicate key value violates unique constraint "idx_pclaim_fingerprint_active"'
                )
            row = {"id": f"{self._table}-{len(rows) + 1}", **self._payload}
            rows.append(row)
            return SimpleNamespace(data=[row])
        if self._op == "update":
            assert self._payload is not None
            for row in rows:
                if self._matches(row):
                    row.update(self._payload)
            return SimpleNamespace(data=[r for r in rows if self._matches(r)])
        matched = [dict(r) for r in rows if self._matches(r)]
        if self._single:
            return SimpleNamespace(data=matched[0] if matched else None)
        return SimpleNamespace(data=matched)


class _FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {
            "twins": [{"id": TWIN_ID, "tenant_id": TENANT_ID, "settings": {}}],
        }

    def table(self, name: str) -> _Query:
        return _Query(self, name)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> SimpleNamespace:
    monkeypatch.chdir(tmp_path)  # endpoint writes temp_uploads/ in cwd
    fake = _FakeSupabase()
    gemini_calls: list[str] = []

    def _fake_gemini(text: str) -> dict:
        gemini_calls.append(text)
        return EXTRACTION

    async def _fake_upsert(**_kwargs: Any) -> int:
        return 1

    monkeypatch.setattr(ingestion, "supabase", fake)
    monkeypatch.setattr(ingestion_identity, "supabase", fake)
    monkeypatch.setattr(ingestion, "verify_twin_ownership", lambda *_a, **_k: None)
    monkeypatch.setattr(ingestion, "log_ingestion_event", lambda *_a, **_k: None)
    monkeypatch.setattr(ingestion, "start_step", lambda **_k: "ev-1")
    monkeypatch.setattr(ingestion, "finish_step", lambda **_k: None)
    monkeypatch.setattr(
        ingestion, "run_all_health_checks", lambda *_a, **_k: {"overall_status": "healthy"}
    )
    monkeypatch.setattr(
        "adk_core.services.vector_store.upsert_text_chunks", _fake_upsert
    )
    monkeypatch.setattr(
        "modules.gcs_storage.upload_file_bytes", lambda **_k: "gs://test/resume.txt"
    )
    monkeypatch.setattr(
        "modules.passport_resume_import.extract_resume_fields_with_gemini", _fake_gemini
    )
    monkeypatch.setattr(
        "modules.passport_resume_import.ensure_professional_profile",
        lambda **_k: "prof-1",
    )
    return SimpleNamespace(db=fake, gemini_calls=gemini_calls)


async def _upload(label: str) -> dict:
    upload = UploadFile(
        file=io.BytesIO(RESUME_TEXT.encode("utf-8")),
        filename="resume.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    return await ingestion.ingest_file_endpoint(
        twin_id=TWIN_ID,
        file=upload,
        source_label=label,
        identity_confirmed=label == "identity",
        http_req=None,
        user=USER,
    )


def _claims(db: _FakeSupabase) -> list[dict]:
    return db.tables.get("profile_claims", [])


@pytest.mark.asyncio
async def test_knowledge_then_identity_proposes_claims(env: SimpleNamespace) -> None:
    first = await _upload("knowledge")
    assert first["duplicate"] is False
    assert "proposed_count" not in first
    assert _claims(env.db) == []

    second = await _upload("identity")

    assert second["duplicate"] is True
    assert second["source_id"] == first["source_id"]
    assert second["proposed_count"] == 4
    claims = _claims(env.db)
    assert len(claims) == 4
    assert {c["state"] for c in claims} == {"proposed"}
    evidence = env.db.tables["claim_evidence"]
    assert {e["source_id"] for e in evidence} == {first["source_id"]}
    # Stored source text is what gets parsed, and the label is upgraded.
    assert env.gemini_calls == [RESUME_TEXT]
    source = env.db.tables["sources"][0]
    assert source["source_label"] == "identity"
    assert source["identity_label_confirmed"] is True


@pytest.mark.asyncio
async def test_identity_twice_creates_no_duplicate_claims(env: SimpleNamespace) -> None:
    first = await _upload("identity")
    assert first["duplicate"] is False
    assert first["proposed_count"] == 4

    second = await _upload("identity")

    assert second["duplicate"] is True
    assert second["proposed_count"] == 0
    assert len(_claims(env.db)) == 4
    assert len(env.db.tables["claim_evidence"]) == 4


@pytest.mark.asyncio
async def test_knowledge_duplicate_unchanged(env: SimpleNamespace) -> None:
    first = await _upload("knowledge")
    second = await _upload("knowledge")

    assert second == {
        "source_id": first["source_id"],
        "job_id": None,
        "status": "live",
        "duplicate": True,
        "message": "This file has already been uploaded. Returning existing source.",
    }
    assert env.gemini_calls == []
    assert _claims(env.db) == []
    assert env.db.tables["sources"][0]["source_label"] == "knowledge"


@pytest.mark.asyncio
async def test_duplicate_identity_survives_extractor_failure(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _upload("knowledge")

    def _boom(_text: str) -> dict:
        raise RuntimeError("gemini down")

    monkeypatch.setattr(
        "modules.passport_resume_import.extract_resume_fields_with_gemini", _boom
    )
    second = await _upload("identity")

    assert second["duplicate"] is True
    assert second["proposed_count"] == 0
    assert _claims(env.db) == []


def test_label_persist_is_scoped_to_twin(env: SimpleNamespace) -> None:
    env.db.tables["sources"] = [{"id": "src-x", "twin_id": "other-twin", "source_label": "knowledge"}]

    ingestion_identity.persist_source_label_metadata(
        source_id="src-x",
        twin_id=TWIN_ID,
        source_label="identity",
        identity_confirmed=True,
    )

    assert env.db.tables["sources"][0]["source_label"] == "knowledge"
    assert "metadata" not in env.db.tables["sources"][0]
