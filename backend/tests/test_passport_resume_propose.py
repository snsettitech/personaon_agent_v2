"""Integration-ish unit tests for propose_claims_from_resume (mocked Gemini)."""

from __future__ import annotations

from unittest.mock import MagicMock

from modules.passport_resume_import import propose_claims_from_resume
from tests._supabase_mock import fluent


def test_propose_claims_from_resume_inserts_proposed_only(monkeypatch):
    twin_chain = fluent({"id": "twin-1", "tenant_id": "tenant-1", "settings": {}})
    profile_select = fluent([])  # no existing profile → insert path in ensure
    # ensure_professional_profile uses maybe_single then insert — simplify by
    # patching ensure + insert + evidence.
    monkeypatch.setattr(
        "modules.passport_resume_import.ensure_professional_profile",
        lambda **kwargs: "prof-1",
    )
    inserted: list[dict] = []

    def _fake_insert(**kwargs):
        inserted.append(kwargs)
        return f"claim-{len(inserted)}"

    monkeypatch.setattr(
        "modules.passport_resume_import.insert_proposed_claim",
        _fake_insert,
    )
    monkeypatch.setattr(
        "modules.passport_resume_import.extract_resume_fields_with_gemini",
        lambda _text: {
            "full_name": "Ada",
            "headline": "Engineer",
            "areas_of_expertise": ["Python"],
        },
    )

    evidence_chain = fluent([{"id": "ev-1"}])
    client = MagicMock()
    client.table.side_effect = lambda name: twin_chain if name == "twins" else evidence_chain

    summary = propose_claims_from_resume(
        twin_id="twin-1",
        source_id="src-1",
        resume_text="Ada is an Engineer skilled in Python.",
        client=client,
        tenant_id="tenant-1",
        correlation_id="corr-1",
    )

    assert summary["profile_id"] == "prof-1"
    assert summary["proposed_count"] == 3
    assert all(row["created_by"] == "import" for row in inserted)
    assert all(row.get("fingerprint") for row in inserted)
    assert client.table.call_count >= 1
