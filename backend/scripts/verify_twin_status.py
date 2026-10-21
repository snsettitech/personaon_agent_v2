import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase

async def verify_twin_status(twin_id: str):
    print(f"\n[INFO] Verifying status for Twin: {twin_id}")

    # 1. Check Sources
    try:
        sources = supabase.table("sources").select("*").eq("twin_id", twin_id).order("created_at", desc=True).execute()
        print(f"\n[SOURCES] ({len(sources.data)} found):")
        for source in sources.data[:5]:  # Show top 5
            print(f"   - {source.get('filename')} (ID: {source.get('id')})")
            print(f"     Status: {source.get('status')} | Staging: {source.get('staging_status')}")
            print(f"     Chunks: {source.get('chunk_count')} | Created: {source.get('created_at')}")
    except Exception as e:
        print(f"[ERROR] Error fetching sources: {e}")

    # 2. Check Jobs (Table: jobs) - For Content Extraction
    try:
        jobs = supabase.table("jobs").select("*").eq("twin_id", twin_id).order("created_at", desc=True).limit(5).execute()
        print("\n[JOBS] Recent Jobs (Table: jobs) - Limit 5:")
        for job in jobs.data:
            print(f"   - Job ID: {job.get('id')}")
            print(f"     Type: {job.get('job_type')} | Status: {job.get('status')}")
            print(f"     Created: {job.get('created_at')} | Completed: {job.get('completed_at')}")
            print(f"     Metadata: {job.get('metadata')}")
            if job.get('error_message'):
                print(f"     [!] Error: {job.get('error_message')}")
    except Exception as e:
        print(f"[ERROR] Error fetching jobs: {e}")

    # 3. Check Training Jobs (Table: training_jobs) - For Ingestion
    try:
        t_jobs = supabase.table("training_jobs").select("*").eq("twin_id", twin_id).order("created_at", desc=True).limit(5).execute()
        print("\n[TRAINING JOBS] Recent Training Jobs (Table: training_jobs) - Limit 5:")
        for job in t_jobs.data:
            print(f"   - Job ID: {job.get('id')}")
            print(f"     Type: {job.get('job_type')} | Status: {job.get('status')}")
            print(f"     Created: {job.get('created_at')}")
    except Exception as e:
        print(f"[ERROR] Error fetching training jobs: {e}")

    # 4. Check Nodes and Edges count
    try:
        nodes = supabase.table("nodes").select("id", count="exact").eq("twin_id", twin_id).execute()
        node_count = nodes.count if hasattr(nodes, 'count') else len(nodes.data)
        print(f"\n[GRAPH] Node count: {node_count}")

        edges = supabase.table("edges").select("id", count="exact").eq("twin_id", twin_id).execute()
        edge_count = edges.count if hasattr(edges, 'count') else len(edges.data)
        print(f"[GRAPH] Edge count: {edge_count}")
    except Exception as e:
        print(f"[ERROR] Error fetching graph counts: {e}")

if __name__ == "__main__":
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python verify_twin_status.py <twin_id>")
        sys.exit(1)

    twin_id = sys.argv[1]
    asyncio.run(verify_twin_status(twin_id))
