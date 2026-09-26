-- v24: ha_leads.urgency - how pressing the buyer's need is (0-3), from the
-- discovery provider's free intent label. Optional: the engine only writes
-- it when this column exists, so running this migration is safe at any time.
ALTER TABLE public.ha_leads ADD COLUMN IF NOT EXISTS urgency real;
