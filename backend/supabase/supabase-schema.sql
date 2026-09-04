-- ============================================================================
-- LeadForge AI — Complete Supabase Schema
-- Run this ENTIRE script in your Supabase SQL Editor (one go).
-- ============================================================================

-- ── 0. Extensions ──────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;


-- ── 1. Users Table ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL DEFAULT 'default@local.dev',
    name          TEXT NOT NULL DEFAULT '',
    avatar_url    TEXT NOT NULL DEFAULT '',
    auth_provider TEXT NOT NULL DEFAULT 'local',
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed the default user (used when auth is disabled)
INSERT INTO public.users (id, email, name)
VALUES ('00000000-0000-0000-0000-000000000001', 'default@local.dev', 'Default User')
ON CONFLICT (id) DO NOTHING;


-- ── 2. Searches Table ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.searches (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE
                         DEFAULT '00000000-0000-0000-0000-000000000001',
    niche            TEXT NOT NULL,
    location         TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued','scraping','analyzing','completed','failed','cancelled')),
    progress_percent INT NOT NULL DEFAULT 0
                         CHECK (progress_percent >= 0 AND progress_percent <= 100),
    message          TEXT NOT NULL DEFAULT 'Search queued',
    total_results    INT NOT NULL DEFAULT 0,
    hot_leads        INT NOT NULL DEFAULT 0,
    warm_leads       INT NOT NULL DEFAULT 0,
    skipped          INT NOT NULL DEFAULT 0,
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_searches_user_id    ON public.searches(user_id);
CREATE INDEX IF NOT EXISTS idx_searches_status     ON public.searches(status);
CREATE INDEX IF NOT EXISTS idx_searches_created_at  ON public.searches(created_at DESC);


-- ── 3. Leads Table ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.leads (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id            UUID NOT NULL REFERENCES public.searches(id) ON DELETE CASCADE,
    user_id              UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE
                              DEFAULT '00000000-0000-0000-0000-000000000001',
    google_key           TEXT NOT NULL DEFAULT '',
    business_name        TEXT NOT NULL DEFAULT 'Unknown',
    category             TEXT NOT NULL DEFAULT '',
    full_address         TEXT NOT NULL DEFAULT '',
    phone                TEXT NOT NULL DEFAULT '',
    email_found          TEXT NOT NULL DEFAULT '',
    website_url          TEXT NOT NULL DEFAULT '',
    rating               REAL,
    total_reviews        INT NOT NULL DEFAULT 0,
    google_maps_link     TEXT NOT NULL DEFAULT '',
    photos               JSONB NOT NULL DEFAULT '[]'::jsonb,
    business_hours       JSONB NOT NULL DEFAULT '{}'::jsonb,
    description          TEXT NOT NULL DEFAULT '',
    lead_category        TEXT NOT NULL DEFAULT 'warm'
                              CHECK (lead_category IN ('hot','warm','skip')),
    website_health_score INT,
    ai_pitch             TEXT,
    ai_confidence_score  REAL,
    estimated_deal_value REAL,
    user_status          TEXT NOT NULL DEFAULT 'new'
                              CHECK (user_status IN ('new','contacted','replied','converted','lost')),
    user_notes           TEXT NOT NULL DEFAULT '',
    is_favorite          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_user_id        ON public.leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_search_id      ON public.leads(search_id);
CREATE INDEX IF NOT EXISTS idx_leads_lead_category  ON public.leads(lead_category);
CREATE INDEX IF NOT EXISTS idx_leads_user_status    ON public.leads(user_status);
CREATE INDEX IF NOT EXISTS idx_leads_is_favorite    ON public.leads(is_favorite);
CREATE INDEX IF NOT EXISTS idx_leads_business_name  ON public.leads(business_name);
CREATE INDEX IF NOT EXISTS idx_leads_created_at     ON public.leads(created_at DESC);


-- ── 4. Website Analyses Table ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.website_analyses (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id       UUID NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
    website_url   TEXT NOT NULL DEFAULT '',
    overall_score INT NOT NULL DEFAULT 0
                       CHECK (overall_score >= 0 AND overall_score <= 100),
    issues        JSONB NOT NULL DEFAULT '[]'::jsonb,
    emails_found  JSONB NOT NULL DEFAULT '[]'::jsonb,
    phones_found  JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_analysis  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_analyses_lead_id ON public.website_analyses(lead_id);


-- ── 5. Stored Procedure: get_dashboard_stats ───────────────────────────────

CREATE OR REPLACE FUNCTION public.get_dashboard_stats(p_user_id UUID)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = ''
AS $function$
DECLARE result JSON;
BEGIN
    SELECT json_build_object(
        'total_searches', (SELECT COUNT(*) FROM public.searches WHERE user_id = p_user_id),
        'completed_searches', (SELECT COUNT(*) FROM public.searches WHERE user_id = p_user_id AND status = 'completed'),
        'total_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id),
        'hot_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND lead_category = 'hot'),
        'warm_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND lead_category = 'warm'),
        'skipped_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND lead_category = 'skip'),
        'favorite_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND is_favorite = TRUE),
        'contacted_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND user_status = 'contacted'),
        'converted_leads', (SELECT COUNT(*) FROM public.leads WHERE user_id = p_user_id AND user_status = 'converted'),
        'recent_searches', (
            SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
            FROM (
                SELECT s.id, s.niche, s.location, s.status, s.total_results, s.created_at
                FROM public.searches s
                WHERE s.user_id = p_user_id
                ORDER BY s.created_at DESC
                LIMIT 5
            ) t
        )
    ) INTO result;
    RETURN result;
END;
$function$;


-- ── 6. Row-Level Security (optional) ──────────────────────────────────────

ALTER TABLE public.searches       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.website_analyses ENABLE ROW LEVEL SECURITY;

-- Note: backend uses service_role key (bypasses RLS).
-- Uncomment below if you access tables directly from the client:
--
-- CREATE POLICY "users own searches" ON public.searches
--     FOR ALL USING (auth.uid() = user_id);
-- CREATE POLICY "users own leads" ON public.leads
--     FOR ALL USING (auth.uid() = user_id);
