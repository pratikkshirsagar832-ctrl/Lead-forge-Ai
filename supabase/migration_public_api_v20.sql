-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — PUBLIC API v1 + PREPAID WALLET  (v20)
-- Apply AFTER migration_posted_at_v18.sql / migration_audit_fix_v19.sql
-- in the Supabase SQL Editor. Idempotent (safe to re-run).
--
-- What this adds:
--   1. api_keys            — hashed API keys (raw key is never stored)
--   2. api_wallets         — prepaid balance per user, in PAISE (integers)
--   3. api_wallet_ledger   — every money movement (topup/hold/charge/release)
--   4. searches.*          — billing='api' columns (price lock, hold, webhook)
--   5. RPCs (atomic, row-locked):
--        api_wallet_hold(user, search, amount)   -> boolean
--        api_wallet_settle(search, delivered)    -> integer (paise charged)
--        api_wallet_credit(user, amount, payment_id, kind, note) -> bigint
--
-- Billing model: when an API search is created, leads × price is HELD from
-- the wallet. When the search finishes, only DELIVERED leads × price is
-- CHARGED and the rest of the hold is RELEASED. Settle is idempotent.
-- ═══════════════════════════════════════════════════════════════

-- ── 1. API keys ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL DEFAULT 'Default key',
    prefix          TEXT NOT NULL,                 -- e.g. "hc_live_AbC1" (display only)
    key_hash        TEXT NOT NULL UNIQUE,          -- sha256(raw key), hex
    webhook_secret  TEXT NOT NULL,                 -- signs webhook deliveries
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON public.api_keys (user_id, created_at DESC);

