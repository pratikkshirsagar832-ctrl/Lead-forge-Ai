-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — SECURITY HARDENING (v8)
-- Apply AFTER migration_post_scraper.sql in the Supabase SQL Editor.
-- Idempotent (safe to run once on a clean or already-migrated project).
--
-- What this fixes (see docs/13 + audit):
--   1. SECURITY DEFINER RPCs were EXECUTE-by-default for PUBLIC/anon/
--      authenticated => anyone with the anon key could insert leads into any
--      user's searches, exhaust victims' counters, read any user's plan/usage.
--      => REVOKE everything except service_role (backend), which bypasses RLS.
--   2. SECURITY DEFINER functions lacked SET search_path (search_path hijack
--      hazard). Recreated hardened with SET search_path = pg_catalog, public
--      and schema-qualified references.
--   3. agent_chat_state / agent_services / ha_searches / ha_leads had NO RLS
--      and default grants => every customer's data readable/writable by anyone
--      with the anon key. ha_* holds ALL users' LinkedIn lead data.
--      => ENABLE RLS, revoke anon/authenticated, and (for ha_*) scope by
--      user_id backfilled from searches.
--   4. user_subscriptions / daily_usage / searches / leads policies were
--      FOR ALL => a signed-in user could self-upgrade to agency, reset quota
--      counters, forge team markers, or attach leads to others' searches.
--      => replace with FOR SELECT only; direct writes belong to the backend
--      (service role), which is exactly how the app already works.
--   5. plans was writable by anon/authenticated => RLS + SELECT-only.
--   6. payment_events table for Razorpay webhook idempotency.
-- ═══════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────
-- 1. REVOKE public execution of every SECURITY DEFINER function.
--    Only service_role may execute these (backend client). The frontend
--    never calls any RPC (verified: Supabase usage is auth-only).
-- ─────────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION public.get_remaining_searches(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_remaining_leads(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_user_subscription(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.increment_daily_usage(uuid, integer, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.upsert_daily_usage(uuid, date, integer, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.create_search(uuid, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.save_lead(jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.get_dashboard_stats(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.reserve_monthly_leads(uuid, text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_monthly_leads(uuid, text, integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.settle_search_monthly_leads(uuid, uuid, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.handle_lead_insert() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.update_subscription_timestamp() FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.get_remaining_searches(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_remaining_leads(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_user_subscription(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.increment_daily_usage(uuid, integer, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.upsert_daily_usage(uuid, date, integer, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.create_search(uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.save_lead(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_dashboard_stats(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.reserve_monthly_leads(uuid, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.settle_monthly_leads(uuid, text, integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.settle_search_monthly_leads(uuid, uuid, integer) TO service_role;

-- ─────────────────────────────────────────────────────────────
-- 2. Hardened SECURITY DEFINER bodies: SET search_path + schema-qualified
--    references, so these can never be redirected by a search_path attack.
-- ─────────────────────────────────────────────────────────────

-- handle_new_user (signup trigger) — canonical v5 behavior: 1-day free trial.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  INSERT INTO public.user_subscriptions (user_id, plan_id, status, trial_end, current_period_end)
  VALUES (NEW.id, 'free', 'trial', now() + interval '1 day', now() + interval '1 day');
  RETURN NEW;
END;
$$;

-- handle_lead_insert (daily leads counter, fired per leads insert).
CREATE OR REPLACE FUNCTION public.handle_lead_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  INSERT INTO public.daily_usage (user_id, date, leads_generated, searches_run)
  VALUES (NEW.user_id, CURRENT_DATE, 1, 0)
  ON CONFLICT (user_id, date)
  DO UPDATE SET leads_generated = public.daily_usage.leads_generated + 1;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.update_subscription_timestamp()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- Read-only helpers (SELECT-capable only).
CREATE OR REPLACE FUNCTION public.get_remaining_searches(p_user_id uuid)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  plan_max integer;
  used_today integer;
BEGIN
  SELECT COALESCE(pl.searches_per_day, 1) INTO plan_max
  FROM public.user_subscriptions us
  JOIN public.plans pl ON us.plan_id = pl.id
  WHERE us.user_id = p_user_id AND us.status IN ('active', 'trial')
  ORDER BY us.created_at DESC
  LIMIT 1;

  SELECT COALESCE(du.searches_run, 0) INTO used_today
  FROM public.daily_usage du
  WHERE du.user_id = p_user_id AND du.date = CURRENT_DATE;

  RETURN GREATEST(0, COALESCE(plan_max, 1) - used_today);
END;
$$;

CREATE OR REPLACE FUNCTION public.get_remaining_leads(p_user_id uuid)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  plan_max integer;
  used_today integer;
BEGIN
  SELECT COALESCE(pl.leads_per_day, 10) INTO plan_max
  FROM public.user_subscriptions us
  JOIN public.plans pl ON us.plan_id = pl.id
  WHERE us.user_id = p_user_id AND us.status IN ('active', 'trial')
  ORDER BY us.created_at DESC
  LIMIT 1;

  SELECT COALESCE(du.leads_generated, 0) INTO used_today
  FROM public.daily_usage du
  WHERE du.user_id = p_user_id AND du.date = CURRENT_DATE;

  RETURN GREATEST(0, COALESCE(plan_max, 10) - used_today);
END;
$$;

CREATE OR REPLACE FUNCTION public.get_user_subscription(p_user_id uuid)
RETURNS json
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  result json;
  row public.user_subscriptions;
BEGIN
  SELECT us.* INTO row
  FROM public.user_subscriptions us
  WHERE us.user_id = p_user_id
  ORDER BY us.created_at DESC
  LIMIT 1;

  IF row.id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT json_build_object(
    'plan_id', row.plan_id,
    'plan_name', pl.name,
    'leads_per_day', pl.leads_per_day,
    'searches_per_day', pl.searches_per_day,
    'status', row.status,
    'trial_end', row.trial_end,
    'current_period_end', row.current_period_end,
    'remaining_searches', public.get_remaining_searches(p_user_id),
    'remaining_leads', public.get_remaining_leads(p_user_id),
    'is_trial_expired',
      CASE WHEN row.trial_end < now() AND row.plan_id = 'free' THEN true ELSE false END
  ) INTO result
  FROM public.plans pl
  WHERE pl.id = row.plan_id;

  RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_dashboard_stats(p_user_id uuid)
RETURNS json
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  total_searches integer;
  total_leads integer;
  hot_leads integer;
  warm_leads integer;
  sub_info json;
BEGIN
  SELECT COUNT(*) INTO total_searches FROM public.searches WHERE user_id = p_user_id;
  SELECT COUNT(*) INTO total_leads FROM public.leads WHERE user_id = p_user_id;
  SELECT COUNT(*) INTO hot_leads FROM public.leads WHERE user_id = p_user_id AND lead_category = 'hot';
  SELECT COUNT(*) INTO warm_leads FROM public.leads WHERE user_id = p_user_id AND lead_category = 'warm';

  sub_info := public.get_user_subscription(p_user_id);

  RETURN json_build_object(
    'total_searches', total_searches,
    'total_leads', total_leads,
    'hot_leads', hot_leads,
    'warm_leads', warm_leads,
    'subscription', sub_info
  );
END;
$$;

CREATE OR REPLACE FUNCTION public.increment_daily_usage(
    p_user_id uuid,
    p_leads integer DEFAULT 0,
    p_searches integer DEFAULT 0,
    p_ai_calls integer DEFAULT 0
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  INSERT INTO public.daily_usage (user_id, date, leads_generated, searches_run, ai_calls)
  VALUES (p_user_id, CURRENT_DATE, p_leads, p_searches, p_ai_calls)
  ON CONFLICT (user_id, date)
  DO UPDATE SET
    leads_generated = public.daily_usage.leads_generated + p_leads,
    searches_run = public.daily_usage.searches_run + p_searches,
    ai_calls = public.daily_usage.ai_calls + p_ai_calls;
END;
$$;

CREATE OR REPLACE FUNCTION public.upsert_daily_usage(
    p_user_id uuid,
    p_date date DEFAULT CURRENT_DATE,
    p_searches integer DEFAULT 0,
    p_leads integer DEFAULT 0,
    p_ai_calls integer DEFAULT 0
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  INSERT INTO public.daily_usage (user_id, date, leads_generated, searches_run, ai_calls)
  VALUES (p_user_id, p_date, p_leads, p_searches, p_ai_calls)
  ON CONFLICT (user_id, date)
  DO UPDATE SET
    leads_generated = public.daily_usage.leads_generated + p_leads,
    searches_run = public.daily_usage.searches_run + p_searches,
    ai_calls = public.daily_usage.ai_calls + p_ai_calls;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_search(
    p_user_id uuid,
    p_niche text,
    p_location text
) RETURNS SETOF public.searches
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  RETURN QUERY
  INSERT INTO public.searches (user_id, niche, location, source, status, progress_percent, message)
  VALUES (p_user_id, p_niche, p_location, 'google_maps', 'queued', 0, 'Search queued')
  RETURNING *;
END;
$$;

CREATE OR REPLACE FUNCTION public.save_lead(p_data jsonb)
RETURNS SETOF public.leads
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  RETURN QUERY
  INSERT INTO public.leads (
    search_id, user_id, google_key, business_name, category,
    full_address, phone, email_found, website_url, rating,
    total_reviews, google_maps_link, photos, business_hours,
    description, lead_category
  ) VALUES (
    (p_data->>'search_id')::uuid,
    (p_data->>'user_id')::uuid,
    COALESCE(p_data->>'google_key', ''),
    COALESCE(p_data->>'business_name', 'Unknown'),
    COALESCE(p_data->>'category', ''),
    COALESCE(p_data->>'full_address', ''),
    COALESCE(p_data->>'phone', ''),
    COALESCE(p_data->>'email_found', ''),
    COALESCE(p_data->>'website_url', ''),
    (p_data->>'rating')::double precision,
    COALESCE((p_data->>'total_reviews')::integer, 0),
    COALESCE(p_data->>'google_maps_link', ''),
    COALESCE(p_data->'photos', '[]'::jsonb),
    COALESCE(p_data->'business_hours', '{}'::jsonb),
    COALESCE(p_data->>'description', ''),
    COALESCE(p_data->>'lead_category', 'warm')
  )
  RETURNING *;
END;
$$;

-- ─────────────────────────────────────────────────────────────
-- 3. RLS: ha_* and agent_* tables were wide open.
--    Backend writes them with the service role (BYPASSRLS), so revoking
--    anon/authenticated and enabling RLS is fully safe for the app.
-- ─────────────────────────────────────────────────────────────
REVOKE ALL ON public.ha_searches, public.ha_leads,
              public.agent_services, public.agent_chat_state
FROM anon, authenticated;

ALTER TABLE public.ha_searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ha_leads   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_services  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_chat_state ENABLE ROW LEVEL SECURITY;

-- Scope ha_* to owners. ha_searches.id doubles as the main searches.id
-- (hyperagent_service seeds the same id), so user_id backfills from searches.
ALTER TABLE public.ha_searches ADD COLUMN IF NOT EXISTS user_id uuid;
ALTER TABLE public.ha_leads   ADD COLUMN IF NOT EXISTS user_id uuid;

UPDATE public.ha_searches hs
SET user_id = s.user_id
FROM public.searches s
WHERE s.id = hs.id AND hs.user_id IS NULL;

UPDATE public.ha_leads hl
SET user_id = s.user_id
FROM public.searches s
JOIN public.ha_searches h ON h.id = hl.search_id
WHERE s.id = h.id AND hl.user_id IS NULL;

DROP POLICY IF EXISTS ha_searches_own ON public.ha_searches;
CREATE POLICY ha_searches_own ON public.ha_searches
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS ha_leads_own ON public.ha_leads;
CREATE POLICY ha_leads_own ON public.ha_leads
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS agent_services_own ON public.agent_services;
CREATE POLICY agent_services_own ON public.agent_services
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

DROP POLICY IF EXISTS agent_chat_state_own ON public.agent_chat_state;
CREATE POLICY agent_chat_state_own ON public.agent_chat_state
  FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- ─────────────────────────────────────────────────────────────
-- 4. Convert per-user tables from FOR ALL to FOR SELECT only. All writes
--    already flow through the backend service role (verified), so end users
--    get read access to their own rows and nothing more.
-- ─────────────────────────────────────────────────────────────
REVOKE INSERT, UPDATE, DELETE ON public.user_subscriptions FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.daily_usage FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.searches FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.leads FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.website_analyses FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.monthly_usage FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.profile_posts FROM anon, authenticated;

DROP POLICY IF EXISTS user_subscriptions_isolation ON public.user_subscriptions;
CREATE POLICY user_subscriptions_isolation ON public.user_subscriptions
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS daily_usage_isolation ON public.daily_usage;
CREATE POLICY daily_usage_isolation ON public.daily_usage
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS searches_isolation ON public.searches;
CREATE POLICY searches_isolation ON public.searches
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS leads_isolation ON public.leads;
CREATE POLICY leads_isolation ON public.leads
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS website_analyses_isolation ON public.website_analyses;
CREATE POLICY website_analyses_isolation ON public.website_analyses
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM public.leads
      WHERE leads.id = website_analyses.lead_id
      AND leads.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS monthly_usage_isolation ON public.monthly_usage;
CREATE POLICY monthly_usage_isolation ON public.monthly_usage
  FOR SELECT USING (user_id = auth.uid());

DROP POLICY IF EXISTS "own profile_posts" ON public.profile_posts;
CREATE POLICY "own profile_posts" ON public.profile_posts
  FOR SELECT USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────
-- 5. plans: reference data — readable, never writable by clients.
-- ─────────────────────────────────────────────────────────────
REVOKE INSERT, UPDATE, DELETE ON public.plans FROM anon, authenticated;
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS plans_read ON public.plans;
CREATE POLICY plans_read ON public.plans FOR SELECT USING (true);

-- ─────────────────────────────────────────────────────────────
-- 6. payment_events — Razorpay webhook idempotency ledger (backend only).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.payment_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id text NOT NULL UNIQUE,
    event_type text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON public.payment_events FROM anon, authenticated;
GRANT SELECT, INSERT ON public.payment_events TO service_role;
ALTER TABLE public.payment_events ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────
-- 7. Missing hot-path indexes.
-- ─────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_leads_user_created ON public.leads(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_user_status2 ON public.leads(user_id, user_status);
CREATE INDEX IF NOT EXISTS idx_leads_user_fav ON public.leads(user_id, is_favorite) WHERE is_favorite;
CREATE INDEX IF NOT EXISTS idx_ha_leads_search_date ON public.ha_leads(search_id, post_date DESC);
CREATE INDEX IF NOT EXISTS idx_ha_leads_user ON public.ha_leads(user_id);
CREATE INDEX IF NOT EXISTS idx_ha_searches_user ON public.ha_searches(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_name_trgm ON public.leads USING GIN (business_name gin_trgm_ops);
