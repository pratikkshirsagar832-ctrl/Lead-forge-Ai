-- ═══════════════════════════════════════════════════════════════
-- HYPERAGENT HA TABLES — original standalone schema, prefixed
-- Tables: ha_searches, ha_leads (isolated from main app tables)
-- Run in MAIN Supabase project
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.ha_searches (
  id uuid primary key default gen_random_uuid(),
  service text not null,
  country text default '',
  lead_type text check (lead_type in ('need_freelancer','hiring_buyer','our_agency')),
  time_window text check (time_window in ('24h','7d','14d','28d')),
  leads_needed int not null,
  status text not null default 'queued',
  found_count int not null default 0,
  accepted_count int not null default 0,
  scanned_count int not null default 0,
  error text,
  created_at timestamptz not null default now(),
  finished_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_ha_searches_created_at ON public.ha_searches (created_at desc);

CREATE TABLE IF NOT EXISTS public.ha_leads (
  id uuid primary key default gen_random_uuid(),
  search_id uuid references public.ha_searches(id) on delete cascade,
  lead_type text check (lead_type in ('need_freelancer','hiring_buyer','our_agency')),
  time_window text check (time_window in ('24h','7d','14d','28d')),
  post_url text not null unique,
  author_name text,
  author_profile_url text,
  post_text text,
  post_date date,
  overall_quality_score numeric,
  service_match_score numeric,
  intent_strength text,
  status text not null default 'new',
  notes text,
  created_at timestamptz not null default now()
);

CREATE INDEX IF NOT EXISTS idx_ha_leads_post_date ON public.ha_leads (post_date desc);
CREATE INDEX IF NOT EXISTS idx_ha_leads_search_id ON public.ha_leads (search_id);
CREATE INDEX IF NOT EXISTS idx_ha_leads_status ON public.ha_leads (status);
