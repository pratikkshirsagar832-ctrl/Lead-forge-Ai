-- ═══════════════════════════════════════════════════════════════
-- HYPERCLIENTS — AGENCY MODE v17 (need_agency requestable type)
-- Apply AFTER migration_monthly_quotas_v16.sql in the Supabase SQL Editor.
-- Idempotent.
--
-- What this does:
--   1. Adds `need_agency` (a client/owner seeking to HIRE an agency) as a
--      requestable lead type on ha_searches/ha_leads — the "I'm an Agency"
--      role lane. Strict single-lane: a search is need_freelancer XOR
--      need_agency, never mixed (enforced in backend code, not here).
--   2. Keeps `our_agency` in the CHECK for HISTORICAL rows only. That type
--      (an agency sourcing freelance help) is retired from new searches;
--      no code path writes it anymore. New writes are need_freelancer or
--      need_agency.
-- ═══════════════════════════════════════════════════════════════

ALTER TABLE public.ha_searches DROP CONSTRAINT IF EXISTS ha_searches_lead_type_check;
ALTER TABLE public.ha_searches ADD CONSTRAINT ha_searches_lead_type_check
  CHECK (lead_type IN ('need_freelancer', 'need_agency', 'our_agency'));

ALTER TABLE public.ha_leads DROP CONSTRAINT IF EXISTS ha_leads_lead_type_check;
ALTER TABLE public.ha_leads ADD CONSTRAINT ha_leads_lead_type_check
  CHECK (lead_type IN ('need_freelancer', 'need_agency', 'our_agency'));
