import os
import sys

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase


def run_migration():
    print("Running Gate 1 Specialization Migration...")

    try:
        # We can't run raw SQL via the standard Supabase client in some configs,
        # so verify the target column can be selected.
        print("Note: In production environments, please run the SQL in migration_phase3_5_gate1_specialization.sql in the Supabase Dashboard.")
        print("Attempting to verify columns via a dummy select...")

        supabase.table("twins").select("id, specialization_id").limit(1).execute()
        print("Columns verified or migration not needed (already exists).")

    except Exception as e:
        print(f"Migration check failed: {e}")
        print("Please run the SQL manually in Supabase SQL Editor.")


if __name__ == "__main__":
    run_migration()
