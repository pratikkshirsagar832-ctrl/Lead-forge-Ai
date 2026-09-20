-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v14 — payment order ledger
-- Run in the MAIN Supabase project. Idempotent (safe to re-run).
--
-- Why: `user_subscriptions.razorpay_order_id` is a single slot. Starting a
-- second checkout overwrote the first order id, so a payment for the abandoned
-- order could no longer be verified by POST /api/subscriptions/verify and the
-- Razorpay webhook silently ignored it — the customer was charged and never got
-- their plan, with no record to reconcile from.
--
-- Orders now live in their own table. The single slot is still written for
-- backward compatibility, and the backend falls back to it automatically when
-- this migration has not been applied yet.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.payment_orders (
    order_id    TEXT PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_id     TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
                -- 0 only for rows backfilled from the legacy single slot; the
                -- authoritative amount is always re-verified against Razorpay.
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
    payment_id  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_user ON public.payment_orders (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON public.payment_orders (status);

-- Server-only: the backend (service role) is the sole writer/reader. With RLS
-- enabled and no policies, anon/authenticated see nothing even if they guess an
-- order id; the table is also explicitly revoked defensively.
ALTER TABLE public.payment_orders ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.payment_orders FROM PUBLIC, anon, authenticated;

-- Backfill the still-pending orders the old single slot can still resolve, so
-- an in-flight checkout survives the upgrade.
INSERT INTO public.payment_orders (order_id, user_id, plan_id, amount, status, created_at)
SELECT us.razorpay_order_id, us.user_id, us.plan_id, 0, 'pending', us.created_at
FROM public.user_subscriptions us
WHERE us.razorpay_order_id IS NOT NULL
  AND us.razorpay_order_id NOT LIKE 'team:%'
  AND us.status = 'pending'
ON CONFLICT (order_id) DO NOTHING;
