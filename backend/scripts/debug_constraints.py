import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase

def check_event_types():
    print("Querying database for unique memory_events.event_type values...")
    try:
        # Supabase doesn't support 'DISTINCT' directly through the client easily for large tables
        # but we can try to select all and unique them in Python if it's not too many rows,
        # or use an RPC if available.
        # Let's try to get a sample and see if we can find outliers.

        # Better: Since we want to find EXACTLY what's breaking the constraint,
        # we can try to select 'event_type' only.
        res = supabase.table("memory_events").select("event_type").execute()

        if res.data:
            types = set(item['event_type'] for item in res.data)
            print("\nFound unique event types in database:")
            for t in sorted(list(types)):
                print(f" - {t}")
        else:
            print("No data found in memory_events table.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    load_dotenv()
    check_event_types()
