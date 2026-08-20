-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LINKEDIN INTENT-LEAD SEARCH MIGRATION
-- Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════════

-- ───────────────────────────────────────────────────────────────
-- 1. LINKEDIN SEARCHES (pipeline runs)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.linkedin_searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    enrich_emails BOOLEAN NOT NULL DEFAULT true,
    max_results INTEGER NOT NULL DEFAULT 20 CHECK (max_results >= 1 AND max_results <= 100),
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    progress_percent INTEGER DEFAULT 0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
    message TEXT DEFAULT 'Search queued',
    total_results INTEGER DEFAULT 0 CHECK (total_results >= 0),
    emails_found INTEGER DEFAULT 0 CHECK (emails_found >= 0),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_linkedin_searches_user ON public.linkedin_searches(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_linkedin_searches_status ON public.linkedin_searches(status);

ALTER TABLE public.linkedin_searches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own linkedin searches" ON public.linkedin_searches;
CREATE POLICY "Users can view own linkedin searches"
    ON public.linkedin_searches FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own linkedin searches" ON public.linkedin_searches;
CREATE POLICY "Users can insert own linkedin searches"
    ON public.linkedin_searches FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own linkedin searches" ON public.linkedin_searches;
CREATE POLICY "Users can update own linkedin searches"
    ON public.linkedin_searches FOR UPDATE
    USING (auth.uid() = user_id);

-- ───────────────────────────────────────────────────────────────
-- 2. LINKEDIN LEADS (people who posted they need a service)
-- ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.linkedin_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    search_id UUID REFERENCES public.linkedin_searches(id) ON DELETE CASCADE,
    full_name TEXT DEFAULT '',
    headline TEXT DEFAULT '',
    company TEXT DEFAULT '',
    location TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    post_url TEXT DEFAULT '',
    post_text TEXT DEFAULT '',
    posted_at TIMESTAMPTZ,
    engagement_likes INTEGER DEFAULT 0 CHECK (engagement_likes >= 0),
    engagement_comments INTEGER DEFAULT 0 CHECK (engagement_comments >= 0),
    email TEXT DEFAULT '',
    profile_picture_url TEXT DEFAULT '',
    connections_count INTEGER DEFAULT 0 CHECK (connections_count >= 0),
    user_status TEXT DEFAULT 'new' CHECK (user_status IN ('new', 'contacted', 'replied', 'converted', 'lost')),
    is_favorite BOOLEAN DEFAULT false,
    user_notes TEXT DEFAULT '',
    raw_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, linkedin_url)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_leads_user ON public.linkedin_leads(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_search ON public.linkedin_leads(search_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_status ON public.linkedin_leads(user_id, user_status);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_email ON public.linkedin_leads(email) WHERE email <> '';

ALTER TABLE public.linkedin_leads ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own linkedin leads" ON public.linkedin_leads;
CREATE POLICY "Users can view own linkedin leads"
    ON public.linkedin_leads FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own linkedin leads" ON public.linkedin_leads;
CREATE POLICY "Users can insert own linkedin leads"
    ON public.linkedin_leads FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own linkedin leads" ON public.linkedin_leads;
CREATE POLICY "Users can update own linkedin leads"
    ON public.linkedin_leads FOR UPDATE
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own linkedin leads" ON public.linkedin_leads;
CREATE POLICY "Users can delete own linkedin leads"
    ON public.linkedin_leads FOR DELETE
    USING (auth.uid() = user_id);