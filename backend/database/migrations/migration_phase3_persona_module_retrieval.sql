-- Phase 3 Persona Module Retrieval
-- Improves lookup latency for intent-scoped runtime module selection.

CREATE INDEX IF NOT EXISTS idx_persona_modules_twin_intent_status_created
  ON persona_modules(twin_id, intent_label, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_persona_modules_twin_status_confidence_created
  ON persona_modules(twin_id, status, confidence DESC, created_at DESC);

