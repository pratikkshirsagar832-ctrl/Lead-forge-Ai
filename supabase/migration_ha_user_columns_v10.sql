-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v10 — LinkedIn CRM parity for ha_leads
-- The frontend PATCHes status/notes/favorite for BOTH lead sources;
-- ha_leads previously had no user columns, so every LinkedIn CRM
-- action 404'd. This adds the columns the API now writes.
-- Run in MAIN Supabase project. Idempotent.
-- ═══════════════════════════════════════════════════════════════

-- User-owned columns (mirror the `leads` table semantics).
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS user_status text;
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS user_notes text;
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS is_favorite boolean NOT NULL DEFAULT false;

-- On-demand AI pitch results (POST /api/ai/pitch/{lead_id} writes these for
-- LinkedIn leads the same way it writes them for Maps leads).
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS ai_pitch text;
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS ai_confidence_score numeric;

-- Backfill: engine rows default to 'new' (their `status` column already
-- carries that value); existing rows get the same so filters behave.
UPDATE public.ha_leads SET user_status = 'new' WHERE user_status IS NULL;

-- Filter performance on the two user-facing filters.
CREATE INDEX IF NOT EXISTS idx_ha_leads_user_status ON public.ha_leads (user_status);
CREATE INDEX IF NOT EXISTS idx_ha_leads_is_favorite ON public.ha_leads (is_favorite);
