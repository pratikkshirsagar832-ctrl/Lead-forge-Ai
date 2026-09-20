-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v13 — atomic daily quota consumption
-- Run in the MAIN Supabase project. Idempotent (safe to re-run).
--
-- Why: `check_search_limit` and `check_ai_limit` read the daily counter and the
-- caller incremented it AFTER doing the work. Two requests arriving together
-- both saw "under the limit" and both were allowed, so a plan's daily cap could
-- be exceeded (each search burns paid Apify/Serper/DeepSeek spend). The quota
-- is now consumed in a single row-locked statement, exactly like
-- reserve_monthly_leads does for the monthly lead caps.
--
-- Contract (matches the reserve_monthly_leads convention):
--   returns -1  -> consumed, the caller may proceed
--   returns >=0 -> refused; the value is the REMAINING allowance
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION public.consume_daily_quota(
    p_user_id uuid,
    p_kind text,
    p_limit integer
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  cur integer;
BEGIN
  IF p_kind NOT IN ('search', 'ai') OR p_limit IS NULL OR p_limit < 0 THEN
    RAISE EXCEPTION 'invalid daily quota request';
  END IF;

  INSERT INTO public.daily_usage (user_id, date, leads_generated, searches_run, ai_calls)
  VALUES (p_user_id, CURRENT_DATE, 0, 0, 0)
  ON CONFLICT (user_id, date) DO NOTHING;

  -- Row lock: concurrent callers serialise here instead of racing a read.
  PERFORM 1 FROM public.daily_usage
   WHERE user_id = p_user_id AND date = CURRENT_DATE
   FOR UPDATE;

  IF p_kind = 'search' THEN
    SELECT searches_run INTO cur FROM public.daily_usage
     WHERE user_id = p_user_id AND date = CURRENT_DATE;
    cur := COALESCE(cur, 0);
    IF cur >= p_limit THEN
      RETURN GREATEST(0, p_limit - cur);
    END IF;
    UPDATE public.daily_usage SET searches_run = cur + 1
     WHERE user_id = p_user_id AND date = CURRENT_DATE;
    RETURN -1;
  END IF;

  SELECT ai_calls INTO cur FROM public.daily_usage
   WHERE user_id = p_user_id AND date = CURRENT_DATE;
  cur := COALESCE(cur, 0);
  IF cur >= p_limit THEN
    RETURN GREATEST(0, p_limit - cur);
  END IF;
  UPDATE public.daily_usage SET ai_calls = cur + 1
   WHERE user_id = p_user_id AND date = CURRENT_DATE;
  RETURN -1;
END;
$$;

-- Give back a consumed unit when the caller could not use it (e.g. the search
-- row failed to insert). Clamped at zero so a double refund can never produce a
-- negative counter (daily_usage has CHECK (>= 0)).
CREATE OR REPLACE FUNCTION public.refund_daily_quota(
    p_user_id uuid,
    p_kind text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF p_kind NOT IN ('search', 'ai') THEN
    RAISE EXCEPTION 'invalid daily quota refund';
  END IF;
  IF p_kind = 'search' THEN
    UPDATE public.daily_usage SET searches_run = GREATEST(0, searches_run - 1)
     WHERE user_id = p_user_id AND date = CURRENT_DATE;
  ELSE
    UPDATE public.daily_usage SET ai_calls = GREATEST(0, ai_calls - 1)
     WHERE user_id = p_user_id AND date = CURRENT_DATE;
  END IF;
END;
$$;

-- Backend-only: these counters are server-authoritative.
DO $$
DECLARE
  fns text[] := ARRAY[
    'public.consume_daily_quota(uuid,text,integer)',
    'public.refund_daily_quota(uuid,text)'
  ];
  sig text;
BEGIN
  FOREACH sig IN ARRAY fns LOOP
    IF to_regprocedure(sig) IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', sig);
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', sig);
    END IF;
  END LOOP;
END $$;
