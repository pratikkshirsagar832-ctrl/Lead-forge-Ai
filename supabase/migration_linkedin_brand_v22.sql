-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — LINKEDIN STUDIO v22: brand profile ("on whose behalf")
-- Apply after migration_linkedin_studio_v21.sql. Idempotent.
--
-- Filled in by the user BEFORE connecting LinkedIn: who we manage LinkedIn
-- for, their business, audience, goals, voice, stories and explicit
-- authorization. DeepSeek reads this on every writing task.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.linkedin_brand_profiles (
    user_id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    managed_for       TEXT NOT NULL DEFAULT 'self' CHECK (managed_for IN ('self', 'company', 'client')),
    full_name         TEXT,
    headline          TEXT,          -- role / LinkedIn headline
    company           TEXT,
    website           TEXT,
    industry          TEXT,
    location          TEXT,
    language          TEXT NOT NULL DEFAULT 'English',
    services          TEXT,          -- what they sell / do
    offer             TEXT,          -- unique value, proof, pricing angle
    target_audience   TEXT,          -- who they write for
    ideal_client      TEXT,
    goals             TEXT[] NOT NULL DEFAULT '{}',   -- leads, authority, hiring, ...
    tone              TEXT[] NOT NULL DEFAULT '{}',   -- conversational, bold, ...
    topics            TEXT[] NOT NULL DEFAULT '{}',   -- content pillars
    expertise         TEXT,
    story_bank        TEXT,          -- achievements, numbers, stories, lessons (grows via Interview)
    writing_samples   TEXT,          -- the user's own past posts (voice)
    cta_preference    TEXT,
    avoid             TEXT,          -- words / topics to never use
    posting_frequency TEXT,
    notes             TEXT,
    authorized        BOOLEAN NOT NULL DEFAULT false,
    authorized_at     TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.linkedin_brand_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.linkedin_brand_profiles FROM PUBLIC, anon, authenticated;
DROP POLICY IF EXISTS li_brand_owner_read ON public.linkedin_brand_profiles;
CREATE POLICY li_brand_owner_read ON public.linkedin_brand_profiles FOR SELECT TO authenticated
  USING (user_id = auth.uid());
GRANT SELECT ON public.linkedin_brand_profiles TO authenticated;

-- Voice profile learned from the user's own posts (linkedin-humanizer --mode profile).
ALTER TABLE public.linkedin_brand_profiles ADD COLUMN IF NOT EXISTS voice_profile   TEXT;
ALTER TABLE public.linkedin_brand_profiles ADD COLUMN IF NOT EXISTS voice_updated_at TIMESTAMPTZ;
