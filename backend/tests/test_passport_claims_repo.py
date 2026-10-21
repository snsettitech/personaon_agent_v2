"""Tests for passport_claims repository (PON-7 Task 4).

TDD order: write tests → RED → implement → GREEN.
"""
import pytest
from unittest.mock import MagicMock

from tests._supabase_mock import fluent


# ---------------------------------------------------------------------------
# ensure_professional_profile
# ---------------------------------------------------------------------------


def test_ensure_professional_profile_returns_existing():
    """Select returns a row → return that id; upsert must NOT be called."""
    from modules.passport_claims import ensure_professional_profile

    client = MagicMock()
    chain = fluent({"id": "prof-existing"})
    client.table.return_value = chain

    actual = ensure_professional_profile(
        tenant_id="ten-1",
        twin_id="tw-1",
        owner_user_id="u-1",
        client=client,
    )

    assert actual == "prof-existing"
    assert client.table.call_count == 1
    chain.upsert.assert_not_called()


def test_ensure_professional_profile_handles_none_maybe_single_response():
    """supabase-py may return None from maybe_single().execute() on zero rows."""
    from modules.passport_claims import ensure_professional_profile

    client = MagicMock()
    select_chain = MagicMock()
    for name in (
        "select", "eq", "maybe_single", "upsert", "single", "insert",
    ):
        getattr(select_chain, name).return_value = select_chain
    select_chain.execute.return_value = None  # Codex P1: Falsey response

    upsert_chain = fluent(None)
    win_chain = fluent({"id": "prof-won"})
    client.table.side_effect = [select_chain, upsert_chain, win_chain]

    actual = ensure_professional_profile(
        tenant_id="ten-1",
        twin_id="tw-1",
        owner_user_id="u-1",
        client=client,
    )

    assert actual == "prof-won"
    assert client.table.call_count == 3
    upsert_chain.upsert.assert_called_once()


def test_ensure_professional_profile_inserts_when_missing():
    """Select returns nothing → conflict-safe upsert → return winning id."""
    from modules.passport_claims import ensure_professional_profile

    client = MagicMock()
    select_chain = fluent(None)
    upsert_chain = fluent(None)
    win_chain = fluent({"id": "prof-new"})
    client.table.side_effect = [select_chain, upsert_chain, win_chain]

    actual = ensure_professional_profile(
        tenant_id="ten-1",
        twin_id="tw-1",
        owner_user_id="u-1",
        client=client,
    )

    assert actual == "prof-new"
    assert client.table.call_count == 3
    upsert_kwargs = upsert_chain.upsert.call_args
    assert upsert_kwargs[0][0]["status"] == "draft"
    assert upsert_kwargs[1].get("on_conflict") == "twin_id"
    assert upsert_kwargs[1].get("ignore_duplicates") is True


# ---------------------------------------------------------------------------
# insert_proposed_claim
# ---------------------------------------------------------------------------


def test_insert_proposed_claim_rejects_bad_type():
    """claim_type not in allowlist → ValueError (belief is a rejected type)."""
    from modules.passport_claims import insert_proposed_claim

    client = MagicMock()
    with pytest.raises(ValueError, match="belief"):
        insert_proposed_claim(
            tenant_id="ten-1",
            profile_id="prof-1",
            claim_type="belief",
            value_json={"text": "I believe in open source"},
            value_text="I believe in open source",
            client=client,
        )
    client.table.assert_not_called()


def test_insert_proposed_claim_rejects_invalid_created_by():
    """created_by not in allowed set → ValueError before any DB call."""
    from modules.passport_claims import insert_proposed_claim

    client = MagicMock()
    with pytest.raises(ValueError, match="scraper"):
        insert_proposed_claim(
            tenant_id="ten-1",
            profile_id="prof-1",
            claim_type="headline",
            value_json={"text": "Engineer"},
            value_text="Engineer",
            client=client,
            created_by="scraper",
        )
    client.table.assert_not_called()


def test_insert_proposed_claim_happy():
    """Valid claim_type → insert into profile_claims with state=proposed → return claim id."""
    from modules.passport_claims import insert_proposed_claim

    client = MagicMock()
    chain = fluent([{"id": "claim-1"}])
    client.table.return_value = chain

    claim_id = insert_proposed_claim(
        tenant_id="ten-1",
        profile_id="prof-1",
        claim_type="headline",
        value_json={"text": "Senior Backend Engineer"},
        value_text="Senior Backend Engineer",
        client=client,
        confidence=0.95,
        extraction_version="v1",
        fingerprint="abc123",
    )

    assert claim_id == "claim-1"
    client.table.assert_called_once_with("profile_claims")
    inserted_row = chain.insert.call_args[0][0]
    assert inserted_row["state"] == "proposed"
    assert inserted_row["claim_type"] == "headline"
    assert inserted_row["confidence"] == 0.95


