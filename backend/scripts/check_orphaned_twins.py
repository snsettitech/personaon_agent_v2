"""Check for orphaned twins and users without tenants."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.observability import supabase

def main():
    print("=== Checking for orphaned twins ===")
    twins = supabase.table("twins").select("id, name, tenant_id, created_at").execute()
    tenants = supabase.table("tenants").select("id").execute()

    tenant_ids = set(t["id"] for t in tenants.data) if tenants.data else set()
    orphans = []

    for twin in (twins.data or []):
        if twin["tenant_id"] not in tenant_ids:
            orphans.append(twin)

    if orphans:
        print(f"Found {len(orphans)} orphaned twins:")
        for o in orphans:
            print(f"  - {o['id']}: {o['name']} (tenant_id={o['tenant_id']})")
    else:
        print("No orphaned twins found.")

    print()
    print("=== Checking for users without tenants ===")
    users = supabase.table("users").select("id, email, tenant_id").execute()
    users_no_tenant = [u for u in (users.data or []) if not u.get("tenant_id")]
    if users_no_tenant:
        print(f"Found {len(users_no_tenant)} users without tenant_id:")
        for u in users_no_tenant:
            print(f"  - {u['id']}: {u.get('email', '?')}")
    else:
        print("All users have tenant_id.")

    print()
    print("=== Summary ===")
    print(f"Total twins: {len(twins.data or [])}")
    print(f"Total tenants: {len(tenants.data or [])}")
    print(f"Orphaned twins: {len(orphans)}")
    print(f"Users without tenant: {len(users_no_tenant)}")

    return orphans, users_no_tenant

if __name__ == "__main__":
    orphans, users_no_tenant = main()
    sys.exit(1 if orphans or users_no_tenant else 0)
