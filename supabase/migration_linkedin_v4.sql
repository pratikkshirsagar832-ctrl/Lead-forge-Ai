-- Migration: Add lead_types to searches, AI qualification fields to leads
-- Run in Supabase SQL Editor

-- Add lead_types to searches table
ALTER TABLE public.searches
ADD COLUMN IF NOT EXISTS lead_types TEXT[] DEFAULT ARRAY['buyer', 'agency', 'hiring'];

-- Add AI qualification fields to leads table
ALTER TABLE public.leads
ADD COLUMN IF NOT EXISTS ai_qualified BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS ai_confidence NUMERIC(3,2),
ADD COLUMN IF NOT EXISTS ai_reason TEXT;

-- Index for filtering by lead_types (PostgreSQL array column)
CREATE INDEX IF NOT EXISTS idx_searches_lead_types ON public.searches USING GIN (lead_types);