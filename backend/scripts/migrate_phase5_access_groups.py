#!/usr/bin/env python3
"""
Migration script for Phase 5: Access Groups
This script creates default "public" groups for existing twins and migrates data.
"""

import sys
import os

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.observability import supabase
import os
from dotenv import load_dotenv

load_dotenv()

def verify_migration():
    """Verify that the migration tables exist."""
    print("Verifying migration tables exist...")

    try:
        # Try to query each table
        supabase.table("access_groups").select("id").limit(1).execute()
        supabase.table("group_memberships").select("id").limit(1).execute()
        supabase.table("content_permissions").select("id").limit(1).execute()
        supabase.table("group_limits").select("id").limit(1).execute()
        supabase.table("group_overrides").select("id").limit(1).execute()
        print("✓ All migration tables exist")
        return True
    except Exception as e:
        print(f"✗ Error: Migration tables may not exist. Please run migration SQL first: {e}")
        return False

def migrate_twins_to_groups():
    """Create default 'public' group for each twin."""
    print("\n=== Creating default groups for twins ===")

    # Get all twins
    twins_response = supabase.table("twins").select("id, name").execute()

    if not twins_response.data:
        print("No twins found. Skipping group creation.")
        return

    print(f"Found {len(twins_response.data)} twin(s)")

    created_groups = 0
    for twin in twins_response.data:
        twin_id = twin["id"]
        twin_name = twin.get("name", "Unknown")

        # Check if default group already exists
        existing = supabase.table("access_groups").select("id").eq(
            "twin_id", twin_id
        ).eq("is_default", True).execute()

        if existing.data:
            print(f"  Twin '{twin_name}' ({twin_id[:8]}...) already has default group. Skipping.")
            continue

        # Create default "public" group
        try:
            group_response = supabase.table("access_groups").insert({
                "twin_id": twin_id,
                "name": "public",
                "description": "Default public group for all existing content and users",
                "is_default": True,
                "is_public": True,
                "settings": {}
            }).execute()

            if group_response.data:
                created_groups += 1
                print(f"  ✓ Created default group for twin '{twin_name}' ({twin_id[:8]}...)")
        except Exception as e:
            print(f"  ✗ Error creating group for twin '{twin_name}': {e}")

    print(f"\nCreated {created_groups} default group(s)")

def migrate_users_to_groups():
    """Assign all existing users to their twin's default group."""
    print("\n=== Assigning users to default groups ===")

    # Get all users with their tenant info
    # We need to find which twin(s) each user belongs to
    # Since users belong to tenants and twins belong to tenants,
    # we'll need to get users per tenant, then get twins per tenant

    tenants_response = supabase.table("tenants").select("id, name").execute()

    if not tenants_response.data:
        print("No tenants found. Skipping user assignment.")
        return

    assigned_count = 0
    skipped_count = 0

    for tenant in tenants_response.data:
        tenant_id = tenant["id"]
        _ = tenant.get("name", "Unknown")

        # Get all users for this tenant
        users_response = supabase.table("users").select("id, email").eq("tenant_id", tenant_id).execute()

        if not users_response.data:
            continue

        # Get all twins for this tenant
        twins_response = supabase.table("twins").select("id, name").eq("tenant_id", tenant_id).execute()

        if not twins_response.data:
            continue

        # For each twin, get the default group and assign users
        for twin in twins_response.data:
            twin_id = twin["id"]
            twin_name = twin.get("name", "Unknown")

            # Get default group for this twin
            group_response = supabase.table("access_groups").select("id").eq(
                "twin_id", twin_id
            ).eq("is_default", True).single().execute()

            if not group_response.data:
                print(f"  ✗ No default group found for twin '{twin_name}'. Skipping user assignments.")
                continue

            group_id = group_response.data["id"]

            # Assign each user to this group (if not already assigned)
            for user in users_response.data:
                user_id = user["id"]

                # Check if membership already exists
                existing = supabase.table("group_memberships").select("id").eq(
                    "user_id", user_id
                ).eq("twin_id", twin_id).execute()

                if existing.data:
                    skipped_count += 1
                    continue

                # Create membership
                try:
                    supabase.table("group_memberships").insert({
                        "group_id": group_id,
                        "user_id": user_id,
                        "twin_id": twin_id,
                        "is_active": True
                    }).execute()
                    assigned_count += 1
                except Exception as e:
                    print(f"  ✗ Error assigning user {user['email']} to twin '{twin_name}': {e}")

    print(f"\nAssigned {assigned_count} user-twin memberships")
    if skipped_count > 0:
        print(f"Skipped {skipped_count} existing memberships")

