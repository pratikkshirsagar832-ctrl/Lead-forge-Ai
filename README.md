# Hyperclients

**AI-Powered Lead Generation & Outreach Platform** — Discover qualified B2B leads from **Google Maps** and **LinkedIn**, score them with AI, and generate personalized outreach pitches from a single premium dashboard.

Built for freelance web developers, digital agencies, and sales teams who want to find, qualify, and close local + remote business leads at scale.

> Production: [https://hyperclients.online](https://hyperclients.online)

---

## ✨ Features

### 🔍 Lead Discovery (Two Sources)

| Source | What it finds | How |
|--------|--------------|-----|
| **Google Maps** | Local businesses by niche + location, with ratings, reviews, phone, website | Go scraper binary (`google-maps-scraper`) |
| **LinkedIn** | Companies hiring for a service — **Remote / Contract-basis / Part-time only** | Apify `scrapeforge/linkedin-all-in-one` post-search |

### 🤖 AI Qualification (LinkedIn)

- GPT-4o-mini semantically scores every post **0–100** across 6 dimensions: service match, business problem, buying intent, decision-maker likelihood, urgency, outreach worthiness
- Detects **work type** (remote / contract / part-time / on-site) — full-time on-site jobs are **hard-rejected**
- Classifies lead type: `explicit_need`, `problem_awareness`, `research`, `hiring`, `agency`, `irrelevant`
- Distinguishes **buyers** ("we're looking for a developer") from **freelancers selling** ("I'm available for projects")
- Generates a personalized **outreach angle** for every saved lead
- Deduplicates by author across `?miniProfileUrn=` URL variants

### 📊 Lead Management

- CRM-style dashboard with **Hot / Warm** categories
- Kanban **pipeline** (New → Contacted → Replied → Converted → Lost) with drag-and-drop
- Filters: category, source, post type, status, favorites
- CSV export with full AI fields
- Lead detail view: post content, AI score breakdown, pitch, pipeline status, notes

### 💰 Subscriptions & Billing

- Razorpay-powered paid plans with per-plan **searches/day** and **leads/day** limits
- Daily usage tracking (`daily_usage`), subscription status, trial handling

### 🧠 AI Outreach

- `POST /api/ai/pitch/{lead_id}` — full personalized pitch
- `POST /api/ai/website-message/{lead_id}` — short WhatsApp-style outreach message

### 🚀 Hyper-Agent Module (Frontend)

Advanced outreach toolkit: campaigns, sequences, research, signals, analytics, compliance, browser automation, email + enrichment integrations, webhooks, and more (client-side architecture under `frontend/src/lib/hyper-agent/`).

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14 / React 18)                 │
│  Tailwind v4 · Framer Motion · Zustand · @dnd-kit · Supabase Auth   │
│  Google OAuth + email/password · Razorpay Checkout                  │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ HTTP (Axios, Bearer JWT)
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI / Python 3.12)                   │
│                                                                     │
│  ┌──────────┐ ┌───────────────┐ ┌───────────────┐ ┌────────────┐  │
│  │ Auth     │ │ Subscriptions │ │ Search        │ │ Leads      │  │
│  └──────────┘ └───────────────┘ └───────┬───────┘ └──────┬─────┘  │
│  ┌──────────┐ ┌───────────────┐         │                 │        │
│  │ Dashboard│ │ AI (pitch)    │         ▼                 ▼        │
│  └──────────┘ └───────────────┘   ┌────────────┐   ┌────────────┐ │
│                                   │ pipeline.py│   │linkedin_   │ │
│                                   │ (Maps,Go)  │   │pipeline.py │ │
│                                   └─────┬──────┘   │ (Apify+GPT)│ │
│                                         │          └─────┬──────┘ │
│                     ┌───────────────────┼────────────────┤        │
│                     ▼                   ▼                ▼        │
│           scraper_service      analyzer_service    apify_service  │
│           (Go subprocess)      (Scrapling+httpx)   (3 actors)     │
└──────────────────────────┬────────────────────────────────────────┘
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│               Supabase (PostgreSQL + Auth + RLS)                     │
│  plans · user_subscriptions · daily_usage · searches · leads ·       │
│  website_analyses · linkedin_leads                                   │
└────────────────────────────────────────────────────────────────────┘
```

### Data Flows

**Google Maps search:**
1. User enters `niche + location` → FastAPI creates a `searches` row, spawns background pipeline (semaphore: 3 concurrent, 10-min timeout)
2. Go binary scrapes up to 25 businesses → raw CSV parsed into `leads`
3. Website Analyzer (Scrapling + httpx fallback, 5 concurrent) visits each site, scores 0–100
4. Leads finalized → `hot` (no site) / `warm` (poor site) / skip (decent site)

**LinkedIn search:**
1. User enters a service (e.g. "website development")
2. Query builder generates broad **role-based discovery phrases** ("looking for a freelance website developer", "contract website developer", "hiring web designer") — packed into ≤60-char OR-chunks because the actor rejects long queries
3. Apify `scrapeforge/linkedin-all-in-one` runs each chunk in parallel (post-search mode) → posts merged + deduped
4. Best post per author kept by engagement; optional `profile-detail` enrichment (headline/company/location — best-effort, non-fatal)
5. GPT-4o-mini scores each candidate 0–100 with the 6-dimension rubric + work-type hard rule
6. Qualified leads (score ≥ 40, no on-site/full-time) ranked, deduped by clean URL, saved with AI score, reason, and outreach pitch

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript |
| **Styling** | Tailwind CSS v4, Framer Motion, Lucide + Tabler icons |
| **State** | Zustand, React Hook Form + Zod, @radix-ui primitives |
| **Drag & drop** | @dnd-kit (pipeline kanban) |
| **3D visuals** | Three.js + @react-three/fiber |
| **Backend** | Python 3.12, FastAPI, uvicorn |
| **Database** | Supabase (PostgreSQL) with Row-Level Security |
| **Auth** | Supabase Auth (email/password + Google OAuth) |
| **Payments** | Razorpay (subscriptions, webhook-verified) |
| **AI** | OpenAI GPT-4o-mini (lead scoring, pitches) |
| **Scraping** | `google-maps-scraper` (Go binary), Apify `scrapeforge/linkedin-all-in-one`, Scrapling (Python) |
| **HTTP** | Axios (frontend), httpx (backend) |
| **Container** | Docker Compose (multi-stage Go builder + Python runtime) |

---

## Project Structure

```
Lead-Forge-Ai/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entrypoint, lifespan, stale-search cleanup
│   │   ├── config.py                  # pydantic-settings (env-driven)
│   │   ├── database.py                # Supabase client factories (lru_cache)
│   │   ├── middleware/
│   │   │   └── auth_middleware.py      # Bearer JWT verification
│   │   ├── routers/
│   │   │   ├── auth.py                # /api/auth/me, profile
│   │   │   ├── subscriptions.py       # /api/subscriptions (Razorpay plans, checkout, webhook)
│   │   │   ├── search.py              # /api/searches CRUD + status + cancel + results
│   │   │   ├── leads.py               # /api/leads CRUD + filters + CSV export
│   │   │   ├── dashboard.py           # /api/dashboard/stats
│   │   │   └── ai.py                  # /api/ai/pitch, /api/ai/website-message
│   │   ├── schemas/                   # Pydantic request/response models
│   │   └── services/
│   │       ├── pipeline.py            # Google Maps search orchestration (semaphore)
│   │       ├── linkedin_pipeline.py   # LinkedIn search: queries → Apify → GPT scoring → save
│   │       ├── apify_service.py       # Apify actors + multi-key failover + chunking
│   │       ├── scraper_service.py     # Go binary subprocess wrapper
│   │       ├── analyzer_service.py    # Website scoring (Scrapling + httpx fallback)
│   │       ├── enhanced_analyzer.py   # Deeper site analysis
│   │       ├── deep_analyzer.py       # Full deep-dive website analysis
│   │       └── ai_service.py          # GPT pitch + website-message generation
│   ├── google-maps-scraper/           # Go scraper module
│   ├── Scrapling/                     # Vendored Scrapling library
│   ├── scripts/                       # run-api.sh/.ps1, systemd unit
│   ├── Dockerfile                     # Multi-stage build (Go + Python)
│   ├── requirements.txt
│   └── .env                           # Backend secrets (server-side only)
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx             # Root layout + providers
│   │   │   ├── page.tsx               # Landing page
│   │   │   ├── login/page.tsx         # Login (Google + email/password)
│   │   │   ├── pricing/page.tsx       # Plans
│   │   │   ├── admin/                 # Admin panel + login
│   │   │   ├── tools/seo-score-checker/
│   │   │   ├── blogs/                 # Marketing blog (MDX)
│   │   │   └── dashboard/
│   │   │       ├── page.tsx           # Overview + stats
│   │   │       ├── search/page.tsx    # New search (Maps/LinkedIn) + live progress
│   │   │       ├── leads/page.tsx     # Filterable lead grid
│   │   │       ├── leads/[id]/page.tsx# Lead detail + AI pitch + score breakdown
│   │   │       ├── pipeline/page.tsx  # Kanban lead manager (@dnd-kit)
│   │   │       ├── history/page.tsx   # Search history
│   │   │       ├── export/page.tsx    # CSV export
│   │   │       ├── billing/page.tsx   # Subscriptions + usage
│   │   │       ├── settings/page.tsx  # Profile
│   │   │       └── hyper-agent/       # Outreach toolkit (campaigns, sequences,
│   │   │                              #   research, signals, analytics, compliance…)
│   │   ├── components/
│   │   │   ├── auth/                  # AuthProvider
│   │   │   ├── dashboard/             # Sidebar, StatsCards, LeadCard, FiltersBar,
│   │   │   │                          #   SearchProgressCard, PostTypeBadge, …
│   │   │   ├── landing/               # Hero, Features, HowItWorks, Footer
│   │   │   └── shared/                # GlassCard, Badge, Modal, Toast, Skeleton…
│   │   ├── hooks/                     # useAuth, useSearch, useLeads, useToast
│   │   ├── stores/                    # Zustand stores (auth, search, leads)
│   │   ├── lib/
│   │   │   ├── api.ts                 # Axios client + auth interceptor
│   │   │   ├── supabase.ts            # Supabase browser client
│   │   │   ├── constants.ts           # Routes, categories, statuses
│   │   │   ├── types.ts               # Shared TS interfaces
│   │   │   └── hyper-agent/           # Outreach engine modules (agent, ai, email,
│   │   │                              #   enrichment, outreach, plugins, webhooks…)
│   │   └── styles/globals.css         # Tailwind v4 + Hyperclients design tokens
│   ├── .env.local                     # Frontend env vars
│   ├── Dockerfile                     # Next.js standalone build
│   └── package.json
│
├── supabase/
│   ├── migration.sql                  # Core schema (plans, subscriptions, searches, leads…)
│   └── migration_linkedin*.sql        # LinkedIn pipeline migrations
│
├── docker-compose.yml                 # backend :8000, frontend :3001 (production)
├── deploy-contabo.sh                  # One-shot server deploy script
├── deploy/                            # Deployment tooling
└── Design/                            # Brand/design assets
```

---

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.12+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| Go | 1.21+ | Only to build `google-maps-scraper` locally |
| Supabase | Project | Free tier works — [supabase.com](https://supabase.com) |
| OpenAI | API key | Lead scoring + pitches |
| Apify | API key | LinkedIn discovery (`scrapeforge/linkedin-all-in-one`) |
| Razorpay | Key ID + Secret | Payments (optional for local dev) |

---

## Setup

### 1. Clone & Install Dependencies

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Vendored Scrapling (for website analysis)
cd Scrapling && pip install -e . && cd ..

# Frontend
cd ../frontend
npm install
```

