"""Check detailed source status."""
__test__ = False
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from modules.observability import supabase

source_id = '921aed5b-7a21-40b1-8783-63907fca8f4c'

print('[SOURCE DETAILS]')
src = supabase.table('sources').select('*').eq('id', source_id).single().execute()
if src.data:
    for k, v in src.data.items():
        if k == 'content_text':
            val = str(v)[:200] + '...' if v else 'None'
            print('  content_text:', val)
        else:
            print(f'  {k}:', v)
