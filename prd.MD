# LeadForge AI — Product Requirements Document
## Version: 2.1
## Status: Finalized for Build
## Build Type: MVP
## Pricing in MVP: Free
## Backend Hosting: Google Compute Engine VM
## Frontend Hosting: Vercel
## Database/Auth: Supabase (MCP-connected)

---

# 1. Product Summary

LeadForge AI is a lead discovery and qualification SaaS for:
- freelance web developers
- digital marketing agencies
- SEO consultants
- website redesign sellers

The app discovers local businesses from Google Maps, checks whether they need a website or a better website, and helps users generate outreach-ready sales opportunities.

This MVP is intentionally simplified for stability and speed:
- no Redis
- no Celery
- no Playwright
- no Crawl4AI
- no payments
- no 3D

Instead, it uses:
- `google-maps-scraper` for Google Maps extraction
- `Scrapling` for homepage website analysis
- `DeepSeek` for on-demand pitch generation
- `FastAPI BackgroundTasks` for job execution
- `Supabase` for authentication and database
- `Next.js` for frontend

---

# 2. Final Locked Architecture

## Backend Hosting
Google Compute Engine VM

## Frontend Hosting
Vercel

## Auth
Frontend direct Supabase Auth  
Backend verifies bearer tokens only

## AI Pitch Timing
On-demand only

## Search Result Target
Up to 50 results

## Website Analysis Scope
Homepage only

## Background Processing
FastAPI BackgroundTasks + asyncio.Semaphore

## Frontend Style
Light theme

## Search Progress
Polling every 2 seconds

## Timeout Strategy
Partial results are saved if timeout occurs; user can retry

---

# 3. Core User Flow

1. User signs up / logs in from frontend using Supabase Auth
2. User opens New Search
3. User enters niche + location
4. Backend creates a search row
5. Backend runs google-maps-scraper in background
6. Businesses are stored as leads
7. Websites are analyzed via Scrapling
8. Leads are categorized:
   - Hot
   - Warm
   - Skip
9. User sees results and filters them
10. User opens lead detail
11. User clicks Generate Pitch
12. AI generates outreach copy
13. User copies pitch or exports CSV

---

# 4. Stack

## Backend
- FastAPI
- Uvicorn
- Supabase Python client
- google-maps-scraper
- Scrapling
- DeepSeek API
- FastAPI BackgroundTasks
- asyncio.Semaphore
- Docker

## Frontend
- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui
- Zustand
- Framer Motion
- Axios
- React Hook Form
- Zod
- Supabase JS client

## Database/Auth
- Supabase Postgres
- Supabase Auth
- Supabase RLS
- Supabase MCP for schema creation and DB setup

---

# 5. Supabase MCP Requirement

Supabase MCP is connected and must be used directly during build.

This means:
- tables must be created through MCP
- indexes must be created through MCP
- RLS policies must be created through MCP
- triggers must be created through MCP
- helper functions / RPCs must be created through MCP
- schema verification must be performed through MCP

No SQLAlchemy migrations.
No Alembic.
No manual DB migration system in MVP.

---

# 6. Required Database Tables

## users
Stores public profile data for authenticated users.

Fields:
- id (uuid, matches auth.users.id)
- email
- name
- avatar_url
- auth_provider
- is_active
- created_at
- updated_at

## searches
Stores every search launched by a user.

Fields:
- id
- user_id
- niche
- location
- status
- progress_percent
- message
- total_results
- hot_leads
- warm_leads
- skipped
- error_message
- created_at
- completed_at

## leads
Stores individual business leads found by a search.

Fields:
- id
- search_id
- user_id
- google_key
- business_name
- category
- full_address
- phone
- email_found
- website_url
- rating
- total_reviews
- google_maps_link
- photos
- business_hours
- description
- lead_category
- website_health_score
- ai_pitch
- ai_confidence_score
- estimated_deal_value
- user_status
- user_notes
- is_favorite
- created_at

## website_analyses
Stores homepage analysis results for a lead that has a website.

Fields:
- id
- lead_id
- website_url
- overall_score
- issues
- emails_found
- phones_found
- raw_analysis
- created_at

---

# 7. Required Supabase Features

## Triggers
- auth.users insert → public.users insert/update
- users.updated_at auto-update trigger

## RLS
Users must only be able to access their own data.

## Indexes
Need indexes on:
- users.email
- searches.user_id
- searches.status
- searches.created_at
- leads.search_id
- leads.user_id
- leads.lead_category
- leads.is_favorite
- leads.user_status
- leads.created_at
- leads.google_key
- website_analyses.lead_id

## RPC / SQL function
Need a dashboard stats function or equivalent query support.

---

# 8. Search Lifecycle

## Create
Search row created with:
- status = queued
- progress = 0
- message = queued message

## Run
Background task executes:
- maps scraping
- result save
- website analysis
- finalize counts

## Complete
Search becomes completed with all counts

## Fail
Search becomes failed only if a real error occurs

## Timeout
At 10 minutes:
- save partial results
- complete with retry note

## Cancel
User can cancel a running search

---

# 9. Search Behavior Rules

- up to 50 businesses per search
- if fewer available, return whatever found
- progress must always move or fail clearly
- searches must never remain stuck forever
- partial results are better than empty failure
- retry should be available

---

# 10. Website Analysis Rules

Use Scrapling only.

Homepage-only checks:
- SSL / HTTPS
- title
- meta description
- visible content length
- contact details
- social presence
- weak quality signals

Result:
- Warm
- Skip

---

# 11. AI Pitch Rules

AI generation is on-demand only.

The AI should:
- generate one professional outreach pitch
- be concise
- be useful to freelancers/agencies
- reference business context when possible

---

# 12. Frontend Rules (for Prompt 2 later)

- light theme
- fast UI
- no 3D
- instant-feel buttons
- optimistic updates
- polling every 2 sec for search progress
- CSV export
- advanced filters
- cancel search

---

# 13. Error Handling Rules

- no silent failures
- no stuck processing forever
- timeout → partial complete
- scraper failure → clear failure
- AI failure → user can retry
- old stale jobs must not break fresh jobs

---

# 14. Deployment Rules

Backend must be built in a way that is:
- Docker-friendly
- VM-friendly
- env-driven
- stable with subprocess calls

Frontend must be deployable on Vercel.

---

# 15. Final Locked Decisions

1. Backend = Google Compute Engine VM
2. Frontend = Vercel
3. Auth = frontend direct Supabase Auth
4. AI pitch = on-demand only
5. Search target = up to 50
6. Website analysis = homepage only
7. Background processing = BackgroundTasks + semaphore
8. Style = Light theme
9. Progress = polling every 2 sec
10. Timeout = partial results + retry
11. Low-result behavior = return whatever found
12. Filters = advanced
13. Lead detail AI = single generate pitch button
14. Notes/status/favorites = optimistic updates
15. Export CSV = yes
16. Cancel search = yes
17. Supabase MCP must be used directly for schema creation