"""Check job status for stuck ingestion."""
__test__ = False
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from modules.observability import supabase

source_id = '921aed5b-7a21-40b1-8783-63907fca8f4c'
twin_id = 'c3cd4ad0-d4cc-4e82-a020-82b48de72d42'

print('[SOURCE]')
src = supabase.table('sources').select('id, filename, status, created_at').eq('id', source_id).single().execute()
if src.data:
    print('  File:', src.data.get('filename'))
    print('  Status:', src.data.get('status'))
    print('  Created:', src.data.get('created_at'))

print()
print('[JOBS for twin]')
jobs = supabase.table('jobs').select('id, job_type, status, created_at').eq('twin_id', twin_id).order('created_at', desc=True).limit(10).execute()
if not jobs.data:
    print('  No jobs found!')
for j in (jobs.data or []):
    print('  Type:', j.get('job_type'), '| Status:', j.get('status'))

print()
print('[INGESTION LOGS]')
logs = supabase.table('ingestion_logs').select('severity, message').eq('source_id', source_id).order('timestamp', desc=True).limit(15).execute()
if not logs.data:
    print('  No logs found!')
for l in (logs.data or []):
    sev = l.get('severity', 'info')
    msg = l.get('message', '')[:100]
    print('  [' + sev + ']', msg)

print()
print('[JOB_LOGS for twin]')
job_logs = supabase.table('job_logs').select('job_id, level, message').order('created_at', desc=True).limit(10).execute()
if not job_logs.data:
    print('  No job logs found!')
for l in (job_logs.data or []):
    print('  [' + l.get('level', 'info') + ']', l.get('message', '')[:80])
