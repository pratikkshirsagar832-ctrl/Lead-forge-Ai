-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LINKEDIN POST TYPE TAGGING (v3)
-- Tags LinkedIn leads with post classification:
--   buyer (person needs the service) / agency (sells it) / hiring / job_seeker
-- Run this in Supabase SQL Editor (AFTER migration_linkedin_v2.sql)
-- ═══════════════════════════════════════════════════════════════

ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS post_type TEXT DEFAULT 'unknown'
    CHECK (post_type IN ('buyer', 'agency', 'hiring', 'job_seeker', 'unknown'));

CREATE INDEX IF NOT EXISTS idx_leads_post_type ON public.leads(user_id, post_type);