-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LINKEDIN STUDIO v21 (AI posting + scheduling via
-- LinkedIn's OFFICIAL API). Apply after migration_public_api_v20.sql.
-- Idempotent (safe to re-run).
--
--   1. linkedin_accounts   — connected profiles / company pages
--                            (OAuth tokens encrypted by the backend)
--   2. linkedin_posts      — drafts, schedule queue, publish history
--   3. linkedin_autopilot  — per-user autopilot settings (opt-in)
--   4. plans.linkedin_posts_monthly + monthly_usage.linkedin_posts_used
--   5. RPCs: claim_due_linkedin_posts, consume_linkedin_post_quota
--   6. Storage bucket linkedin-media (private)
-- ═══════════════════════════════════════════════════════════════

-- ── 1. Connected LinkedIn accounts ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.linkedin_accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL CHECK (kind IN ('person', 'organization')),
    urn                 TEXT NOT NULL,              -- urn:li:person:… / urn:li:organization:…
    name                TEXT,
    avatar_url          TEXT,
    app                 TEXT NOT NULL DEFAULT 'member' CHECK (app IN ('member', 'pages')),
    access_token_enc    TEXT NOT NULL,              -- Fernet ciphertext, never plaintext
    refresh_token_enc   TEXT,
    expires_at          TIMESTAMPTZ,
    refresh_expires_at  TIMESTAMPTZ,
    scopes              TEXT,
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'revoked')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, urn)
);
CREATE INDEX IF NOT EXISTS idx_li_accounts_user ON public.linkedin_accounts (user_id);

-- ── 2. Posts: drafts → schedule → publish ────────────────────────
CREATE TABLE IF NOT EXISTS public.linkedin_posts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    account_id         UUID REFERENCES public.linkedin_accounts(id) ON DELETE SET NULL,
    status             TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
                          'draft', 'scheduled', 'publishing', 'published',
                          'failed', 'needs_reconnect', 'cancelled')),
    commentary         TEXT NOT NULL DEFAULT '' CHECK (char_length(commentary) <= 3000),
    media              JSONB NOT NULL DEFAULT '[]'::jsonb,
    visibility         TEXT NOT NULL DEFAULT 'PUBLIC' CHECK (visibility IN ('PUBLIC', 'CONNECTIONS')),
    scheduled_at       TIMESTAMPTZ,
    published_at       TIMESTAMPTZ,
    linkedin_post_urn  TEXT,
    post_url           TEXT,
    error              TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    next_attempt_at    TIMESTAMPTZ,
    source             TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'ai', 'autopilot')),
    ai_meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_li_posts_due ON public.linkedin_posts (status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_li_posts_user ON public.linkedin_posts (user_id, scheduled_at DESC);

-- ── 3. Autopilot (opt-in) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.linkedin_autopilot (
    user_id         UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    enabled         BOOLEAN NOT NULL DEFAULT false,
    auto_approve    BOOLEAN NOT NULL DEFAULT false,   -- true = posts WITHOUT manual approval
    consent_at      TIMESTAMPTZ,                      -- when the user accepted autopilot terms
    account_id      UUID REFERENCES public.linkedin_accounts(id) ON DELETE SET NULL,
    timezone        TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    slots           JSONB NOT NULL DEFAULT '[]'::jsonb, -- [{"dow":1,"time":"09:30"}] (0=Mon)
    pillars         TEXT[] NOT NULL DEFAULT '{}',
    audience        TEXT,
    voice_profile   TEXT,
    lookahead_days  INTEGER NOT NULL DEFAULT 7 CHECK (lookahead_days BETWEEN 1 AND 14),
    last_planned_at TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 4. Plan limits + monthly usage ───────────────────────────────
ALTER TABLE public.plans ADD COLUMN IF NOT EXISTS linkedin_posts_monthly INTEGER NOT NULL DEFAULT 0
    CHECK (linkedin_posts_monthly >= 0);
UPDATE public.plans SET linkedin_posts_monthly = CASE id
    WHEN 'pro' THEN 60 WHEN 'agency' THEN 200 ELSE 0 END
 WHERE linkedin_posts_monthly = 0;
ALTER TABLE public.monthly_usage ADD COLUMN IF NOT EXISTS linkedin_posts_used INTEGER NOT NULL DEFAULT 0;

-- ── 5a. Claim due posts exactly once (safe with many workers) ─────
CREATE OR REPLACE FUNCTION public.claim_due_linkedin_posts(p_limit integer DEFAULT 10)
RETURNS SETOF public.linkedin_posts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  RETURN QUERY
  UPDATE public.linkedin_posts p
     SET status = 'publishing', attempts = p.attempts + 1, updated_at = now()
   WHERE p.id IN (
         SELECT id FROM public.linkedin_posts
          WHERE status = 'scheduled'
            AND scheduled_at <= now()
            AND (next_attempt_at IS NULL OR next_attempt_at <= now())
          ORDER BY scheduled_at
          LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 10), 50))
          FOR UPDATE SKIP LOCKED)
  RETURNING p.*;
END;
$$;

-- ── 5b. Monthly post quota (atomic) ──────────────────────────────
-- Returns -1 when a unit was consumed, otherwise the remaining allowance (0).
CREATE OR REPLACE FUNCTION public.consume_linkedin_post_quota(p_user_id uuid, p_limit integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_month date := date_trunc('month', now())::date;
  cur integer;
BEGIN
  IF p_limit IS NULL OR p_limit <= 0 THEN
    RETURN 0;
  END IF;
  INSERT INTO public.monthly_usage (user_id, usage_month)
  VALUES (p_user_id, v_month)
  ON CONFLICT (user_id, usage_month) DO NOTHING;
  SELECT linkedin_posts_used INTO cur FROM public.monthly_usage
   WHERE user_id = p_user_id AND usage_month = v_month FOR UPDATE;
  cur := COALESCE(cur, 0);
  IF cur >= p_limit THEN
    RETURN GREATEST(0, p_limit - cur);
  END IF;
  UPDATE public.monthly_usage SET linkedin_posts_used = cur + 1
   WHERE user_id = p_user_id AND usage_month = v_month;
  RETURN -1;
END;
$$;

-- ── 6. Security ──────────────────────────────────────────────────
ALTER TABLE public.linkedin_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.linkedin_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.linkedin_autopilot ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.linkedin_accounts, public.linkedin_posts, public.linkedin_autopilot
    FROM PUBLIC, anon, authenticated;
-- Posts + autopilot are readable by their owner; accounts (token ciphertext)
-- are backend-only.
DROP POLICY IF EXISTS li_posts_owner_read ON public.linkedin_posts;
CREATE POLICY li_posts_owner_read ON public.linkedin_posts FOR SELECT TO authenticated
  USING (user_id = auth.uid());
GRANT SELECT ON public.linkedin_posts TO authenticated;
DROP POLICY IF EXISTS li_autopilot_owner_read ON public.linkedin_autopilot;
CREATE POLICY li_autopilot_owner_read ON public.linkedin_autopilot FOR SELECT TO authenticated
  USING (user_id = auth.uid());
GRANT SELECT ON public.linkedin_autopilot TO authenticated;

REVOKE ALL ON FUNCTION public.claim_due_linkedin_posts(integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consume_linkedin_post_quota(uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_due_linkedin_posts(integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.consume_linkedin_post_quota(uuid, integer) TO service_role;

-- ── 7. Private media bucket (images / PDFs before upload to LinkedIn) ─
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('linkedin-media', 'linkedin-media', false, 104857600)
ON CONFLICT (id) DO NOTHING;