### 2. Database (Supabase)

1. Create a Supabase project
2. SQL Editor → run `supabase/migration.sql` then `supabase/migration_linkedin.sql` (+ `_v2`/`_v3`/`_v4` in order)
3. Enable Row-Level Security on `searches` and `leads` if not already applied
4. Create a `plans` row (e.g. Free / Pro / Agency) with `searches_per_day` and `leads_per_day`

### 3. Environment Variables

**`backend/.env`:**
```env
ENVIRONMENT=development
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJ...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJ...
OPENAI_API_KEY=sk-...
APIFY_API_KEY=apify_api_...
APIFY_API_KEY_2=apify_api_...          # optional failover key
RAZORPAY_KEY_ID=rzp_...
RAZORPAY_KEY_SECRET=...
GMAPS_SCRAPER_PATH=backend/google-maps-scraper/google-maps-scraper
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
SITE_URL=http://localhost:3000
```

**`frontend/.env.local`:**
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJ...
```

### 4. Build the Scraper Binary (Maps only)

```bash
cd backend/google-maps-scraper
go build -o google-maps-scraper .
```

### 5. Run Locally

```bash
# Terminal 1 — Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open **http://localhost:3000** → Sign up → Run your first search.

---

## API Endpoints

### Auth & Users
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/auth/me` | Current user + subscription + remaining usage |

### Subscriptions
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/subscriptions/plans` | Available plans |
| `GET` | `/api/subscriptions/current` | Current subscription + usage |
| `POST` | `/api/subscriptions/create-order` | Create Razorpay order |
| `POST` | `/api/subscriptions/verify` | Verify Razorpay payment signature |
| `POST` | `/api/subscriptions/webhook` | Razorpay payment webhook (HMAC-verified) |
| `POST` | `/api/subscriptions/cancel` | Cancel subscription |

