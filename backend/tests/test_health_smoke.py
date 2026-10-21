"""
Smoke test: INFRA-01 (backend /health) and INFRA-02 (frontend / returns 200).

Usage (local, against deployed services):
  BACKEND_URL=https://personaon-api-xxx.run.app \
  FRONTEND_URL=https://personaon-web-xxx.run.app \
  pytest backend/tests/test_health_smoke.py -v

Usage (local backend only, no frontend deployed yet):
  BACKEND_URL=http://localhost:8000 pytest backend/tests/test_health_smoke.py::test_backend_health -v

The test skips gracefully if env vars are not set (safe to run in CI without
a deployed service — the GitHub Actions deploy workflow adds a curl smoke step instead).
"""
import os
import httpx
import pytest


BACKEND_URL = os.environ.get("BACKEND_URL", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "")


@pytest.mark.skipif(not BACKEND_URL, reason="BACKEND_URL not set — skipping backend smoke test")
def test_backend_health():
    """INFRA-01: Backend /health endpoint returns 200 within 30 seconds."""
    response = httpx.get(f"{BACKEND_URL}/health", timeout=30.0)
    assert response.status_code == 200, (
        f"Backend health check failed. Status: {response.status_code}, "
        f"Body: {response.text[:200]}"
    )


@pytest.mark.skipif(not FRONTEND_URL, reason="FRONTEND_URL not set — skipping frontend smoke test")
def test_frontend_root():
    """INFRA-02: Frontend root / returns 200 within 30 seconds."""
    response = httpx.get(f"{FRONTEND_URL}/", timeout=30.0, follow_redirects=True)
    assert response.status_code == 200, (
        f"Frontend root check failed. Status: {response.status_code}, "
        f"Body: {response.text[:200]}"
    )


def test_smoke_test_module_importable():
    """Sanity check: this file is valid and importable."""
    assert True
