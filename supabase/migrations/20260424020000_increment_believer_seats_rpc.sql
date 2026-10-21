-- Phase 4: Atomic believer seat increment RPC.
-- Called by billing webhook on checkout.session.completed for believer_ltd.
-- Uses UPDATE ... WHERE ... RETURNING to ensure atomicity under concurrent claims.
-- Raises exception if all seats are taken (seats_sold >= seats_cap).

-- LINT-ALLOW: new-overload
CREATE OR REPLACE FUNCTION increment_believer_seats()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    updated_id INTEGER;
BEGIN
    UPDATE public.believer_seats
    SET seats_sold = seats_sold + 1,
        updated_at = NOW()
    WHERE id = 1
      AND seats_sold < seats_cap
    RETURNING id INTO updated_id;

    IF updated_id IS NULL THEN
        RAISE EXCEPTION 'believer_seats_cap_reached: All Believer seats have been claimed.'
            USING ERRCODE = 'P0001';
    END IF;
END;
$$;

-- Only service_role may call this function (webhook handler uses service key)
REVOKE ALL ON FUNCTION increment_believer_seats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION increment_believer_seats() TO service_role;
