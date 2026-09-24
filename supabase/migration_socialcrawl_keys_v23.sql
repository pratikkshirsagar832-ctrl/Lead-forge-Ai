-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — v23: SocialCrawl API key pool (auto-rotation)
-- Idempotent. Keys are stored ENCRYPTED (Fernet, LINKEDIN_TOKEN_KEY);
-- only the backend service role touches this table.
--
-- The LinkedIn lead engine uses the first usable key; when a key runs out of
-- credits it is marked 'exhausted' and the next key takes over mid-search.
-- Keys are added / removed / checked from /admin/keys.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.socialcrawl_keys (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label              TEXT,
    key_enc            TEXT NOT NULL,
    key_hash           TEXT NOT NULL UNIQUE,          -- sha256(key): dedupe without decrypting
    key_hint           TEXT NOT NULL,                 -- last 4 chars, for display only
    status             TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'exhausted', 'invalid', 'disabled', 'removed')),
    source             TEXT NOT NULL DEFAULT 'admin' CHECK (source IN ('admin', 'env')),
    priority           INTEGER NOT NULL DEFAULT 100,  -- lower = used first
    credits_remaining  INTEGER,
    credits_used       BIGINT NOT NULL DEFAULT 0,
    calls              BIGINT NOT NULL DEFAULT 0,
    last_error         TEXT,
    last_used_at       TIMESTAMPTZ,
    last_checked_at    TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS socialcrawl_keys_status_idx ON public.socialcrawl_keys (status, priority, created_at);

-- Atomic usage counter (called after every search request).
CREATE OR REPLACE FUNCTION public.record_socialcrawl_usage(
    p_id UUID, p_calls INTEGER, p_credits INTEGER, p_remaining INTEGER
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    UPDATE public.socialcrawl_keys
       SET calls = calls + GREATEST(p_calls, 0),
           credits_used = credits_used + GREATEST(p_credits, 0),
           credits_remaining = COALESCE(p_remaining, credits_remaining),
           last_used_at = now(),
           updated_at = now()
     WHERE id = p_id;
$$;

ALTER TABLE public.socialcrawl_keys ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.socialcrawl_keys FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_socialcrawl_usage(UUID, INTEGER, INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
