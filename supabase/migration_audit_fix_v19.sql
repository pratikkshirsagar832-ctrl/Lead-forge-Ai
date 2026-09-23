-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — AUDIT FIX v19 (consolidated missing pieces)
-- Paste the WHOLE file once in Supabase Dashboard → SQL Editor → Run.
-- Idempotent (safe to re-run; every statement guards itself).
--
-- Audit (2026-09-23, via PostgREST schema cache + probes on prod):
--   PRESENT: all 14 other tables, all monthly-quota RPCs
--            (reserve/settle/consume/refund_monthly), save_lead,
--            all quota/owner columns, ha observability columns,
--            ha_leads.posted_at (v18 columns visible).
--   MISSING: (1) public.payment_orders table  → v14 below
--            (2) consume_daily_quota / refund_daily_quota RPCs → v13 below
--   Impact of the gaps: daily caps enforced via racy fallback (double-spend
--   possible under concurrency); Razorpay order ledger unwritten
--   (payment_id NULL on verified rows, no reconciliation record).
-- ═══════════════════════════════════════════════════════════════

-- ── Part 1: v13 — atomic daily quota consumption ─────────────────────
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

-- ── Part 2: v14 — payment order ledger ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.payment_orders (
    order_id    TEXT PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_id     TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
    payment_id  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_user ON public.payment_orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON public.payment_orders (status);

ALTER TABLE public.payment_orders ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.payment_orders FROM PUBLIC, anon, authenticated;

-- Backfill still-pending orders the old single slot can resolve.
INSERT INTO public.payment_orders (order_id, user_id, plan_id, amount, status, created_at)
SELECT us.razorpay_order_id, us.user_id, us.plan_id, 0, 'pending', us.created_at
FROM public.user_subscriptions us
WHERE us.razorpay_order_id IS NOT NULL
  AND us.razorpay_order_id NOT LIKE 'team:%'
  AND us.status = 'pending'
ON CONFLICT (order_id) DO NOTHING;