_REVIEWER_UUID = "00000000-0000-4000-8000-000000000001"


# ---------------------------------------------------------------------------
# transition_claim_state
# ---------------------------------------------------------------------------


def test_transition_proposed_to_approved():
    """proposed → approved: conditional update on state=proposed."""
    from modules.passport_claims import transition_claim_state

    client = MagicMock()
    update_chain = fluent([{"id": "claim-1"}])
    client.table.return_value = update_chain

    transition_claim_state(
        claim_id="claim-1",
        new_state="approved",
        reviewed_by=_REVIEWER_UUID,
        client=client,
    )

    assert client.table.call_count == 1
    updated_payload = update_chain.update.call_args[0][0]
    assert updated_payload["state"] == "approved"
    assert updated_payload["reviewed_by"] == _REVIEWER_UUID
    assert "reviewed_at" in updated_payload
    # Must filter by proposed so concurrent finalize cannot overwrite
    eq_calls = [c.args for c in update_chain.eq.call_args_list]
    assert ("id", "claim-1") in eq_calls
    assert ("state", "proposed") in eq_calls


def test_transition_proposed_to_rejected():
    """proposed → rejected: same field update with state=rejected."""
    from modules.passport_claims import transition_claim_state

    client = MagicMock()
    update_chain = fluent([{"id": "claim-2"}])
    client.table.return_value = update_chain

    transition_claim_state(
        claim_id="claim-2",
        new_state="rejected",
        reviewed_by=_REVIEWER_UUID,
        client=client,
    )

    updated_payload = update_chain.update.call_args[0][0]
    assert updated_payload["state"] == "rejected"


def test_transition_cannot_approve_when_not_proposed():
    """Update matches zero rows (already finalized) → ValueError."""
    from modules.passport_claims import transition_claim_state

    client = MagicMock()
    update_chain = fluent([])  # zero rows updated
    client.table.return_value = update_chain

    with pytest.raises(ValueError, match="proposed"):
        transition_claim_state(
            claim_id="claim-3",
            new_state="approved",
            reviewed_by=_REVIEWER_UUID,
            client=client,
        )


# ---------------------------------------------------------------------------
# correct_claim
# ---------------------------------------------------------------------------


def test_correct_claim_rejects_bad_type():
    """claim_type not in allowlist → ValueError before any DB call."""
    from modules.passport_claims import correct_claim

    client = MagicMock()
    with pytest.raises(ValueError, match="belief"):
        correct_claim(
            claim_id="claim-old",
            tenant_id="ten-1",
            profile_id="prof-1",
            claim_type="belief",
            value_json={"text": "I believe in open source"},
            value_text="I believe in open source",
            reviewed_by=_REVIEWER_UUID,
            client=client,
        )
    client.rpc.assert_not_called()


def test_correct_claim_calls_atomic_rpc():
    """Correction goes through correct_profile_claim RPC (single transaction)."""
    from modules.passport_claims import correct_claim

    client = MagicMock()
    rpc_chain = fluent("claim-new")
    client.rpc.return_value = rpc_chain

    new_id = correct_claim(
        claim_id="claim-old",
        tenant_id="ten-1",
        profile_id="prof-1",
        claim_type="headline",
        value_json={"text": "Corrected headline"},
        value_text="Corrected headline",
        reviewed_by=_REVIEWER_UUID,
        client=client,
        confidence=0.9,
    )

    assert new_id == "claim-new"
    client.rpc.assert_called_once()
    assert client.rpc.call_args[0][0] == "correct_profile_claim"
    params = client.rpc.call_args[0][1]
    assert params["p_claim_id"] == "claim-old"
    assert params["p_tenant_id"] == "ten-1"
    assert params["p_profile_id"] == "prof-1"
    assert params["p_confidence"] == 0.9
    client.table.assert_not_called()


def test_correct_claim_maps_rpc_state_error():
    """RPC 'cannot correct state' surfaces as ValueError."""
    from modules.passport_claims import correct_claim

    client = MagicMock()
    rpc_chain = MagicMock()
    rpc_chain.execute.side_effect = Exception(
        "correct_profile_claim: cannot correct state=rejected"
    )
    client.rpc.return_value = rpc_chain

    with pytest.raises(ValueError, match="cannot correct state"):
        correct_claim(
            claim_id="claim-rej",
            tenant_id="ten-1",
            profile_id="prof-1",
            claim_type="bio",
            value_json={"text": "x"},
            value_text="x",
            reviewed_by=_REVIEWER_UUID,
            client=client,
        )
