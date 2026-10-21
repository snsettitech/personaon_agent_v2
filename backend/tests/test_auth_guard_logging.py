from datetime import datetime, timedelta

from jose import jwt
from starlette.requests import Request

from modules import auth_guard
from modules import observability


class _DummyResponse:
    def __init__(self, data):
        self.data = data


class _DummyTable:
    def __init__(self):
        self._single = False

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        self._single = True
        return self

    def update(self, *args, **kwargs):
        return self

    def execute(self):
        if self._single:
            return _DummyResponse({"email": "user@example.com"})
        return _DummyResponse([{"tenant_id": "tenant-123"}])


class _DummySupabase:
    def table(self, *args, **kwargs):
        return _DummyTable()


def test_get_current_user_does_not_log_jwt_secret(monkeypatch, capsys):
    secret = "supersecretvalue-32-bytes-minimum"
    token = jwt.encode(
        {
            "sub": "user-123",
            "aud": "authenticated",
            "email": "user@example.com",
            "exp": datetime.utcnow() + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )

    # Ensure test doesn't rely on external services
    monkeypatch.setattr(observability, "supabase", _DummySupabase(), raising=False)
    monkeypatch.setattr(auth_guard, "SUPABASE_JWT_SECRET", secret, raising=False)
    monkeypatch.setattr(auth_guard, "DEV_MODE", True, raising=False)

    request = Request(
        {
            "type": "http",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )

    auth_guard.get_current_user(
        request,
        authorization=f"Bearer {token}",
        x_twin_api_key=None,
        origin=None,
        referer=None,
    )

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
