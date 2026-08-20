-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LINKEDIN INTENT SEARCH v2 (UNIFIED FLOW)
-- LinkedIn searches now live in the SAME searches/leads tables as
-- Google Maps, tagged with source = 'google_maps' | 'linkedin'
-- Run this in Supabase SQL Editor (AFTER migration_linkedin.sql)
-- ═══════════════════════════════════════════════════════════════

-- 1. searches: add LinkedIn-specific columns
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS enrich_emails BOOLEAN DEFAULT false;
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS max_results INTEGER DEFAULT 20 CHECK (max_results >= 1 AND max_results <= 50);
ALTER TABLE public.searches ADD COLUMN IF NOT EXISTS emails_found INTEGER DEFAULT 0 CHECK (emails_found >= 0);

-- 2. leads: add source tag + LinkedIn person fields
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'google_maps';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS linkedin_url TEXT DEFAULT '';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS post_url TEXT DEFAULT '';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS post_text TEXT DEFAULT '';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS headline TEXT DEFAULT '';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS profile_picture_url TEXT DEFAULT '';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS connections_count INTEGER DEFAULT 0 CHECK (connections_count >= 0);
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_leads_source ON public.leads(user_id, source);
CREATE INDEX IF NOT EXISTS idx_leads_linkedin_url ON public.leads(user_id, linkedin_url) WHERE linkedin_url <> '';

-- 3. cleanup: drop the standalone LinkedIn tables (superseded by unified flow)
DROP TABLE IF EXISTS public.linkedin_leads;
DROP TABLE IF EXISTS public.linkedin_searches;