import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_fresh_twin_score():
    """A twin with no meetings/commitments/memory starts at 1/6 (twin_created)."""
    from services.persona_progress import compute_progress

    mock_supa = MagicMock()
    # twins table: has display_name + bio
    mock_supa.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "display_name": "Sooraj", "bio": "Engineer", "public_share_enabled": False
    }
    # Count queries: 0 meetings, 0 done commitments, 0 approved memory, no public share
    mock_supa.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.count = 0

    with patch("services.persona_progress.supabase", mock_supa):
        result = await compute_progress("twin-1")

    assert result["completed"] >= 1  # at minimum twin_created
    assert result["total"] == 6
    assert result["checkpoints"]["twin_created"] is True


@pytest.mark.asyncio
async def test_profile_filled_checkpoint():
    from services.persona_progress import compute_progress

    mock_supa = MagicMock()
    mock_supa.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
        "display_name": "Sooraj", "bio": "Engineer", "public_share_enabled": False
    }
    mock_supa.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.count = 0

    with patch("services.persona_progress.supabase", mock_supa):
        result = await compute_progress("twin-1")

    assert result["checkpoints"]["profile_filled"] is True
