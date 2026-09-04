-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — PROFILE PUBLIC POSTS (post-scraper actor output)
-- One row per PUBLIC post scraped from a LinkedIn profile (or verified
-- from a direct post URL). Data comes from the in-house Apify actor
-- "linkedin-post-scraper" (public pages only; honest access-restriction
-- classification — never proxied/bypassed).
-- Run after migration.sql (+ v2..v7 + hyperagent) in the SQL Editor.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.profile_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Optional owner lead (when scraped from the lead detail page).
    lead_id UUID REFERENCES public.leads(id) ON DELETE SET NULL,
    -- Profile the post was scraped from (actor sourceUrl / input URL).
    profile_url TEXT NOT NULL DEFAULT '',
    -- Canonical LinkedIn post URL ('' only when the actor could not resolve
    -- one — extraction_status then explains why; never a substitute URL).
    post_url TEXT NOT NULL DEFAULT '',
    post_id TEXT DEFAULT '',
    post_text TEXT DEFAULT '',
    author_name TEXT DEFAULT '',
    author_url TEXT DEFAULT '',
    author_headline TEXT DEFAULT '',
    author_type TEXT NOT NULL DEFAULT 'unknown'
        CHECK (author_type IN ('person', 'company', 'unknown')),
    posted_at TIMESTAMPTZ,
    num_likes INTEGER CHECK (num_likes IS NULL OR num_likes >= 0),
    num_comments INTEGER CHECK (num_comments IS NULL OR num_comments >= 0),
    num_shares INTEGER CHECK (num_shares IS NULL OR num_shares >= 0),
    hashtags JSONB DEFAULT '[]'::jsonb,
    mentions JSONB DEFAULT '[]'::jsonb,
    media JSONB DEFAULT '[]'::jsonb,
    -- success | partial | failed | unresolved
    extraction_status TEXT NOT NULL DEFAULT 'success'
        CHECK (extraction_status IN ('success', 'partial', 'failed', 'unresolved')),
    extraction_method TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    extracted_at TIMESTAMPTZ,
    raw JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One profile post per user (idempotent re-scrapes upsert instead of duping).
CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_posts_user_post
    ON public.profile_posts (user_id, post_url) WHERE post_url <> '';

CREATE INDEX IF NOT EXISTS idx_profile_posts_user_created
    ON public.profile_posts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_profile_posts_lead
    ON public.profile_posts (lead_id);
CREATE INDEX IF NOT EXISTS idx_profile_posts_profile
    ON public.profile_posts (profile_url);

ALTER TABLE public.profile_posts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own profile_posts" ON public.profile_posts;
CREATE POLICY "own profile_posts"
    ON public.profile_posts
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
