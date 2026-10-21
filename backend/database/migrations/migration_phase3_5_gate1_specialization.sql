-- backend/database/migrations/migration_phase3_5_gate1_specialization.sql
-- Goal: Enable per-twin specialization storage

-- 1. Add specialization_id and version to twins table
ALTER TABLE twins ADD COLUMN IF NOT EXISTS specialization_id VARCHAR(50) DEFAULT 'vanilla';
ALTER TABLE twins ADD COLUMN IF NOT EXISTS specialization_version VARCHAR(50) DEFAULT '1.0.0';

-- 2. Audit Log for schema change
DO $$
BEGIN
    -- Optional audit row, only when the placeholder twin exists.
    IF EXISTS (
        SELECT 1 FROM twins WHERE id = '00000000-0000-0000-0000-000000000000'
    ) THEN
        INSERT INTO audit_logs (id, twin_id, actor_id, event_type, action, metadata, created_at)
        VALUES (
            gen_random_uuid(),
            '00000000-0000-0000-0000-000000000000',
            NULL,
            'system_schema_change',
            'ADD_TWIN_SPECIALIZATION_COLUMNS',
            '{"columns": ["specialization_id", "specialization_version"], "phase": "3.5", "gate": 1}',
            NOW()
        );
    END IF;
END $$;

-- 3. (Optional) Set VC specialization for specific experimental twins if needed
-- UPDATE twins SET specialization_id = 'vc' WHERE id = '...some-id...';
