-- Lead Forge HyperAgent — research engine persistence tables + RLS.
-- Run after migration.sql. Tables are tenant-scoped (user_id) with RLS.

-- Research run/task extra fidelity (the `searches` row carries the lifecycle).
create table if not exists research_runs (
  id uuid primary key default gen_random_uuid(),
  search_id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  objective text,
  state text not null default 'queued',
  candidates_found int default 0,
  verified_count int default 0,
  duplicates_removed int default 0,
  final_lead_count int default 0,
  stop_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Structural candidate posts (evidence-first).
create table if not exists lead_candidates (
  id uuid primary key default gen_random_uuid(),
  search_id text,
  user_id uuid not null references auth.users(id) on delete cascade,
  tenant_id text default '',
  post_url text,
  profile_url text,
  author_name text,
  author_headline text,
  post_text text,
  posted_at timestamptz,
  intent_type text,
  requested_service text,
  lead_type text,
  score_overall numeric,
  duplicate_group text,
  verification_status text,
  rejection_reason text,
  source_agent text,
  created_at timestamptz not null default now()
);

-- Personalized outreach drafts gated by an approval boundary.
create table if not exists message_drafts (
  id uuid primary key default gen_random_uuid(),
  search_id text,
  user_id uuid not null references auth.users(id) on delete cascade,
  lead_id text,
  author_name text,
  full_message text,
  approval_state text not null default 'draft_created',
  evidence_refs jsonb default '[]'::jsonb,
  created_at timestamptz not null default now()
);

-- Observability event stream (never contains secrets).
create table if not exists agent_events (
  id uuid primary key default gen_random_uuid(),
  search_id text,
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null,
  object_id text,
  payload jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Usage accounting.
create table if not exists usage_metrics (
  id uuid primary key default gen_random_uuid(),
  search_id text,
  user_id uuid not null references auth.users(id) on delete cascade,
  payload jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- LinkedIn browser session reference (opaque; secrets live in the encrypted store).
create table if not exists linkedin_sessions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  status text not null default 'disconnected',
  storage_ref text,
  last_validated_at timestamptz,
  error_detail text default '',
  updated_at timestamptz not null default now()
);

-- RLS: users may only see their own rows.
alter table research_runs enable row level security;
alter table lead_candidates enable row level security;
alter table message_drafts enable row level security;
alter table agent_events enable row level security;
alter table usage_metrics enable row level security;
alter table linkedin_sessions enable row level security;

create policy "own research_runs" on research_runs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own lead_candidates" on lead_candidates for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own message_drafts" on message_drafts for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own agent_events" on agent_events for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own usage_metrics" on usage_metrics for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own linkedin_sessions" on linkedin_sessions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
