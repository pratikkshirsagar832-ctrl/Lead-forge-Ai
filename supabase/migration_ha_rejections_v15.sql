-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v15 — ha_rejections ownership + RLS lockdown
-- Run in the MAIN Supabase project. Idempotent (safe to re-run).
--
-- Why: ha_rejections was created without user_id, FK, RLS or REVOKE, so it
-- was open + unscopable. Telemetry rows now carry the owning user (via the
-- parent ha_searches/searches row), are server-write-only, and owner-readable.
-- ═══════════════════════════════════════════════════════════════

ALTER TABLE public.ha_rejections ADD COLUMN IF NOT EXISTS user_id uuid;
CREATE INDEX IF NOT EXISTS idx_ha_rejections_user ON public.ha_rejections (user_id);

-- Backfill owners from the parent search rows.
UPDATE public.ha_rejections hr
SET user_id = COALESCE(hs.user_id, s.user_id)
FROM public.ha_searches hs
JOIN public.searches s ON s.id = hs.id
WHERE hr.search_id = hs.id
  AND hr.user_id IS NULL
  AND COALESCE(hs.user_id, s.user_id) IS NOT NULL;

ALTER TABLE public.ha_rejections ENABLE ROW LEVEL SECURITY;

-- Server-only writes; owner-scoped reads.
REVOKE INSERT, UPDATE, DELETE ON public.ha_rejections
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.ha_rejections TO authenticated;

DROP POLICY IF EXISTS ha_rejections_own ON public.ha_rejections;
CREATE POLICY ha_rejections_own ON public.ha_rejections
  FOR SELECT USING (user_id = auth.uid());
