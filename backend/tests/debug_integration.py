# tests/debug_integration.py
import sys
import os
from unittest.mock import MagicMock, patch, AsyncMock

# 1. Setup paths
sys.path.insert(0, os.getcwd())

# 2. Mock Modules BEFORE importing app
sys.modules["modules.observability"] = MagicMock()
# sys.modules["modules.auth_guard"] = MagicMock()  <-- This causes Depends(Mock) 422
sys.modules["modules.ingestion"] = MagicMock()

# 3. Import App
from fastapi.testclient import TestClient
from main import app
from modules.auth_guard import get_current_user

# 4. Dependency Override
app.dependency_overrides[get_current_user] = lambda: {"user_id": "test", "tenant_id": "test"}

# 5. Patch MediaIngester
# We need to patch the class method on the imported module
from modules.media_ingestion import MediaIngester

client = TestClient(app)

def run_test():
    with patch.object(MediaIngester, 'ingest_youtube_video', new_callable=AsyncMock) as mock_ingest:
        mock_ingest.return_value = {"success": True, "chunks": 10}

        print("Sending POST request...")
        response = client.post(
            "/ingest/youtube/twin-123",
            json={"url": "http://youtube.com/watch?v=realvideo"}
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")

        if response.status_code == 200:
            print("SUCCESS")
        else:
            print("FAILURE")

if __name__ == "__main__":
    run_test()
