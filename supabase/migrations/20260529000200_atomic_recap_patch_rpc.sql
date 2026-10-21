-- =============================================================================
-- Layer 2 / Phase 30 review fix (Bug 7): atomic PATCH /recap.
--
-- BEFORE: router did 3 separate supabase calls:
--   (1) UPDATE meetings SET summary_json|recap_extras_json
--   (2) INSERT INTO recap_edits (before, after)
--   (3) enqueue routing/reminder jobs
--
-- The `before` snapshot was computed in Python from the row fetched earlier
-- in the request. Two concurrent PATCHes both reading the SAME row would
-- each compute a `before` based on stale state; whichever UPDATE landed
-- second would silently overwrite the first edit and its recap_edits row
-- would point at the wrong baseline.
--
-- This RPC takes a row-level lock (FOR UPDATE) on meetings, applies the
-- patch, and inserts the audit row inside a single transaction so the
-- before/after pair always reflects the row as it actually existed at the
-- moment of UPDATE.
--
-- Return shape: jsonb { meeting: {...full updated row...}, edit_id: uuid }
-- so the router can:
--   * return the merged meeting row to the client (parity with the
--     pre-RPC code path that returned `rows[0]`),
--   * pass edit_id to the routing-job enqueue helper.
-- =============================================================================

-- LINT-ALLOW: new-overload
CREATE OR REPLACE FUNCTION update_recap_with_audit(
    p_meeting_id uuid,
    p_tenant_id  uuid,
    p_user_id    uuid,
    p_field      text,
    p_json_column text,        -- 'summary_json' or 'recap_extras_json'
    p_after      jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_meeting      meetings%ROWTYPE;
    v_current_doc  jsonb;
    v_next_doc     jsonb;
    v_before       jsonb;
    v_edit_id      uuid;
    v_after_text   text;
BEGIN
    -- Whitelist the json column name. EXECUTE-format on an arbitrary text
    -- input would be a SQL-injection vector even with SECURITY DEFINER.
    IF p_json_column NOT IN ('summary_json', 'recap_extras_json') THEN
        RAISE EXCEPTION 'invalid_json_column: %', p_json_column
            USING ERRCODE = '22023';
    END IF;

    -- Whitelist the field. Mirrors the CHECK constraint on recap_edits.field.
    IF p_field NOT IN (
        'tldr', 'topics', 'action_items', 'key_questions',
        'intent', 'what_happened', 'commitments'
    ) THEN
        RAISE EXCEPTION 'invalid_recap_field: %', p_field
            USING ERRCODE = '22023';
    END IF;

    -- Take a row-level lock so any concurrent PATCH on the same meeting
    -- queues behind us instead of computing a stale `before` snapshot.
    SELECT * INTO v_meeting
    FROM meetings
    WHERE id = p_meeting_id
      AND tenant_id = p_tenant_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'meeting_not_found_or_cross_tenant: %', p_meeting_id
            USING ERRCODE = 'P0001';
    END IF;

    -- Read current JSON doc, compute next doc, capture before for audit.
    IF p_json_column = 'summary_json' THEN
        v_current_doc := COALESCE(v_meeting.summary_json, '{}'::jsonb);
    ELSE
        v_current_doc := COALESCE(v_meeting.recap_extras_json, '{}'::jsonb);
    END IF;

    v_before   := v_current_doc -> p_field;          -- may be NULL on first edit
    v_next_doc := jsonb_set(v_current_doc, ARRAY[p_field], p_after, true);

    -- Apply the patch. Two field-specific side effects mirror the router's
    -- pre-RPC behavior: tldr also lands in the legacy `summary` text column,
    -- and action_items also lands in the legacy `action_items` jsonb column.
    IF p_json_column = 'summary_json' THEN
        IF p_field = 'tldr' THEN
            -- jsonb scalar -> text. Use jsonb_typeof to avoid quoting numbers.
            IF jsonb_typeof(p_after) = 'string' THEN
                v_after_text := p_after #>> '{}';
            ELSE
                v_after_text := '';
            END IF;
            UPDATE meetings
            SET summary_json = v_next_doc,
                summary      = v_after_text,
                updated_at   = now()
            WHERE id = p_meeting_id;
        ELSIF p_field = 'action_items' THEN
            UPDATE meetings
            SET summary_json = v_next_doc,
                action_items = p_after,
                updated_at   = now()
            WHERE id = p_meeting_id;
        ELSE
            UPDATE meetings
            SET summary_json = v_next_doc,
                updated_at   = now()
            WHERE id = p_meeting_id;
        END IF;
    ELSE
        UPDATE meetings
        SET recap_extras_json = v_next_doc,
            updated_at        = now()
        WHERE id = p_meeting_id;
    END IF;

    -- Audit row. Inside the same txn so it's impossible to have an UPDATE
    -- without its matching recap_edits row.
    INSERT INTO recap_edits (meeting_id, tenant_id, user_id, field, before, after)
    VALUES (p_meeting_id, p_tenant_id, p_user_id, p_field, v_before, p_after)
    RETURNING id INTO v_edit_id;

    -- Return only client-safe columns (F6.7 review fix). The prior
    -- `to_jsonb(v_meeting)` serialised every column including
    -- transcript_raw, recall_bot_id, share_token, and any future
    -- internal column added to the meetings table. Even though the
    -- Python `_serialize` helper currently narrows the response, the
    -- defense-in-depth principle is to never leak past the data
    -- boundary in the first place — Python column allowlists drift
    -- as the schema grows.
    --
    -- The final SELECT also re-enforces the tenant filter (S5 review
    -- fix): the row was locked under the same condition above, so a
    -- mismatch is structurally impossible inside this txn, but the
    -- explicit AND tenant_id = p_tenant_id silences any future static
    -- analysis lint flagging tenant-unscoped SELECTs in SECURITY
    -- DEFINER functions.
    RETURN (
        SELECT jsonb_build_object(
            'meeting', jsonb_build_object(
                'id', m.id,
                'title', m.title,
                'status', m.status,
                'source', m.source,
                'platform', m.platform,
                'duration_seconds', m.duration_seconds,
                'meeting_start', m.meeting_start,
                'meeting_end', m.meeting_end,
                'created_at', m.created_at,
                'updated_at', m.updated_at,
                'transcript_url', m.transcript_url,
                'transcript_provider', m.transcript_provider,
                'video_url', m.video_url,
                'speaker_timeline_url', m.speaker_timeline_url,
                'summary', m.summary,
                'summary_json', m.summary_json,
                'recap_extras_json', m.recap_extras_json,
                'action_items', m.action_items,
                'twin_id', m.twin_id,
                'recall_recording_id', m.recall_recording_id
            ),
            'edit_id', v_edit_id
        )
        FROM meetings m
        WHERE m.id = p_meeting_id AND m.tenant_id = p_tenant_id
    );
END;
$$;

-- Service-role only. The router calls this via the service key; direct
-- authenticated invocation is intentionally blocked so the audit trail
-- cannot be forged client-side.
REVOKE ALL ON FUNCTION update_recap_with_audit(uuid, uuid, uuid, text, text, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_recap_with_audit(uuid, uuid, uuid, text, text, jsonb) TO service_role;