def migrate_content_to_groups():
    """Grant default group access to all existing sources and verified_qna."""
    print("\n=== Granting default group access to content ===")

    # Process sources
    print("Processing sources...")
    sources_response = supabase.table("sources").select("id, twin_id").execute()

    sources_granted = 0
    sources_skipped = 0

    if sources_response.data:
        for source in sources_response.data:
            source_id = source["id"]
            twin_id = source["twin_id"]

            # Get default group for this twin
            group_response = supabase.table("access_groups").select("id").eq(
                "twin_id", twin_id
            ).eq("is_default", True).single().execute()

            if not group_response.data:
                continue

            group_id = group_response.data["id"]

            # Check if permission already exists
            existing = supabase.table("content_permissions").select("id").eq(
                "group_id", group_id
            ).eq("content_type", "source").eq("content_id", source_id).execute()

            if existing.data:
                sources_skipped += 1
                continue

            # Grant permission
            try:
                supabase.table("content_permissions").insert({
                    "group_id": group_id,
                    "twin_id": twin_id,
                    "content_type": "source",
                    "content_id": source_id
                }).execute()
                sources_granted += 1
            except Exception as e:
                print(f"  ✗ Error granting permission for source {source_id}: {e}")

    print(f"  Granted access to {sources_granted} source(s), skipped {sources_skipped} existing")

    # Process verified_qna
    print("Processing verified QnA...")
    qna_response = supabase.table("verified_qna").select("id, twin_id").execute()

    qna_granted = 0
    qna_skipped = 0

    if qna_response.data:
        for qna in qna_response.data:
            qna_id = qna["id"]
            twin_id = qna["twin_id"]

            # Get default group for this twin
            group_response = supabase.table("access_groups").select("id").eq(
                "twin_id", twin_id
            ).eq("is_default", True).single().execute()

            if not group_response.data:
                continue

            group_id = group_response.data["id"]

            # Check if permission already exists
            existing = supabase.table("content_permissions").select("id").eq(
                "group_id", group_id
            ).eq("content_type", "verified_qna").eq("content_id", qna_id).execute()

            if existing.data:
                qna_skipped += 1
                continue

            # Grant permission
            try:
                supabase.table("content_permissions").insert({
                    "group_id": group_id,
                    "twin_id": twin_id,
                    "content_type": "verified_qna",
                    "content_id": qna_id
                }).execute()
                qna_granted += 1
            except Exception as e:
                print(f"  ✗ Error granting permission for verified QnA {qna_id}: {e}")

    print(f"  Granted access to {qna_granted} verified QnA entry/entries, skipped {qna_skipped} existing")

def verify_data_integrity():
    """Verify that migration completed successfully."""
    print("\n=== Verifying data integrity ===")

    # Check that all twins have default groups
    twins_response = supabase.table("twins").select("id").execute()
    if twins_response.data:
        for twin in twins_response.data:
            group_response = supabase.table("access_groups").select("id").eq(
                "twin_id", twin["id"]
            ).eq("is_default", True).execute()
            if not group_response.data:
                print(f"  ✗ WARNING: Twin {twin['id']} has no default group")
            else:
                print(f"  ✓ Twin {twin['id'][:8]}... has default group")

    # Check that all users have memberships (per tenant-twin combination they could access)
    # This is more complex - we'll just report counts
    memberships_response = supabase.table("group_memberships").select("id", count="exact").execute()
    print(f"  ✓ Total group memberships: {len(memberships_response.data) if memberships_response.data else 0}")

    # Check content permissions
    permissions_response = supabase.table("content_permissions").select("id", count="exact").execute()
    print(f"  ✓ Total content permissions: {len(permissions_response.data) if permissions_response.data else 0}")

def main():
    print("=" * 60)
    print("Phase 5: Access Groups Migration Script")
    print("=" * 60)

    if not verify_migration():
        print("\nPlease run the migration SQL file first:")
        print("  migration_phase5_access_groups.sql")
        sys.exit(1)

    try:
        migrate_twins_to_groups()
        migrate_users_to_groups()
        migrate_content_to_groups()
        verify_data_integrity()

        print("\n" + "=" * 60)
        print("Migration completed successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"\n✗ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
