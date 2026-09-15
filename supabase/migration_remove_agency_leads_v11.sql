-- HYPERCLIENTS migration v11: remove agency leads + Pro $99 -> $49
-- Agency PLAN stays. Only agency lead-types are removed.
-- Run in Supabase SQL Editor. Idempotent (IF EXISTS / WHERE filters).

-- 1. Pro $99 -> $49 (USD cents). Agency plan untouched.
UPDATE public.plans SET price_monthly = 4900 WHERE id = 'pro';

-- 2. Normalize historical agency lead-types to buyer equivalents.
-- leads.post_type: agency/agency_wanted -> buyer
UPDATE public.leads SET post_type = 'buyer'
WHERE post_type IN ('agency', 'agency_wanted');

-- searches.lead_types arrays: replace agency_wanted with buyer, dedupe
UPDATE public.searches
SET lead_types = (
  SELECT array_agg(DISTINCT x ORDER BY x)
  FROM unnest(array_replace(lead_types, 'agency_wanted', 'buyer')) AS x
)
WHERE lead_types && ARRAY['agency_wanted']::text[];
UPDATE public.searches SET lead_types = ARRAY['buyer']::text[]
WHERE lead_types IS NULL OR lead_types = '{}'::text[];

-- ha engine tables: our_agency -> need_freelancer
UPDATE public.ha_leads SET lead_type = 'need_freelancer'
WHERE lead_type = 'our_agency';
UPDATE public.ha_searches SET lead_type = 'need_freelancer'
WHERE lead_type = 'our_agency';

-- 3. Tighten CHECKs to buyer-only (drop agency variants).
ALTER TABLE public.leads DROP CONSTRAINT IF EXISTS leads_post_type_check;
ALTER TABLE public.leads ADD CONSTRAINT leads_post_type_check
    CHECK (post_type IN ('buyer', 'hiring', 'job_seeker', 'unknown'));

ALTER TABLE public.searches ALTER COLUMN lead_types SET DEFAULT ARRAY['buyer']::TEXT[];

ALTER TABLE public.ha_leads DROP CONSTRAINT IF EXISTS ha_leads_lead_type_check;
ALTER TABLE public.ha_leads ADD CONSTRAINT ha_leads_lead_type_check
    CHECK (lead_type IN ('need_freelancer'));

ALTER TABLE public.ha_searches DROP CONSTRAINT IF EXISTS ha_searches_lead_type_check;
ALTER TABLE public.ha_searches ADD CONSTRAINT ha_searches_lead_type_check
    CHECK (lead_type IN ('need_freelancer'));
