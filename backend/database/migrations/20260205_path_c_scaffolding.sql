-- 20260205_path_c_scaffolding.sql
-- Path C: Temporal Scaffolding for Global Reasoning

-- 1. Add temporal columns to nodes
ALTER TABLE nodes 
ADD COLUMN IF NOT EXISTS effective_from TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS effective_to TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS provenance JSONB DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1;

-- 2. Add temporal columns to edges
ALTER TABLE edges
ADD COLUMN IF NOT EXISTS effective_from TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS effective_to TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS provenance JSONB DEFAULT '{}'::jsonb;

-- 3. Create indices for temporal queries
CREATE INDEX IF NOT EXISTS idx_nodes_temporal ON nodes (twin_id, effective_from, effective_to);
CREATE INDEX IF NOT EXISTS idx_edges_temporal ON edges (twin_id, effective_from, effective_to);

-- 4. Comment on table for documentation
COMMENT ON COLUMN nodes.provenance IS 'Metadata about where this node was extracted from: session_id, source_doc, confidence';
COMMENT ON COLUMN nodes.effective_from IS 'Start of the validity period for this belief/fact';
COMMENT ON COLUMN nodes.effective_to IS 'End of the validity period (null means currently active)';
