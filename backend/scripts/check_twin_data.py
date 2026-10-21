"""Check twin metadata and source twin_id values"""
from modules.observability import supabase

print("=== ALL SOURCES ===")
sources = supabase.table("sources").select("id, filename, twin_id").limit(10).execute()
if sources.data:
    for s in sources.data:
        fname = s.get('filename', 'unknown')[:40]
        tid = s.get('twin_id', 'NULL')
        tid_short = tid[:8] if tid else 'NULL'
        print(f"  {fname:<45} twin_id={tid_short}")
else:
    print("  No sources found in database")

print("\n=== TWIN DETAILS ===")
twins = supabase.table("twins").select("*").order("created_at", desc=True).limit(3).execute()
for t in twins.data:
    settings = t.get("settings") or {}
    print(f"\n{t['name']}:")
    print(f"  id: {t['id']}")
    print(f"  description: {t.get('description', 'N/A')}")
    print(f"  settings: {list(settings.keys())}")
    if 'handle' in settings:
        print(f"  settings.handle: {settings['handle']}")
    if 'tagline' in settings:
        print(f"  settings.tagline: {settings['tagline']}")

