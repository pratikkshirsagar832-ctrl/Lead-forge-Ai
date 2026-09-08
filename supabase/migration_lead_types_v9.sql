-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LEAD-TYPE MODEL v9 (two requestable buyer types)
-- Apply AFTER migration_security_v8.sql in the Supabase SQL Editor.
-- Idempotent.
--
-- What this does:
--   1. Removes `hiring_buyer` from the product. Exactly two buyer types are
--      requestable: need_freelancer (someone needs an independent freelancer
--      for their own project/company) and our_agency (an agency wants outside
--      freelance help). Employee job-ads are never leads.
--   2. Retags any existing ha_* rows tagged `hiring_buyer`: those posts
--      describe a business hiring a freelancer/contractor for a defined piece
--      of work — semantically need_freelancer (freelance/contract hire), not
--      an employee job-ad. (job-seeker/job-ad rows were never saved by the
--      engine, which only persists accepted buyers.)
--   3. Recreates the ha_searches/ha_leads lead_type CHECK constraints with
--      only the two live values.
--   4. Comment-count ceiling support (configurable "max comments on post"):
--      num_comments on ha_leads and max_comments_allowed on ha_searches.
--      When a discovery provider supplies comment counts, the engine drops
--      posts above the ceiling as low-competition candidates.
-- ═══════════════════════════════════════════════════════════════

-- ── 1. ha_searches.lead_type constraint --------------------------------
ALTER TABLE public.ha_searches DROP CONSTRAINT IF EXISTS ha_searches_lead_type_check;
ALTER TABLE public.ha_searches ADD CONSTRAINT ha_searches_lead_type_check
  CHECK (lead_type IN ('need_freelancer', 'our_agency'));

-- ── 2. ha_leads.lead_type constraint + retag existing rows ---------------
UPDATE public.ha_leads
SET lead_type = 'need_freelancer'
WHERE lead_type = 'hiring_buyer';

ALTER TABLE public.ha_leads DROP CONSTRAINT IF EXISTS ha_leads_lead_type_check;
ALTER TABLE public.ha_leads ADD CONSTRAINT ha_leads_lead_type_check
  CHECK (lead_type IN ('need_freelancer', 'our_agency'));

-- ── 3. Comment-count ceiling columns -------------------------------------
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS num_comments integer
  CHECK (num_comments IS NULL OR num_comments >= 0);

ALTER TABLE public.ha_searches ADD COLUMN IF NOT EXISTS max_comments_allowed integer
  CHECK (max_comments_allowed IS NULL OR max_comments_allowed >= 0);

-- ── 4. lead_type for the old standalone `leads` rows ---------------------
-- The unified `leads` table historically allowed post_type='hiring' /
-- 'job_seeker' etc. from the retired LinkedIn pipeline. Product-level hiring
-- is gone; existing rows keep their historical label (no destructive
-- rewrite) but the value is no longer produced by any code path.
