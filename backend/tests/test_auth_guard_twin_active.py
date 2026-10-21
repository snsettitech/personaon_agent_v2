from fastapi import HTTPException

from modules import auth_guard, observability


class _DummyResponse:
    def __init__(self, data):
        self.data = data


class _TwinsQuery:
    def __init__(self, parent):
        self.parent = parent
        self._select = None

    def select(self, fields):
        self._select = fields
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        if self._select == "id, status":
            if self.parent.raise_status_missing:
                raise Exception('column "status" does not exist')
            return _DummyResponse(self.parent.status_row)
        if self._select == "id":
            return _DummyResponse(self.parent.id_row)
        raise AssertionError(f"Unexpected select fields: {self._select}")


class _DummySupabase:
    def __init__(self, *, status_row=None, id_row=None, raise_status_missing=False):
        self.status_row = status_row
        self.id_row = id_row
        self.raise_status_missing = raise_status_missing

    def table(self, name):
        assert name == "twins"
        return _TwinsQuery(self)


def test_ensure_twin_active_falls_back_when_status_column_missing(monkeypatch):
    monkeypatch.setattr(
        observability,
        "supabase",
        _DummySupabase(
            status_row=None,
            id_row={"id": "twin-1"},
            raise_status_missing=True,
        ),
        raising=False,
    )

    assert auth_guard.ensure_twin_active("twin-1") is True


def test_ensure_twin_active_raises_for_inactive_status(monkeypatch):
    monkeypatch.setattr(
        observability,
        "supabase",
        _DummySupabase(
            status_row={"id": "twin-2", "status": "archived"},
            id_row={"id": "twin-2"},
            raise_status_missing=False,
        ),
        raising=False,
    )

    try:
        auth_guard.ensure_twin_active("twin-2")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "not active" in str(exc.detail).lower()


def test_ensure_twin_active_raises_not_found_when_missing(monkeypatch):
    monkeypatch.setattr(
        observability,
        "supabase",
        _DummySupabase(
            status_row=None,
            id_row=None,
            raise_status_missing=True,
        ),
        raising=False,
    )

    try:
        auth_guard.ensure_twin_active("missing-twin")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404
        assert "not found" in str(exc.detail).lower()

