import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase

def verify_pipeline(twin_id: str):
    print(f"--- Pipeline Verification for Twin: {twin_id} ---\n")

    # 1. Source Uploaded
    source_res = supabase.table("sources").select("*").eq("twin_id", twin_id).order("created_at", desc=True).limit(1).execute()
    if not source_res.data:
        print("1. [FAIL] Source: No source found for this twin.")
        return

    source = source_res.data[0]
    source_id = source['id']
    print(f"1. [DONE] Source Uploaded: '{source['filename']}' (ID: {source_id})")

    # 2. Extracting text from PDF
    if source.get('content_text'):
        print(f"2. [DONE] Text Extracted: Source has {len(source.get('content_text', ''))} characters stored.")
    else:
        # Check if chunks exist as evidence of extraction
        chunk_check = supabase.table("chunks").select("id", count="exact").eq("source_id", source_id).execute()
        count = chunk_check.count if hasattr(chunk_check, 'count') else len(chunk_check.data)
        if count > 0:
            print(f"2. [DONE] Text Extracted: Evidence found via {count} existing chunks.")
        else:
            print("2. [FAIL] Text Extracted: No content found.")

    # 3. Chunking and embedding
    chunks_res = supabase.table("chunks").select("id, vector_id").eq("source_id", source_id).execute()
    chunk_count = len(chunks_res.data)
    if chunk_count > 0:
        print(f"3. [DONE] Chunking & Embedding: {chunk_count} chunks created.")
    else:
        print("3. [FAIL] Chunking & Embedding: No chunks found.")

    # 4. Indexing to Pinecone
    indexed_count = sum(1 for c in chunks_res.data if c.get('vector_id'))
    if indexed_count > 0:
        print(f"4. [DONE] Indexing: {indexed_count}/{chunk_count} chunks have Pinecone vector IDs.")
    else:
        print("4. [INFO] Indexing: Chunks exist but no vector IDs were found in the Supabase 'chunks' table.")

    # 5. Extracting graph nodes (Scribe Engine)
    job_res = supabase.table("jobs").select("*").eq("source_id", source_id).eq("job_type", "content_extraction").order("created_at", desc=True).limit(1).execute()
    if job_res.data:
        job = job_res.data[0]
        meta = job.get('metadata', {})
        nodes = meta.get('nodes_created', 0)
        edges = meta.get('edges_created', 0)
        status = job['status']
        if status == 'complete' and (nodes > 0 or edges > 0):
            print(f"5. [DONE] Graph Extraction: Success! {nodes} nodes and {edges} edges created.")
        else:
            print(f"5. [WAIT] Graph Extraction: Job status '{status}', Nodes: {nodes}, Edges: {edges}")
    else:
        node_check = supabase.table("nodes").select("id", count="exact").eq("twin_id", twin_id).execute()
        n_count = node_check.count if hasattr(node_check, 'count') else len(node_check.data)
        if n_count > 0:
            print(f"5. [DONE] Graph Extraction: {n_count} nodes exist for this twin.")
        else:
            print("5. [FAIL] Graph Extraction: No nodes/edges found.")

if __name__ == "__main__":
    load_dotenv()
    t_id = "c3cd4ad0-d4cc-4e82-a020-82b48de72d42"
    verify_pipeline(t_id)
