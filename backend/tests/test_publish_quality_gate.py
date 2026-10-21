from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from modules.auth_guard import verify_owner


client = TestClient(app)


def _owner_user():
    return {"user_id": "owner-1", "tenant_id": "tenant-1", "role": "owner"}


def _query_mock(data):
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.single.return_value = query
    query.update.return_value = query
    query.execute.return_value = SimpleNamespace(data=data)
    return query


def test_publish_toggle_has_no_quality_suite_gate():
    app.dependency_overrides[verify_owner] = _owner_user
    try:
        settings_query = _query_mock({"settings": {"widget_settings": {}}})
        update_query = _query_mock([{"id": "twin-1"}])

        with patch("routers.twins.verify_twin_ownership"), patch(
            "routers.twins.get_twin_verification_status",
            return_value={"is_ready": True, "issues": []},
        ), patch("routers.twins.supabase") as mocked_supabase, patch(
            "routers.twins.invalidate_agent"
        ):
            # No verification-table lookup: the quality-suite gate was removed
            # from the publish toggle in 1c64a82b (LinkedIn verification only).
            mocked_supabase.table.side_effect = [settings_query, update_query]

            response = client.patch(
                "/twins/twin-1",
                json={"is_public": True},
            )

            assert response.status_code == 200
            assert response.json() == [{"id": "twin-1"}]

            update_payload = update_query.update.call_args.args[0]
            assert "is_public" not in update_payload
            assert update_payload["settings"]["widget_settings"]["public_share_enabled"] is True
            assert update_payload["settings"]["is_public"] is True
    finally:
        app.dependency_overrides = {}
