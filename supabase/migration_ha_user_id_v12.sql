-- ═══════════════════════════════════════════════════════════════
-- MIGRATION v12 — LinkedIn engine row ownership (ha_searches / ha_leads)
-- Run in the MAIN Supabase project AFTER migration_security_v8.sql.
-- Idempotent (safe to re-run).
--
-- Why: v8 added `user_id` to ha_searches/ha_leads, backfilled the rows that
-- existed then, and put owner-scoped RLS policies on both tables
-- (`USING (user_id = auth.uid())`). Every row created AFTER v8 was written by
-- the engine without a user_id, so those rows are NULL-owned: invisible to any
-- policy-scoped client, and impossible to attribute to a user.
--
-- This migration:
--   1. (Re)creates the columns + indexes if a deployment skipped v8.
--   2. Re-backfills every NULL owner from the owning `searches` row.
--   3. Adds a BEFORE INSERT trigger so ownership is self-healing at the
--      database even if an older backend build writes the rows.
-- The application now also stamps user_id on insert (authoritative path).
-- ═══════════════════════════════════════════════════════════════

-- 1. Columns + indexes (no-ops when v8 already ran) ───────────────────
ALTER TABLE public.ha_searches ADD COLUMN IF NOT EXISTS user_id uuid;
ALTER TABLE public.ha_leads    ADD COLUMN IF NOT EXISTS user_id uuid;
CREATE INDEX IF NOT EXISTS idx_ha_leads_user ON public.ha_leads (user_id);
CREATE INDEX IF NOT EXISTS idx_ha_searches_user ON public.ha_searches (user_id);
ALTER TABLE public.ha_searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ha_leads    ENABLE ROW LEVEL SECURITY;

-- 2. Re-backfill NULL owners ──────────────────────────────────────────
-- ha_searches.id is seeded with the main searches.id, so the owner is known.
UPDATE public.ha_searches hs
SET user_id = s.user_id
FROM public.searches s
WHERE s.id = hs.id
  AND hs.user_id IS NULL
  AND s.user_id IS NOT NULL;

-- ha_leads has no user_id of its own; it inherits from its search row
-- (falling back to the main searches row when ha_searches.user_id is still
-- NULL on a very old deployment).
UPDATE public.ha_leads hl
SET user_id = COALESCE(hs.user_id, s.user_id)
FROM public.ha_searches hs
JOIN public.searches s ON s.id = hs.id
WHERE hl.search_id = hs.id
  AND hl.user_id IS NULL
  AND COALESCE(hs.user_id, s.user_id) IS NOT NULL;

-- 3. Self-healing trigger ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.ha_leads_set_user_id()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF NEW.user_id IS NULL AND NEW.search_id IS NOT NULL THEN
    SELECT COALESCE(hs.user_id, s.user_id)
    INTO NEW.user_id
    FROM public.ha_searches hs
    JOIN public.searches s ON s.id = hs.id
    WHERE hs.id = NEW.search_id;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ha_leads_set_user_id_trg ON public.ha_leads;
CREATE TRIGGER ha_leads_set_user_id_trg
  BEFORE INSERT ON public.ha_leads
  FOR EACH ROW EXECUTE FUNCTION public.ha_leads_set_user_id();

-- Only the backend (service role) may write these tables.
REVOKE INSERT, UPDATE, DELETE ON public.ha_searches, public.ha_leads
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.ha_searches, public.ha_leads TO authenticated;

-- Owner-scoped read policies (idempotent re-create).
DROP POLICY IF EXISTS ha_searches_own ON public.ha_searches;
CREATE POLICY ha_searches_own ON public.ha_searches
  FOR SELECT USING (user_id = auth.uid());
DROP POLICY IF EXISTS ha_leads_own ON public.ha_leads;
CREATE POLICY ha_leads_own ON public.ha_leads
  FOR SELECT USING (user_id = auth.uid());
