-- ═══════════════════════════════════════════════════════════════
-- OBSERVABILITY + SAFETY-NET COLUMNS (Tier 0 / Tier 1 of the audit
-- fix). Run this whole file in the Supabase SQL editor once.
-- All statements are idempotent / existence-guarded.
-- ═══════════════════════════════════════════════════════════════

-- Rejected-candidate telemetry (per post that REACHED the classifier and was
-- rejected). Kept on a rolling 14-day window by the backend.
CREATE TABLE IF NOT EXISTS public.ha_rejections (
  id uuid primary key default gen_random_uuid(),
  search_id uuid,
  post_url text,
  post_text text,
  lead_type_verdict text,
  reason text,
  evidence text,
  accepted boolean,
  is_qualified boolean,
  created_at timestamptz not null default now()
);
CREATE INDEX IF NOT EXISTS idx_ha_rejections_created_at ON public.ha_rejections (created_at);
CREATE INDEX IF NOT EXISTS idx_ha_rejections_search_id ON public.ha_rejections (search_id);

-- Per-search spend counters + stop reason (written by the engine; surfaced in
-- the search-status API).
ALTER TABLE public.ha_searches
  ADD COLUMN IF NOT EXISTS serper_requests_used integer not null default 0;
ALTER TABLE public.ha_searches
  ADD COLUMN IF NOT EXISTS deepseek_calls_used integer not null default 0;
ALTER TABLE public.ha_searches
  ADD COLUMN IF NOT EXISTS stop_reason text;
