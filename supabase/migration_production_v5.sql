-- HYPERCLIENTS production migration v5
-- Apply after migration_linkedin_v4.sql. This migration is additive and keeps
-- historical daily_usage rows intact for reporting only.

ALTER TABLE public.plans
    ADD COLUMN IF NOT EXISTS linkedin_hq_leads_monthly INTEGER NOT NULL DEFAULT 0 CHECK (linkedin_hq_leads_monthly >= 0),
    ADD COLUMN IF NOT EXISTS gmb_leads_monthly INTEGER NOT NULL DEFAULT 0 CHECK (gmb_leads_monthly >= 0),
    ADD COLUMN IF NOT EXISTS billing_cycle_days INTEGER NOT NULL DEFAULT 30 CHECK (billing_cycle_days > 0),
    ADD COLUMN IF NOT EXISTS features JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Amounts are USD cents; Razorpay INR amounts must be configured server-side
-- from an explicit product price, never a stale exchange-rate calculation.
UPDATE public.plans SET
    name = CASE id WHEN 'free' THEN 'Free' WHEN 'solo' THEN 'Solo' WHEN 'pro' THEN 'Pro' WHEN 'agency' THEN 'Agency' ELSE name END,
    price_monthly = CASE id WHEN 'free' THEN 0 WHEN 'solo' THEN 1900 WHEN 'pro' THEN 9900 WHEN 'agency' THEN 29900 ELSE price_monthly END,
    linkedin_hq_leads_monthly = CASE id WHEN 'free' THEN 3 WHEN 'solo' THEN 20 WHEN 'pro' THEN 120 WHEN 'agency' THEN 400 ELSE linkedin_hq_leads_monthly END,
    gmb_leads_monthly = CASE id WHEN 'free' THEN 30 WHEN 'solo' THEN 200 WHEN 'pro' THEN 1500 WHEN 'agency' THEN 6000 ELSE gmb_leads_monthly END,
    trial_days = CASE WHEN id = 'free' THEN 1 ELSE 0 END,
    billing_cycle_days = 30,
    features = CASE id
      WHEN 'free' THEN '["Lead management","Website analysis"]'::jsonb
      WHEN 'solo' THEN '["Lead management","Website analysis","AI pitch generation"]'::jsonb
      WHEN 'pro' THEN '["CSV export","Team access","Priority support"]'::jsonb
      WHEN 'agency' THEN '["CSV export","Team access","API access","Dedicated support"]'::jsonb
      ELSE features END
WHERE id IN ('free','solo','pro','agency');

CREATE TABLE IF NOT EXISTS public.monthly_usage (
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    usage_month DATE NOT NULL,
    linkedin_hq_generated INTEGER NOT NULL DEFAULT 0 CHECK (linkedin_hq_generated >= 0),
    linkedin_hq_reserved INTEGER NOT NULL DEFAULT 0 CHECK (linkedin_hq_reserved >= 0),
    gmb_generated INTEGER NOT NULL DEFAULT 0 CHECK (gmb_generated >= 0),
    gmb_reserved INTEGER NOT NULL DEFAULT 0 CHECK (gmb_reserved >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, usage_month)
);
ALTER TABLE public.monthly_usage ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS monthly_usage_isolation ON public.monthly_usage;
CREATE POLICY monthly_usage_isolation ON public.monthly_usage FOR SELECT USING (user_id = auth.uid());

ALTER TABLE public.searches
    ADD COLUMN IF NOT EXISTS quota_source TEXT CHECK (quota_source IN ('linkedin','google_maps')),
    ADD COLUMN IF NOT EXISTS reserved_leads INTEGER NOT NULL DEFAULT 0 CHECK (reserved_leads >= 0),
    ADD COLUMN IF NOT EXISTS quota_settled_at TIMESTAMPTZ;

ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_post_type_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_post_type_check
    CHECK (post_type IN ('buyer', 'agency', 'agency_wanted', 'hiring', 'job_seeker', 'unknown'));
ALTER TABLE public.searches ALTER COLUMN lead_types SET DEFAULT ARRAY['buyer','hiring']::TEXT[];

-- Atomically reserve capacity. The caller is server-side and supplies the
-- effective plan resolved from the subscription, never the browser.
CREATE OR REPLACE FUNCTION public.reserve_monthly_leads(
    p_user_id UUID, p_plan_id TEXT, p_source TEXT, p_amount INTEGER
) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  month_start DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
  limit_value INTEGER;
  used_value INTEGER;
