-- ============================================================================
-- BOOKING REQUESTS TABLE
-- Stores visitor booking requests for persona calendar slots.
-- Status lifecycle: pending -> approved | rejected | cancelled | expired
-- ============================================================================

CREATE TABLE IF NOT EXISTS booking_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    twin_id UUID NOT NULL REFERENCES twins(id) ON DELETE CASCADE,
    visitor_name VARCHAR(200) NOT NULL,
    visitor_email VARCHAR(200) NOT NULL,
    visitor_message TEXT,
    visitor_timezone VARCHAR(100),
    proposed_start TIMESTAMPTZ NOT NULL,
    proposed_end TIMESTAMPTZ NOT NULL,
    slot_duration_minutes INT DEFAULT 30,
    status VARCHAR(20) DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled', 'expired')),
    approved_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,
    rejection_reason TEXT,
    gcal_event_id VARCHAR(200),
    meet_link VARCHAR(500),
    event_link VARCHAR(500),
    conversation_id UUID,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ DEFAULT (now() + interval '48 hours')
);

CREATE INDEX IF NOT EXISTS idx_booking_twin ON booking_requests(twin_id, status);
CREATE INDEX IF NOT EXISTS idx_booking_start ON booking_requests(proposed_start);
