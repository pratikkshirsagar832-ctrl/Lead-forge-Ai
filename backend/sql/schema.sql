-- LeadForge Local Database Schema
-- PostgreSQL 16

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- PLANS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    price_monthly INTEGER NOT NULL DEFAULT 0,
    searches_per_day INTEGER NOT NULL DEFAULT 3,
    leads_per_day INTEGER NOT NULL DEFAULT 30,
    billing_cycle_days INTEGER NOT NULL DEFAULT 30,
    sort_order INTEGER NOT NULL DEFAULT 0
);

INSERT INTO plans (id, name, price_monthly, searches_per_day, leads_per_day, billing_cycle_days, sort_order)
VALUES
    ('free', 'Free', 0, 3, 30, 30, 1),
    ('solo', 'Solo', 4900, 10, 100, 30, 2),
    ('pro', 'Pro', 14900, 30, 300, 30, 3),
    ('agency', 'Agency', 49900, 100, 1000, 30, 4)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- USERS TABLE (local — mirrors Supabase auth.users)
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    full_name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    auth_provider TEXT DEFAULT 'email',
    google_id TEXT DEFAULT '',
    password_hash TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- USER SUBSCRIPTIONS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL DEFAULT 'free' REFERENCES plans(id),
    status TEXT NOT NULL DEFAULT 'trial',
    trial_end TIMESTAMPTZ,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    razorpay_order_id TEXT DEFAULT '',
    razorpay_payment_id TEXT DEFAULT '',
    razorpay_subscription_id TEXT DEFAULT '',
    cancelled_at TIMESTAMPTZ,
    is_trial_expired BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_subscriptions_user_id ON user_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_subscriptions_razorpay ON user_subscriptions(razorpay_order_id);

-- ============================================================
-- DAILY USAGE TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS daily_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    searches_run INTEGER DEFAULT 0,
    leads_generated INTEGER DEFAULT 0,
    ai_calls INTEGER DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_usage_user_date ON daily_usage(user_id, date);

-- ============================================================
-- SEARCHES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS searches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    niche TEXT DEFAULT '',
    location TEXT DEFAULT '',
    source TEXT DEFAULT 'google_maps',
    status TEXT DEFAULT 'queued',
    message TEXT DEFAULT '',
    progress_percent INTEGER DEFAULT 0,
    total_results INTEGER DEFAULT 0,
    hot_leads INTEGER DEFAULT 0,
    warm_leads INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    emails_found INTEGER DEFAULT 0,
    error_message TEXT DEFAULT '',
    max_results INTEGER DEFAULT 20,
    enrich_emails BOOLEAN DEFAULT TRUE,
    lead_types JSONB DEFAULT '["buyer","agency","hiring"]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_searches_user_id ON searches(user_id);
CREATE INDEX IF NOT EXISTS idx_searches_status ON searches(status);

-- ============================================================
-- LEADS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    search_id UUID REFERENCES searches(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source TEXT DEFAULT 'google_maps',
    google_key TEXT DEFAULT '',
    business_name TEXT NOT NULL DEFAULT 'Unknown',
    category TEXT DEFAULT '',
    full_address TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    email_found TEXT DEFAULT '',
    website_url TEXT DEFAULT '',
    rating DOUBLE PRECISION DEFAULT 0,
    total_reviews INTEGER DEFAULT 0,
    google_maps_link TEXT DEFAULT '',
    photos JSONB DEFAULT '[]',
    business_hours JSONB DEFAULT '{}',
    description TEXT DEFAULT '',
    lead_category TEXT DEFAULT 'warm',
    post_type TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    post_url TEXT DEFAULT '',
    post_text TEXT DEFAULT '',
    headline TEXT DEFAULT '',
    profile_picture_url TEXT DEFAULT '',
    connections_count INTEGER DEFAULT 0,
    posted_at TIMESTAMPTZ,
    ai_qualified BOOLEAN DEFAULT FALSE,
    ai_confidence_score DOUBLE PRECISION DEFAULT 0,
    ai_reason TEXT DEFAULT '',
    ai_pitch TEXT DEFAULT '',
    estimated_deal_value DOUBLE PRECISION DEFAULT 0,
    website_health_score INTEGER DEFAULT 0,
    user_status TEXT DEFAULT 'new',
    user_notes TEXT DEFAULT '',
    is_favorite BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_search_id ON leads(search_id);
CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_lead_category ON leads(lead_category);
CREATE INDEX IF NOT EXISTS idx_leads_linkedin_url ON leads(linkedin_url);

-- ============================================================
-- WEBSITE ANALYSES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS website_analyses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    website_url TEXT DEFAULT '',
    overall_score INTEGER DEFAULT 0,
    issues JSONB DEFAULT '[]',
    emails_found JSONB DEFAULT '[]',
    phones_found JSONB DEFAULT '[]',
    raw_analysis JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_analyses_lead_id ON website_analyses(lead_id);

-- ============================================================
-- HELPER FUNCTIONS
-- ============================================================

-- Increment daily usage
CREATE OR REPLACE FUNCTION increment_daily_usage(
    p_user_id UUID,
    p_searches INTEGER DEFAULT 0,
    p_leads INTEGER DEFAULT 0,
    p_ai_calls INTEGER DEFAULT 0
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO daily_usage (user_id, date, searches_run, leads_generated, ai_calls)
    VALUES (p_user_id, CURRENT_DATE, p_searches, p_leads, p_ai_calls)
    ON CONFLICT (user_id, date) DO UPDATE SET
        searches_run = daily_usage.searches_run + EXCLUDED.searches_run,
        leads_generated = daily_usage.leads_generated + EXCLUDED.leads_generated,
        ai_calls = daily_usage.ai_calls + EXCLUDED.ai_calls;
END;
$$ LANGUAGE plpgsql;

-- Get user subscription with plan details
CREATE OR REPLACE FUNCTION get_user_subscription(p_user_id UUID)
RETURNS TABLE (
    plan_id TEXT,
    plan_name TEXT,
    status TEXT,
    searches_per_day INTEGER,
    leads_per_day INTEGER,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    is_trial_expired BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        us.plan_id,
        p.name as plan_name,
        us.status,
        p.searches_per_day,
        p.leads_per_day,
        us.current_period_start,
        us.current_period_end,
        us.trial_end,
        us.is_trial_expired
    FROM user_subscriptions us
    JOIN plans p ON p.id = us.plan_id
    WHERE us.user_id = p_user_id
    ORDER BY us.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Create search (returns the new search row)
CREATE OR REPLACE FUNCTION create_search(
    p_user_id UUID,
    p_niche TEXT,
    p_location TEXT
)
RETURNS TABLE (
    id UUID,
    user_id UUID,
    niche TEXT,
    location TEXT,
    status TEXT,
    created_at TIMESTAMPTZ
) AS $$
DECLARE
    new_search_id UUID;
BEGIN
    INSERT INTO searches (user_id, niche, location, status)
    VALUES (p_user_id, p_niche, p_location, 'queued')
    RETURNING searches.id INTO new_search_id;

    RETURN QUERY
    SELECT s.id, s.user_id, s.niche, s.location, s.status, s.created_at
    FROM searches s WHERE s.id = new_search_id;
END;
$$ LANGUAGE plpgsql;