BEGIN
  IF p_source NOT IN ('linkedin','google_maps') OR p_amount < 1 THEN
    RAISE EXCEPTION 'invalid quota reservation';
  END IF;
  SELECT CASE WHEN p_source = 'linkedin' THEN linkedin_hq_leads_monthly ELSE gmb_leads_monthly END
  INTO limit_value FROM plans WHERE id = p_plan_id AND is_active = true;
  IF limit_value IS NULL THEN RAISE EXCEPTION 'plan unavailable'; END IF;
  INSERT INTO monthly_usage (user_id, usage_month) VALUES (p_user_id, month_start)
  ON CONFLICT (user_id, usage_month) DO NOTHING;
  PERFORM 1 FROM monthly_usage WHERE user_id = p_user_id AND usage_month = month_start FOR UPDATE;
  SELECT CASE WHEN p_source = 'linkedin' THEN linkedin_hq_generated + linkedin_hq_reserved ELSE gmb_generated + gmb_reserved END
  INTO used_value FROM monthly_usage WHERE user_id = p_user_id AND usage_month = month_start;
  IF used_value + p_amount > limit_value THEN
    RETURN GREATEST(0, limit_value - used_value);
  END IF;
  UPDATE monthly_usage SET
    linkedin_hq_reserved = linkedin_hq_reserved + CASE WHEN p_source = 'linkedin' THEN p_amount ELSE 0 END,
    gmb_reserved = gmb_reserved + CASE WHEN p_source = 'google_maps' THEN p_amount ELSE 0 END,
    updated_at = now()
  WHERE user_id = p_user_id AND usage_month = month_start;
  RETURN -1;
END;
$$;

CREATE OR REPLACE FUNCTION public.settle_monthly_leads(
    p_user_id UUID, p_source TEXT, p_reserved INTEGER, p_generated INTEGER
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE month_start DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
BEGIN
  IF p_source NOT IN ('linkedin','google_maps') OR p_reserved < 0 OR p_generated < 0 OR p_generated > p_reserved THEN
    RAISE EXCEPTION 'invalid quota settlement';
  END IF;
  UPDATE monthly_usage SET
    linkedin_hq_reserved = linkedin_hq_reserved - CASE WHEN p_source = 'linkedin' THEN p_reserved ELSE 0 END,
    linkedin_hq_generated = linkedin_hq_generated + CASE WHEN p_source = 'linkedin' THEN p_generated ELSE 0 END,
    gmb_reserved = gmb_reserved - CASE WHEN p_source = 'google_maps' THEN p_reserved ELSE 0 END,
    gmb_generated = gmb_generated + CASE WHEN p_source = 'google_maps' THEN p_generated ELSE 0 END,
    updated_at = now()
  WHERE user_id = p_user_id AND usage_month = month_start;
END;
$$;

CREATE OR REPLACE FUNCTION public.settle_search_monthly_leads(
    p_search_id UUID, p_user_id UUID, p_generated INTEGER
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  search_row public.searches%ROWTYPE;
  month_start DATE := date_trunc('month', now() AT TIME ZONE 'UTC')::date;
BEGIN
  SELECT * INTO search_row FROM searches WHERE id = p_search_id FOR UPDATE;
  IF NOT FOUND OR search_row.quota_settled_at IS NOT NULL OR search_row.reserved_leads = 0 THEN RETURN; END IF;
  IF p_generated < 0 OR p_generated > search_row.reserved_leads THEN RAISE EXCEPTION 'invalid search settlement'; END IF;
  UPDATE monthly_usage SET
    linkedin_hq_reserved = linkedin_hq_reserved - CASE WHEN search_row.quota_source = 'linkedin' THEN search_row.reserved_leads ELSE 0 END,
    linkedin_hq_generated = linkedin_hq_generated + CASE WHEN search_row.quota_source = 'linkedin' THEN p_generated ELSE 0 END,
    gmb_reserved = gmb_reserved - CASE WHEN search_row.quota_source = 'google_maps' THEN search_row.reserved_leads ELSE 0 END,
    gmb_generated = gmb_generated + CASE WHEN search_row.quota_source = 'google_maps' THEN p_generated ELSE 0 END,
    updated_at = now()
  WHERE user_id = p_user_id AND usage_month = month_start;
  UPDATE searches SET quota_settled_at = now() WHERE id = p_search_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
  INSERT INTO public.user_subscriptions (user_id, plan_id, status, trial_end, current_period_end)
  VALUES (NEW.id, 'free', 'trial', now() + interval '1 day', now() + interval '1 day');
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.reserve_monthly_leads(UUID, TEXT, TEXT, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.settle_monthly_leads(UUID, TEXT, TEXT, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.settle_search_monthly_leads(UUID, UUID, INTEGER) FROM PUBLIC;