### Searches
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/searches` | Create search (`source: google_maps` / `linkedin`) |
| `GET` | `/api/searches` | Search history (paginated) |
| `GET` | `/api/searches/scraper-health` | Scraper binary health check |
| `GET` | `/api/searches/{id}` | Search detail |
| `GET` | `/api/searches/{id}/status` | Lightweight polling status |
| `GET` | `/api/searches/{id}/results` | Saved leads for a search |
| `POST` | `/api/searches/{id}/cancel` | Cancel a running search |
| `POST` | `/api/searches/{id}/load-more` | Scrape additional results |

### Leads
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/leads` | List leads (filters + pagination) |
| `GET` | `/api/leads/export` | CSV export |
| `GET` | `/api/leads/{id}` | Lead detail |
| `POST` | `/api/leads/{id}/analyze-website` | Run website analysis on demand |
| `PATCH` | `/api/leads/{id}/status` | Pipeline status |
| `PATCH` | `/api/leads/{id}/notes` | User notes |
| `PATCH` | `/api/leads/{id}/favorite` | Toggle favorite |

### AI
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ai/pitch/{lead_id}` | Generate personalized outreach pitch |
| `POST` | `/api/ai/website-message/{lead_id}` | Short WhatsApp-style message |

### Dashboard
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/stats` | Aggregate stats |

