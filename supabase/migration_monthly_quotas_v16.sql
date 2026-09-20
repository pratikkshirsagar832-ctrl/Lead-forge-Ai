-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v16 — monthly quotas (searches/AI/leads) + agency $199
-- Run in the MAIN Supabase project. Idempotent (safe to re-run).
--
-- Why: searches, AI calls and generic leads reset DAILY
-- (plans.searches_per_day / leads_per_day + hardcoded AI_DAILY_LIMITS +
-- daily_usage counters). Product decision: all quotas are MONTHLY now,
-- keeping the SAME numbers (pro 15/day -> 15/mo). daily_usage is kept for
-- reporting only; enforcement moves to monthly_usage.
--
-- Also: agency $299 (29900) -> $199 (19900). Solo $19 / Pro $49 re-affirmed.
-- Amounts are USD cents; Razorpay INR amounts stay server-side env config.
-- ═══════════════════════════════════════════════════════════════

-- 1. New monthly quota columns on plans (copy daily values as monthly) ──
ALTER TABLE public.plans
  ADD COLUMN IF NOT EXISTS searches_per_month INTEGER NOT NULL DEFAULT 3 CHECK (searches_per_month >= 0),
  ADD COLUMN IF NOT EXISTS leads_per_month INTEGER NOT NULL DEFAULT 30 CHECK (leads_per_month >= 0),
  ADD COLUMN IF NOT EXISTS ai_calls_monthly INTEGER NOT NULL DEFAULT 5 CHECK (ai_calls_monthly >= 0);

UPDATE public.plans SET
  searches_per_month = CASE id WHEN 'free' THEN 3 WHEN 'solo' THEN 5 WHEN 'pro' THEN 15 WHEN 'agency' THEN 50 ELSE searches_per_month END,
  leads_per_month = CASE id WHEN 'free' THEN 30 WHEN 'solo' THEN 50 WHEN 'pro' THEN 150 WHEN 'agency' THEN 500 ELSE leads_per_month END,
  ai_calls_monthly = CASE id WHEN 'free' THEN 5 WHEN 'solo' THEN 25 WHEN 'pro' THEN 100 WHEN 'agency' THEN 300 ELSE ai_calls_monthly END
WHERE id IN ('free', 'solo', 'pro', 'agency');

-- 2. Pricing audit: solo $19 / pro $49 / agency $199 ─────────────────────
-- Also backfill v5 columns some deployments skipped (live DBs missing
-- billing_cycle_days 500 public pricing when selected explicitly).
ALTER TABLE public.plans
  ADD COLUMN IF NOT EXISTS billing_cycle_days INTEGER NOT NULL DEFAULT 30 CHECK (billing_cycle_days > 0),
  ADD COLUMN IF NOT EXISTS features JSONB NOT NULL DEFAULT '[]'::jsonb;
UPDATE public.plans SET billing_cycle_days = 30 WHERE billing_cycle_days IS NULL;
UPDATE public.plans SET price_monthly = 1900 WHERE id = 'solo';
UPDATE public.plans SET price_monthly = 4900 WHERE id = 'pro';
UPDATE public.plans SET price_monthly = 19900 WHERE id = 'agency';
UPDATE public.plans
SET description = '$199/mo - 400 HQ LinkedIn leads + 6000 GMB leads per month, 50 searches/mo'
WHERE id = 'agency';

-- 3. Monthly ledger counters for searches + AI ───────────────────────────
ALTER TABLE public.monthly_usage
  ADD COLUMN IF NOT EXISTS searches_used INTEGER NOT NULL DEFAULT 0 CHECK (searches_used >= 0),
  ADD COLUMN IF NOT EXISTS ai_calls_used INTEGER NOT NULL DEFAULT 0 CHECK (ai_calls_used >= 0);

-- 4. Atomic monthly consume/settle helpers (row-locked, like v5/v13) ─────
CREATE OR REPLACE FUNCTION public.consume_monthly_quota(
  p_user_id UUID, p_kind TEXT, p_limit INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  month_start DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
  cur INTEGER;
BEGIN
  IF p_kind NOT IN ('search', 'ai') OR p_limit IS NULL OR p_limit < 0 THEN
    RAISE EXCEPTION 'invalid monthly quota request';
  END IF;
  INSERT INTO public.monthly_usage (user_id, usage_month)
  VALUES (p_user_id, month_start)
  ON CONFLICT (user_id, usage_month) DO NOTHING;
  PERFORM 1 FROM public.monthly_usage
   WHERE user_id = p_user_id AND usage_month = month_start FOR UPDATE;
  IF p_kind = 'search' THEN
    SELECT searches_used INTO cur FROM public.monthly_usage
     WHERE user_id = p_user_id AND usage_month = month_start;
    cur := COALESCE(cur, 0);
    IF cur >= p_limit THEN RETURN GREATEST(0, p_limit - cur); END IF;
    UPDATE public.monthly_usage SET searches_used = cur + 1, updated_at = now()
     WHERE user_id = p_user_id AND usage_month = month_start;
    RETURN -1;
  END IF;
  SELECT ai_calls_used INTO cur FROM public.monthly_usage
   WHERE user_id = p_user_id AND usage_month = month_start;
  cur := COALESCE(cur, 0);
  IF cur >= p_limit THEN RETURN GREATEST(0, p_limit - cur); END IF;
  UPDATE public.monthly_usage SET ai_calls_used = cur + 1, updated_at = now()
   WHERE user_id = p_user_id AND usage_month = month_start;
  RETURN -1;
END;
$$;

CREATE OR REPLACE FUNCTION public.refund_monthly_quota(
  p_user_id UUID, p_kind TEXT
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
DECLARE
  month_start DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
BEGIN
  IF p_kind NOT IN ('search', 'ai') THEN
    RAISE EXCEPTION 'invalid monthly quota refund';
  END IF;
  IF p_kind = 'search' THEN
    UPDATE public.monthly_usage SET searches_used = GREATEST(0, searches_used - 1), updated_at = now()
     WHERE user_id = p_user_id AND usage_month = month_start;
  ELSE
    UPDATE public.monthly_usage SET ai_calls_used = GREATEST(0, ai_calls_used - 1), updated_at = now()
     WHERE user_id = p_user_id AND usage_month = month_start;
  END IF;
END;
$$;

-- Backend-only RPCs.
DO $$
DECLARE
  fns text[] := ARRAY[
    'public.consume_monthly_quota(uuid,text,integer)',
    'public.refund_monthly_quota(uuid,text)'
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
