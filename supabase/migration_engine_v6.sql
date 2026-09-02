-- HYPERCLIENTS — Migration v6: allow agency_wanted (and job_seeker) post_type
--
-- The strict Agency Wanted lead engine emits post_type='agency_wanted' for
-- genuine agency-sourcing leads. The v3 constraint (migration_linkedin_v3.sql)
-- only allowed ('buyer','agency','hiring','job_seeker','unknown') — it was
-- missing 'agency_wanted'. Production migration_production_v5.sql was intended
-- to add it but this DDL confirms it never applied on live Supabase.
--
-- Run this in the Supabase SQL Editor (or any psql with the DB password):
--   https://supabase.com/dashboard/project/gzxmgdkpsdqkxrnpplyh/sql/new
--
-- Safe: idempotent. Drops the old constraint and recreates it with the full
-- allowed value set.

ALTER TABLE public.leads
    DROP CONSTRAINT IF EXISTS leads_post_type_check;

ALTER TABLE public.leads
    ADD CONSTRAINT leads_post_type_check
    CHECK (post_type IN ('buyer', 'agency', 'agency_wanted', 'hiring', 'job_seeker', 'unknown'));

-- Sanity: confirm the new constraint.
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname = 'leads_post_type_check';
