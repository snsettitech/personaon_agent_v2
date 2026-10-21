import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase

def inspect_tables(tables):
    for table_name in tables:
        print(f"\nInspecting '{table_name}' table columns...")
        try:
            res = supabase.table(table_name).select("*").limit(1).execute()
            if res.data:
                print(f"Columns in '{table_name}': {list(res.data[0].keys())}")
            else:
                print(f"Table '{table_name}' is empty or not found.")
        except Exception as e:
            print(f"Error inspecting table '{table_name}': {e}")

if __name__ == "__main__":
    load_dotenv()
    target_tables = ["nodes", "edges", "stances", "identity_claims", "memories", "content_permissions"]
    inspect_tables(target_tables)