---

## LinkedIn Pipeline Details

### Discovery Queries
Service input is expanded into **role-based phrases**:
```
"website development" →
  website development, looking for a freelance website developer,
  looking for freelance website developer, hiring website developer,
  need a website developer for our, website developer required for,
  freelance website developer for, need website developer for project,
  contract website developer, website developer needed, …
```
Phrases are packed into ≤60-char boolean-OR chunks (the Apify actor fails on longer queries) and run in parallel.

### AI Scoring Rubric (0–100)

| Dimension | Weight | Signals |
|-----------|--------|---------|
| Service match | 25 | mentions the service / its core problem |
| Business problem | 20 | metrics declining, new build needed |
| Buying intent | 20 | vendor search, **hiring freelancer/contractor = 18** |
| Decision-maker likelihood | 15 | Founder/CEO/VP = 15 |
| Urgency | 10 | ASAP, deadline, project starting |
| Outreach worthiness | 10 | reachable decision-maker with a problem |

**Hard rules:** on-site/full-time hiring → rejected. Freelancers marketing their own availability ("I'm available", "open to projects") → rejected — they are sellers, not buyers.

### Saved Lead Mapping

| AI output | DB column |
|-----------|-----------|
| `lead_score` | `ai_confidence_score` (stored as score/100, column constrained 0–1) |
| `lead_type` | `post_type` (mapped to `buyer`/`agency`/`hiring`/`job_seeker` — CHECK-constrained) |
| `outreach_angle` | `ai_pitch` |
| `reason` | `ai_reason` |
| work type | prefixed into `headline` (🌍 Remote / 📄 Contract / ⏱️ Part-time) |

---

## Lead Categories

| Category | Meaning | Website Health |
|----------|---------|----------------|
| **Hot** (Maps) | No website found | N/A |
| **Warm** (Maps) | Poor/broken website | 0–49 |
| **Hot** (LinkedIn) | AI score ≥ 85 — explicit need + decision-maker | — |
| **Warm** (LinkedIn) | AI score ≥ 40 — clear problem or hiring intent | — |

Pipeline statuses (kanban): **New → Contacted → Replied → Converted → Lost**

---

## Deployment

### Docker Compose (production — used on Hostinger)

```bash
cd /root/leadforge
git pull
docker compose up -d --build
# backend  → 127.0.0.1:8000 (behind reverse proxy / nginx)
# frontend → 127.0.0.1:3001
```

### One-shot server script

```bash
bash deploy-contabo.sh    # pulls repo, writes .env templates, compose up
```

### Manual Docker

```bash
docker build -t leadforge-backend -f backend/Dockerfile backend
docker run -p 8000:8000 --env-file backend/.env leadforge-backend
```

---

## Tech Notes

- **Apify multi-key failover** — `_run_sync_actor` retries 401/402/429/5xx across `APIFY_API_KEY` then `APIFY_API_KEY_2`; only a 400 raises immediately
- **LinkedIn query chunking** — `run_post_search` parallelizes ≤60-char OR chunks via `ThreadPoolExecutor`, then dedupes by `postId`
- **Profile enrichment is best-effort** — headline/company enrichment failure never fails a search
- **DB constraints respected** — lead rows are mapped to the existing CHECK-constrained columns (`post_type`, `lead_category`, `ai_confidence_score`) so inserts never violate schema
- **Stale search recovery** — on startup, searches stuck in `queued/scraping/analyzing` > 15 min are marked failed
- **Website analysis** — Scrapling with synchronous-httpx fallback, threaded via `asyncio.to_thread`
- **Auth** — Bearer JWT verified against Supabase `auth.get_user()` on every request
- **Payments** — Razorpay webhooks verified with HMAC signature; subscription + usage enforced per-request

---

## License

Apache License 2.0 — see `backend/LICENSE`.
