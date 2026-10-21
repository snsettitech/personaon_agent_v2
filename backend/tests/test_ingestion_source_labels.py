import pytest
from fastapi import HTTPException

from routers.ingestion import _validate_source_label


def test_validate_source_label_accepts_supported_values():
    assert _validate_source_label("knowledge", False) == "knowledge"
    assert _validate_source_label("identity", True) == "identity"


def test_validate_source_label_requires_value():
    with pytest.raises(HTTPException) as exc:
        _validate_source_label(None, None)
    assert exc.value.status_code == 422


def test_validate_source_label_rejects_invalid_label():
    with pytest.raises(HTTPException) as exc:
        _validate_source_label("random", False)
    assert exc.value.status_code == 422


def test_validate_source_label_requires_confirmation_for_identity():
    with pytest.raises(HTTPException) as exc:
        _validate_source_label("identity", False)
    assert exc.value.status_code == 422
