-- P0.1: Memory Events Table
-- Audit trail for all memory extraction and modification events

-- 1. Create memory_events table
CREATE TABLE IF NOT EXISTS memory_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID NOT NULL,
  twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL CHECK (event_type IN ('auto_extract', 'manual_edit', 'confirm', 'delete')),
  source_type TEXT, -- 'chat_turn', 'file_upload'
  source_id TEXT,   -- conversation_id, message_id, file_id
  payload JSONB NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'failed', 'pending_review')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. RLS Policy
ALTER TABLE memory_events ENABLE ROW LEVEL SECURITY;

-- View policy: Users can only see events for twins in their tenant
CREATE POLICY "Tenant Isolation: View Memory Events" ON memory_events
FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM twins 
    WHERE twins.id = memory_events.twin_id 
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

-- Modify policy: Users can only modify events for twins in their tenant
CREATE POLICY "Tenant Isolation: Modify Memory Events" ON memory_events
FOR ALL USING (
  EXISTS (
    SELECT 1 FROM twins 
    WHERE twins.id = memory_events.twin_id 
    AND twins.tenant_id = (auth.jwt() ->> 'tenant_id')::uuid
  )
);

-- 3. Indexes for performance
CREATE INDEX IF NOT EXISTS idx_memory_events_twin ON memory_events(twin_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_created ON memory_events(twin_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_events_type ON memory_events(twin_id, event_type);
CREATE INDEX IF NOT EXISTS idx_memory_events_status ON memory_events(twin_id, status);

-- 4. System RPC for creating events (bypasses RLS for backend use)
CREATE OR REPLACE FUNCTION create_memory_event_system(
  p_tenant_id UUID,
  p_twin_id UUID,
  p_event_type TEXT,
  p_payload JSONB,
  p_status TEXT DEFAULT 'applied',
  p_source_type TEXT DEFAULT NULL,
  p_source_id TEXT DEFAULT NULL
)
RETURNS SETOF memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  INSERT INTO memory_events (tenant_id, twin_id, event_type, payload, status, source_type, source_id)
  VALUES (p_tenant_id, p_twin_id, p_event_type, p_payload, p_status, p_source_type, p_source_id)
  RETURNING *;
END;
$$;

-- 5. System RPC for updating event payload
CREATE OR REPLACE FUNCTION update_memory_event_system(
  p_event_id UUID,
  p_payload JSONB
)
RETURNS SETOF memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  UPDATE memory_events
  SET payload = memory_events.payload || p_payload
  WHERE id = p_event_id
  RETURNING *;
END;
$$;

-- 6. System RPC for getting events by twin (for TIL feed)
CREATE OR REPLACE FUNCTION get_memory_events_system(
  p_twin_id UUID,
  p_limit INT DEFAULT 50,
  p_event_type TEXT DEFAULT NULL
)
RETURNS SETOF memory_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM memory_events
  WHERE twin_id = p_twin_id
    AND (p_event_type IS NULL OR event_type = p_event_type)
  ORDER BY created_at DESC
  LIMIT p_limit;
END;
$$;
