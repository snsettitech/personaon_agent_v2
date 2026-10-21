-- Phase 30-G: Link tool_connectors to Recall.ai Calendar V2.
-- After Google/Outlook OAuth completes in calendar_booking.py, the captured
-- refresh_token is also registered with Recall.ai Calendar V2 so they can sync
-- calendar events + auto-dispatch meeting bots. recall_calendar_id stores the
-- Recall connection ID so we can deregister on disconnect.

ALTER TABLE public.tool_connectors
    ADD COLUMN IF NOT EXISTS recall_calendar_id TEXT;

CREATE INDEX IF NOT EXISTS idx_tool_connectors_recall_cal
    ON public.tool_connectors(recall_calendar_id)
    WHERE recall_calendar_id IS NOT NULL;

-- TODO(graduation): add UNIQUE(twin_id, connector_type) constraint on
-- tool_connectors to prevent duplicate connectors per twin. Concurrent OAuth
-- callbacks (e.g. two browser tabs) can currently produce orphaned Recall
-- subscriptions. Migration left out of this PR to keep scope contained;
-- backfill any existing duplicates before adding the constraint.
