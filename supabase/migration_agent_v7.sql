-- HYPERCLIENTS — Migration v7: HyperAgent conversational + service memory
--
-- The new HyperAgent page:
--   1. agent_services — up-to-date MEMORY of powerful per-(service, lead_type,
--      country) queries the agent learns from DeepSeek, so repeat searches reuse
--      them and the agent stays current.
--   2. agent_chat_state — persists each user's conversational step (cookies ->
--      service -> lead type -> country -> count) so the wizard survives refresh.
--
-- Both are idempotent (CREATE IF NOT EXISTS). No data is dropped.

-- Learned / reusable powerful queries for a service the agent has searched.
CREATE TABLE IF NOT EXISTS public.agent_services (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    service       text NOT NULL,
    lead_type     text NOT NULL DEFAULT 'freelancer_needed',
    queries       jsonb NOT NULL DEFAULT '[]',
    country       text NOT NULL DEFAULT '',
    used_count    integer NOT NULL DEFAULT 0,
    last_used_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, service, lead_type, country)
);
CREATE INDEX IF NOT EXISTS idx_agent_services_user ON public.agent_services(user_id);

-- Per-user conversational wizard state (one questionnaire at a time).
CREATE TABLE IF NOT EXISTS public.agent_chat_state (
    user_id     uuid PRIMARY KEY,
    step        text NOT NULL DEFAULT 'cookies',
    data        jsonb NOT NULL DEFAULT '{}',
    updated_at  timestamptz NOT NULL DEFAULT now()
);
