# backend/tests/test_media_integration.py
"""Integration tests for Phase 5 Media endpoints.

Tests:
- POST /ingest/youtube/{twin_id}
"""

import sys
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from uuid import UUID

# Add backend to path
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from main import app
from modules.auth_guard import verify_owner

client = TestClient(app)

class TestMediaIntegration(unittest.TestCase):

    def setUp(self):
        # Override Auth Dependency (owner-only ingestion endpoints)
        app.dependency_overrides[verify_owner] = lambda: {"user_id": "test-user", "tenant_id": "test-tenant"}

    def tearDown(self):
        app.dependency_overrides = {}

    @patch('routers.ingestion.verify_twin_ownership')
    @patch('routers.ingestion._queue_ingestion_job')
    @patch('routers.ingestion.finish_step')
    @patch('routers.ingestion.start_step')
    @patch('routers.ingestion._insert_source_row')
    @patch('routers.ingestion.uuid.uuid4')
    def test_youtube_endpoint(self, mock_uuid4, mock_insert, mock_start_step, mock_finish_step, mock_queue, mock_auth):
        """Test POST /ingest/youtube/{twin_id}"""
        # Mock auth to always succeed
        mock_auth.return_value = True

        # Stable IDs for assertion
        mock_uuid4.return_value = UUID("00000000-0000-0000-0000-000000000123")
        mock_queue.return_value = "job-123"
        mock_start_step.return_value = "event-1"

        response = client.post(
            "/ingest/youtube/twin-123",
            json={"url": "http://youtube.com/watch?v=realvideo"}
        )

        if response.status_code != 200:
            print(f"FAIL BODY: {response.text}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_id"], "00000000-0000-0000-0000-000000000123")
        self.assertEqual(response.json()["job_id"], "job-123")
        self.assertEqual(response.json()["status"], "pending")

        mock_insert.assert_called_once()
        mock_start_step.assert_called()
        mock_finish_step.assert_called()
        mock_queue.assert_called_once()

if __name__ == "__main__":
    unittest.main(verbosity=2)