-- ── 2. Wallets (paise) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.api_wallets (
    user_id        UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    balance_paise  BIGINT NOT NULL DEFAULT 0 CHECK (balance_paise >= 0),
    held_paise     BIGINT NOT NULL DEFAULT 0 CHECK (held_paise >= 0),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 3. Ledger ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.api_wallet_ledger (
    id             BIGSERIAL PRIMARY KEY,
    user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind           TEXT NOT NULL CHECK (kind IN ('topup', 'hold', 'charge', 'release', 'adjust')),
    amount_paise   BIGINT NOT NULL,
    balance_after  BIGINT NOT NULL,
    search_id      UUID,
    payment_id     TEXT,
    note           TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_api_ledger_user ON public.api_wallet_ledger (user_id, created_at DESC);
-- A payment can credit a wallet at most once (idempotent top-ups).
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_ledger_payment
    ON public.api_wallet_ledger (payment_id) WHERE payment_id IS NOT NULL;

-- ── 4. searches: API billing columns ─────────────────────────────
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS billing TEXT NOT NULL DEFAULT 'plan';
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS api_key_id UUID;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS price_per_lead_paise INTEGER;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS wallet_hold_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS wallet_charged_paise BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS wallet_settled_at TIMESTAMPTZ;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS webhook_url TEXT;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS webhook_status TEXT;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS webhook_attempts INTEGER NOT NULL DEFAULT 0;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'searches_billing_check') THEN
    ALTER TABLE public.searches ADD CONSTRAINT searches_billing_check CHECK (billing IN ('plan', 'api'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_searches_api ON public.searches (user_id, created_at DESC) WHERE billing = 'api';

-- ── 5a. Hold: reserve leads × price before a search starts ───────
CREATE OR REPLACE FUNCTION public.api_wallet_hold(
    p_user_id uuid,
    p_search_id uuid,
    p_amount bigint
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  w public.api_wallets%ROWTYPE;
BEGIN
  IF p_amount IS NULL OR p_amount <= 0 THEN
    RAISE EXCEPTION 'invalid hold amount';
  END IF;
  INSERT INTO public.api_wallets (user_id) VALUES (p_user_id) ON CONFLICT (user_id) DO NOTHING;
  SELECT * INTO w FROM public.api_wallets WHERE user_id = p_user_id FOR UPDATE;
  IF w.balance_paise - w.held_paise < p_amount THEN
    RETURN false;
  END IF;
  UPDATE public.api_wallets
     SET held_paise = held_paise + p_amount, updated_at = now()
   WHERE user_id = p_user_id;
  UPDATE public.searches SET wallet_hold_paise = p_amount WHERE id = p_search_id;
  INSERT INTO public.api_wallet_ledger (user_id, kind, amount_paise, balance_after, search_id, note)
  VALUES (p_user_id, 'hold', p_amount, w.balance_paise, p_search_id, 'reserved for search');
  RETURN true;
END;
$$;

-- ── 5b. Settle: charge delivered × price, release the rest ───────
CREATE OR REPLACE FUNCTION public.api_wallet_settle(
    p_search_id uuid,
    p_delivered integer
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  s record;
  v_charge bigint;
  v_release bigint;
  v_balance bigint;
BEGIN
  SELECT id, user_id, billing, price_per_lead_paise, wallet_hold_paise, wallet_settled_at
    INTO s FROM public.searches WHERE id = p_search_id FOR UPDATE;
  IF NOT FOUND OR s.billing <> 'api' THEN
    RETURN 0;
  END IF;
  IF s.wallet_settled_at IS NOT NULL THEN
    RETURN 0;  -- already settled: idempotent no-op
  END IF;

  v_charge := LEAST(GREATEST(COALESCE(p_delivered, 0), 0)::bigint * COALESCE(s.price_per_lead_paise, 0),
                    COALESCE(s.wallet_hold_paise, 0));
  v_release := COALESCE(s.wallet_hold_paise, 0) - v_charge;

  INSERT INTO public.api_wallets (user_id) VALUES (s.user_id) ON CONFLICT (user_id) DO NOTHING;
  PERFORM 1 FROM public.api_wallets WHERE user_id = s.user_id FOR UPDATE;
  UPDATE public.api_wallets
     SET balance_paise = GREATEST(0, balance_paise - v_charge),
         held_paise = GREATEST(0, held_paise - COALESCE(s.wallet_hold_paise, 0)),
         updated_at = now()
   WHERE user_id = s.user_id
  RETURNING balance_paise INTO v_balance;

  IF v_charge > 0 THEN
    INSERT INTO public.api_wallet_ledger (user_id, kind, amount_paise, balance_after, search_id, note)
    VALUES (s.user_id, 'charge', -v_charge, v_balance, p_search_id,
            GREATEST(COALESCE(p_delivered, 0), 0) || ' lead(s) delivered');
  END IF;
  IF v_release > 0 THEN
    INSERT INTO public.api_wallet_ledger (user_id, kind, amount_paise, balance_after, search_id, note)
    VALUES (s.user_id, 'release', v_release, v_balance, p_search_id, 'unused hold released');
  END IF;

  UPDATE public.searches
     SET wallet_settled_at = now(), wallet_charged_paise = v_charge
   WHERE id = p_search_id;
  RETURN v_charge;
END;
$$;

-- ── 5c. Credit: top-ups (idempotent on payment_id) and adjustments ─
CREATE OR REPLACE FUNCTION public.api_wallet_credit(
    p_user_id uuid,
    p_amount bigint,
    p_payment_id text,
    p_kind text DEFAULT 'topup',
    p_note text DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_balance bigint;
BEGIN
  IF p_amount IS NULL OR p_amount <= 0 OR p_kind NOT IN ('topup', 'adjust') THEN
    RAISE EXCEPTION 'invalid credit';
  END IF;
  INSERT INTO public.api_wallets (user_id) VALUES (p_user_id) ON CONFLICT (user_id) DO NOTHING;
  PERFORM 1 FROM public.api_wallets WHERE user_id = p_user_id FOR UPDATE;
  IF p_payment_id IS NOT NULL AND EXISTS (
      SELECT 1 FROM public.api_wallet_ledger WHERE payment_id = p_payment_id) THEN
    SELECT balance_paise INTO v_balance FROM public.api_wallets WHERE user_id = p_user_id;
    RETURN v_balance;  -- already credited: never double-credit a payment
  END IF;
  UPDATE public.api_wallets
     SET balance_paise = balance_paise + p_amount, updated_at = now()
   WHERE user_id = p_user_id
  RETURNING balance_paise INTO v_balance;
  INSERT INTO public.api_wallet_ledger (user_id, kind, amount_paise, balance_after, payment_id, note)
  VALUES (p_user_id, p_kind, p_amount, v_balance, p_payment_id, p_note);
  RETURN v_balance;
END;
$$;

-- ── 6. Security: owners can READ their own rows; writes via service role/RPCs ─
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_wallet_ledger ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.api_keys, public.api_wallets, public.api_wallet_ledger FROM PUBLIC, anon, authenticated;

DROP POLICY IF EXISTS api_wallets_owner_read ON public.api_wallets;
CREATE POLICY api_wallets_owner_read ON public.api_wallets FOR SELECT TO authenticated
  USING (user_id = auth.uid());
GRANT SELECT ON public.api_wallets TO authenticated;

DROP POLICY IF EXISTS api_ledger_owner_read ON public.api_wallet_ledger;
CREATE POLICY api_ledger_owner_read ON public.api_wallet_ledger FOR SELECT TO authenticated
  USING (user_id = auth.uid());
GRANT SELECT ON public.api_wallet_ledger TO authenticated;
-- api_keys: no client access at all (hashes stay server-side); the backend
-- lists keys through the service role without the hash column.

REVOKE ALL ON FUNCTION public.api_wallet_hold(uuid, uuid, bigint) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.api_wallet_settle(uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.api_wallet_credit(uuid, bigint, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_wallet_hold(uuid, uuid, bigint) TO service_role;
GRANT EXECUTE ON FUNCTION public.api_wallet_settle(uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.api_wallet_credit(uuid, bigint, text, text, text) TO service_role;
