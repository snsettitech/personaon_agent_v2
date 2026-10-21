import os
from supabase import create_client, Client
from dotenv import load_dotenv

def apply_migration():
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("Missing Supabase credentials")
        return

    supabase: Client = create_client(url, key)

    migration_path = "database/migrations/20260205_phase4_memory_tiers.sql"
    if not os.path.exists(migration_path):
        # Try relative to backend
        migration_path = "backend/" + migration_path
        if not os.path.exists(migration_path):
            print(f"Migration file not found: {migration_path}")
            return

    with open(migration_path) as f:
        sql = f.read()

    print(f"Applying migration: {migration_path}")
    try:
        # We use a simple RPC or just print instructions if we can't run raw SQL
        # In most environments, we can run SQL via a 'pg_exec' style RPC if it exists
        # If not, we just notify the user.
        # Let's try to see if there's a specialized RPC for migrations.
        # For now, I'll use a known 'exec_sql' RPC if available, or just catch the error.
        _ = supabase.rpc("exec_sql", {"sql_query": sql}).execute()
        print("Migration applied successfully via RPC.")
    except Exception as e:
        print(f"Failed to apply migration via RPC: {e}")
        print("Please apply the SQL manually in the Supabase SQL Editor:")
        print("-" * 20)
        print(sql)
        print("-" * 20)

if __name__ == "__main__":
    apply_migration()
