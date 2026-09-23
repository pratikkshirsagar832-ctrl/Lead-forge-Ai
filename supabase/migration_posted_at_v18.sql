-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — EXACT POST TIME v18 (latest-first LinkedIn leads)
-- Apply AFTER migration_need_agency_v17.sql in the Supabase SQL Editor.
-- Idempotent.
--
-- What this does:
--   Adds ha_leads.posted_at (timestamptz): the EXACT publish time of the
--   LinkedIn post, decoded from the activity id in its URL. `post_date`
--   (day precision) stays for existing filters. The backend writes
--   posted_at only once this column exists (probed at insert time), so
--   applying this migration late never loses a lead.
-- ═══════════════════════════════════════════════════════════════

ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS posted_at timestamptz;

-- Backfill from the day-level date so older rows still sort sensibly.
UPDATE public.ha_leads
   SET posted_at = post_date::timestamptz
 WHERE posted_at IS NULL AND post_date IS NOT NULL;

-- Newest-first listing per search / per owner.
CREATE INDEX IF NOT EXISTS ha_leads_search_posted_at_idx
  ON public.ha_leads (search_id, posted_at DESC);

-- EXACT-N: post_url was unique across ALL users, so a post another account
-- already saved was silently skipped on insert and the search delivered
-- fewer leads than requested. Make it unique PER USER instead. The backend
-- upserts with on_conflict (user_id, post_url) and falls back to post_url
-- automatically until this migration is applied.
ALTER TABLE public.ha_leads DROP CONSTRAINT IF EXISTS ha_leads_post_url_key;
CREATE UNIQUE INDEX IF NOT EXISTS ha_leads_user_post_url_key
  ON public.ha_leads (user_id, post_url);
CREATE INDEX IF NOT EXISTS ha_leads_post_url_idx ON public.ha_leads (post_url);
