import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
def test_update_widget_config_merges_fields():
    """Existing fields preserved, new fields added."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "widget_config": {"bubble_color": "#FF0000", "position": "bottom-right"}
    }
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{"id": "key-1"}]

    with patch("modules.api_keys.supabase", mock_sb):
        from modules.api_keys import update_widget_config
        result = update_widget_config(
            key_id="key-1",
            config_patch={"position": "bottom-left", "lead_capture_enabled": True},
        )

    assert result is True
    update_call = mock_sb.table.return_value.update.call_args[0][0]
    merged = update_call["widget_config"]
    assert merged["bubble_color"] == "#FF0000"
    assert merged["position"] == "bottom-left"
    assert merged["lead_capture_enabled"] is True


@pytest.mark.unit
def test_update_widget_config_returns_false_for_missing_key():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None

    with patch("modules.api_keys.supabase", mock_sb):
        from modules.api_keys import update_widget_config
        result = update_widget_config(key_id="missing", config_patch={"position": "bottom-left"})

    assert result is False
