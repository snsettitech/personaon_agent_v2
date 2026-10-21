-- ============================================================================
-- DATA REPAIR: Fix Orphaned Twins with Wrong tenant_id
-- ============================================================================
-- This script fixes twins that were created with user.id (auth UUID) 
-- instead of the correct tenants.id (tenant UUID)

-- STEP 1: Identify orphaned twins
-- These twins have tenant_id matching a user's auth ID, not a tenant's ID
SELECT 
    t.id as twin_id, 
    t.name as twin_name, 
    t.tenant_id as wrong_tenant_id,
    u.tenant_id as correct_tenant_id,
    u.email as user_email
FROM twins t
JOIN users u ON t.tenant_id = u.id
WHERE NOT EXISTS (SELECT 1 FROM tenants tn WHERE tn.id = t.tenant_id);

-- STEP 2: Update orphaned twins to use the correct tenant_id
-- IMPORTANT: Review the SELECT output above before running this UPDATE
UPDATE twins 
SET tenant_id = (
    SELECT u.tenant_id 
    FROM users u 
    WHERE u.id = twins.tenant_id
)
WHERE EXISTS (
    SELECT 1 FROM users u 
    WHERE u.id = twins.tenant_id
)
AND NOT EXISTS (
    SELECT 1 FROM tenants tn 
    WHERE tn.id = twins.tenant_id
);

-- STEP 3: Verify fix - should return 0 rows after UPDATE
SELECT COUNT(*) as remaining_orphans
FROM twins t
JOIN users u ON t.tenant_id = u.id
WHERE NOT EXISTS (SELECT 1 FROM tenants tn WHERE tn.id = t.tenant_id);
