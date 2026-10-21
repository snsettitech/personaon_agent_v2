import asyncio
import os
import sys
import uuid
from dotenv import load_dotenv

# Add the parent directory to sys.path to import modules correctly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.ingestion import ingest_youtube_transcript, ingest_x_thread
from modules.observability import supabase

async def verify_youtube(twin_id: str):
    print("\n--- Testing YouTube Resilience (Strategy 1.6) ---")
    # This video ScMzIvxBSi4 was previously failing with 403
    video_url = "https://www.youtube.com/watch?v=ScMzIvxBSi4"
    source_id = str(uuid.uuid4())

    try:
        print(f"Ingesting YouTube: {video_url} for source_id: {source_id}")
        chunks = await ingest_youtube_transcript(source_id, twin_id, video_url)
        print(f"✅ YouTube Ingestion SUCCESS: Developed {chunks} chunks")

        # Verify in DB
        res = supabase.table("sources").select("id, status, content_text").eq("id", source_id).single().execute()
        if res.data and len(res.data.get("content_text", "")) > 100:
            print(f"[SUCCESS] DB Verification SUCCESS: Content found ({len(res.data['content_text'])} chars)")
        else:
            print("[FAILED] DB Verification FAILED: Content empty or missing")
    except Exception as e:
        print(f"[FAILED] YouTube Ingestion FAILED: {e}")

async def verify_x(twin_id: str):
    print("\n--- Testing X Thread Resilience (4 Fallbacks) ---")
    x_url = "https://x.com/naval/status/1002103360646823936"
    source_id = str(uuid.uuid4())

    try:
        print(f"Ingesting X Thread: {x_url} for source_id: {source_id}")
        chunks = await ingest_x_thread(source_id, twin_id, x_url)
        print(f"[SUCCESS] X Ingestion SUCCESS: Developed {chunks} chunks")

        # Verify in DB
        res = supabase.table("sources").select("id, status, content_text").eq("id", source_id).single().execute()
        if res.data and len(res.data.get("content_text", "")) > 50:
            print(f"[SUCCESS] DB Verification SUCCESS: Content found ({len(res.data['content_text'])} chars)")
        else:
            print("[FAILED] DB Verification FAILED: Content empty or missing")
    except Exception as e:
        print(f"[FAILED] X Ingestion FAILED: {e}")

async def main():
    load_dotenv()
    test_twin_id = "6118cb8a-016b-444d-ad84-2cab0a8310f8" # My AI Persona
    print(f"Testing with Twin ID: {test_twin_id}")

    await verify_youtube(test_twin_id)
    await verify_x(test_twin_id)

if __name__ == "__main__":
    asyncio.run(main())
