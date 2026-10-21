"""
Manually re-trigger ingestion for a stuck source.
This will:
1. Fetch the source record
2. Download the file if available
3. Re-run the full ingestion pipeline
"""
__test__ = False
import asyncio
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

from modules.observability import supabase

SOURCE_ID = '921aed5b-7a21-40b1-8783-63907fca8f4c'
TWIN_ID = 'c3cd4ad0-d4cc-4e82-a020-82b48de72d42'

async def main():
    print('[1] Checking source record...')
    src = supabase.table('sources').select('filename, file_url, content_text, status').eq('id', SOURCE_ID).single().execute()
    if not src.data:
        print('ERROR: Source not found!')
        return

    print(f'  Filename: {src.data.get("filename")}')
    print(f'  Status: {src.data.get("status")}')
    print(f'  Has content_text: {bool(src.data.get("content_text"))}')

    if src.data.get('content_text'):
        print('[INFO] Source already has content_text. Just needs reindexing.')
        text = src.data.get('content_text')
    else:
        print('[2] No content_text - need file to re-extract...')
        print('[ERROR] File was not persisted. User needs to re-upload.')
        print()
        print('SOLUTION:')
        print(f'1. Delete this source: DELETE FROM sources WHERE id = {SOURCE_ID}')
        print('2. Re-upload the file through the UI')
        print('3. Or manually provide the file path below')
        return

    # If we have text, we can re-index
    print('[3] Re-indexing to Pinecone...')
    from modules.ingestion import process_and_index_text

    num_chunks = await process_and_index_text(
        SOURCE_ID,
        TWIN_ID,
        text,
        metadata_override={'filename': src.data.get('filename', 'unknown'), 'type': 'file'}
    )
    print(f'  Indexed {num_chunks} chunks')

    # Update status
    supabase.table('sources').update({
        'status': 'live',
        'staging_status': 'live',
        'chunk_count': num_chunks
    }).eq('id', SOURCE_ID).execute()
    print('[4] Status updated to live')

    # Trigger graph extraction
    print('[5] Triggering graph extraction...')
    from modules._core.scribe_engine import enqueue_content_extraction_job
    enqueue_content_extraction_job(
        twin_id=TWIN_ID,
        source_id=SOURCE_ID,
        tenant_id=None,
        source_type='file_upload',
        max_chunks=6
    )
    print('  Graph extraction enqueued')
    print()
    print('[DONE] Source should now be live!')

if __name__ == '__main__':
    asyncio.run(main())
