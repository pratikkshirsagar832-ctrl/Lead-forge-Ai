# Hyperclients

**Automated Lead Generation Engine** — Scrape Google Maps, analyze websites, and draft AI-powered outreach pitches from a single dashboard.

Built for freelance web developers, digital agencies, and sales teams who want to find and qualify local business leads at scale.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Next.js 14)                 │
│  React 18 · Tailwind v4 · Framer Motion · Zustand       │
│  Supabase Auth (email + Google OAuth)                   │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (Axios)
                     ▼
┌─────────────────────────────────────────────────────────┐
│                 Backend (FastAPI / Python 3.12)           │
│                                                          │
│  ┌───────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │ Auth      │  │ Search       │  │ AI Pitch          │ │
│  │ Router    │  │ Router       │  │ Router            │ │
│  └───────────┘  └──────┬───────┘  └───────────────────┘ │
│                        │                                 │
│              ┌─────────▼──────────┐                     │
│              │  Pipeline Service  │                     │
│              │  (async semaphore) │                     │
│              └──┬──────┬──────┬───┘                     │
│                 │      │      │                         │
│       ┌─────────▼┐ ┌──▼───┐ ┌─▼───────────┐           │
│       │ Scraper  │ │Site  │ │ Analyzer    │           │
│       │ (Go bin) │ │Fetch │ │ (Scrapling) │           │
│       └──────────┘ └──────┘ └─────────────┘           │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                    Supabase (PostgreSQL)                  │
│  users · searches · leads · website_analyses            │
│  Row-Level Security · Auth · Auto API                   │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User** enters `niche + location` in the dashboard
2. **FastAPI** creates a `searches` row and spawns a background pipeline
3. **Google Maps Scraper** (Go binary) extracts up to 50 businesses → raw CSV
4. **Pipeline** parses results, saves `leads` rows, categorizes by website presence
5. **Website Analyzer** (Scrapling + httpx) visits each website, scores it (0-100)
6. **Finalize** updates lead categories → `hot` (no site), `warm` (poor site), `skip` (decent site)
7. **User** views, filters, and manages leads in the CRM-style dashboard
8. **AI Pitch** (DeepSeek API) generates personalized outreach copy on demand

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 14 (App Router), React 18, TypeScript |
| **Styling** | Tailwind CSS v4, Framer Motion, Lucide Icons |
| **State** | Zustand (client state), React Hook Form + Zod (forms) |
| **Backend** | Python 3.12, FastAPI, uvicorn |
| **Database** | Supabase (PostgreSQL) with Row-Level Security |
| **Auth** | Supabase Auth (email/password, Google OAuth) |
| **AI** | DeepSeek API (chat completions) |
| **Scraping** | `google-maps-scraper` (Go binary), Scrapling (Python) |
| **HTTP** | Axios (frontend), httpx (backend) |
| **Container** | Docker (multi-stage: Go builder + Python runtime) |

---

## Project Structure

```
Lead-Forge-Ai/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entrypoint, lifespan, CORS
│   │   ├── config.py                  # pydantic-settings config
│   │   ├── database.py                # Supabase client factories
│   │   ├── middleware/
│   │   │   └── auth_middleware.py      # Bearer token verification
│   │   ├── routers/
│   │   │   ├── auth.py                # GET/PUT /api/auth/*
│   │   │   ├── search.py              # CRUD /api/searches/*
│   │   │   ├── leads.py               # CRUD + export /api/leads/*
│   │   │   ├── dashboard.py           # GET /api/dashboard/stats
│   │   │   └── ai.py                  # POST /api/ai/pitch/{id}
│   │   ├── schemas/
│   │   │   ├── user.py                # Pydantic user schemas
│   │   │   ├── search.py              # Pydantic search schemas
│   │   │   └── lead.py                # Pydantic lead schemas
│   │   ├── services/
│   │   │   ├── pipeline.py            # Search orchestration (semaphore, stages)
│   │   │   ├── scraper_service.py     # Go binary subprocess wrapper
│   │   │   ├── analyzer_service.py    # Website analysis (Scrapling + httpx)
│   │   │   ├── ai_service.py          # DeepSeek pitch generation
│   │   │   └── auth_service.py        # User profile CRUD
│   │   └── utils/
│   │       └── helpers.py             # Shared utilities
│   ├── google-maps-scraper/           # Go scraper module (submodule)
│   ├── Scrapling/                     # Vendored Scrapling library
│   ├── scripts/                       # run-api.sh, run-api.ps1, systemd unit
│   ├── Dockerfile                     # Multi-stage Docker build
│   ├── requirements.txt
│   ├── .env                           # Backend env vars
│   └── supabase-schema.sql            # Database schema
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx             # Root layout, providers
│   │   │   ├── page.tsx               # Landing page
│   │   │   ├── not-found.tsx          # 404 page
│   │   │   ├── login/page.tsx         # Login (Google + email/password)
│   │   │   ├── signup/page.tsx        # Signup
│   │   │   ├── auth/callback/page.tsx # OAuth callback handler
│   │   │   └── dashboard/
│   │   │       ├── layout.tsx         # Auth-protected dashboard shell
│   │   │       ├── page.tsx           # Overview with stats
│   │   │       ├── search/page.tsx    # New search form + progress
│   │   │       ├── leads/page.tsx     # Filterable lead grid
│   │   │       ├── leads/[id]/page.tsx# Lead detail + AI pitch
│   │   │       ├── history/page.tsx   # Past search history
│   │   │       ├── settings/page.tsx  # User profile
│   │   │       └── export/page.tsx    # CSV export
│   │   ├── components/
│   │   │   ├── auth/AuthProvider.tsx  # Supabase auth listener
│   │   │   ├── dashboard/
│   │   │   │   ├── Sidebar.tsx        # Navigation
│   │   │   │   ├── StatsCards.tsx     # Dashboard stats grid
│   │   │   │   ├── FiltersBar.tsx     # Lead filter controls
│   │   │   │   ├── LeadCard.tsx       # Lead summary card
│   │   │   │   ├── SearchProgressCard.tsx # Live progress tracker
│   │   │   │   └── EmptyState.tsx     # Empty list state
│   │   │   ├── landing/
│   │   │   │   ├── Hero.tsx
│   │   │   │   ├── Features.tsx
│   │   │   │   ├── HowItWorks.tsx
│   │   │   │   └── Footer.tsx
│   │   │   └── shared/
│   │   │       ├── GlassCard.tsx      # Glassmorphism card
│   │   │       ├── Badge.tsx          # Status badges
│   │   │       ├── Skeleton.tsx       # Loading skeletons
│   │   │       ├── LoadingButton.tsx  # Button with spinner
│   │   │       ├── Toast.tsx          # Toast notifications
│   │   │       └── FullPageLoader.tsx # Full-page loading
│   │   ├── hooks/
│   │   │   ├── useAuth.ts            # Auth operations
│   │   │   ├── useSearch.ts          # Search + polling
│   │   │   ├── useLeads.ts           # Lead CRUD + export
│   │   │   └── useToast.ts           # Toast state (Zustand)
│   │   ├── stores/
│   │   │   ├── authStore.ts          # Auth state
│   │   │   ├── searchStore.ts        # Active search state
│   │   │   └── leadStore.ts          # Leads + filters
│   │   ├── lib/
│   │   │   ├── api.ts                # Axios client + auth interceptor
│   │   │   ├── supabase.ts           # Supabase client
│   │   │   ├── constants.ts          # Routes, categories, statuses
│   │   │   └── utils.ts              # cn(), formatDate(), etc.
│   │   └── styles/
│   │       └── globals.css           # Tailwind v4 + custom theme
│   ├── .env.local                    # Frontend env vars
│   ├── next.config.ts
│   ├── package.json
│   └── tsconfig.json
│
└── README.md
```

---

## Prerequisites

| Dependency | Version | Notes |
|-----------|---------|-------|
| Python | 3.12+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| Go | 1.21+ | Only needed if building the scraper locally |
| Supabase | Project | Free tier works — set up at [supabase.com](https://supabase.com) |
| DeepSeek | API key | Already in `.env` |

---

## Setup

### 1. Clone & Install Dependencies

```powershell
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Install vendored Scrapling
cd Scrapling
pip install -e .
cd ..

# Frontend
cd ../frontend
npm install
```

### 2. Database (Supabase)

1. Create a new Supabase project
2. Go to **SQL Editor** → paste and run `backend/supabase-schema.sql`
3. Enable **Row-Level Security** on the `searches` and `leads` tables (optional)
4. Copy your project URL, anon key, and service role key to `backend/.env`

### 3. Environment Variables

**`backend/.env`** — already configured:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJ...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJ...
DEEPSEEK_API_KEY=sk-your-key
GMAPS_SCRAPER_PATH=C:\path\to\google-maps-scraper.exe
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000
ENVIRONMENT=development
```

**`frontend/.env.local`** — already configured:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJ...
```

### 4. Build the Scraper Binary

```powershell
# Option A: Build from source (requires Go)
cd backend/google-maps-scraper
go build -o google-maps-scraper.exe .

# Option B: Point GMAPS_SCRAPER_PATH to an existing binary
```

### 5. Run

```powershell
# Terminal 1 — Backend
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

Open **http://localhost:3000** → Sign up → Start your first search.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/auth/me` | Get current user profile |
| `PUT` | `/api/auth/profile` | Update profile (name, avatar) |
| `POST` | `/api/searches` | Create new search |
| `GET` | `/api/searches` | Search history (paginated) |
| `GET` | `/api/searches/{id}` | Search detail |
| `GET` | `/api/searches/{id}/status` | Polling status (lightweight) |
| `POST` | `/api/searches/{id}/cancel` | Cancel running search |
| `GET` | `/api/leads` | List leads (filtered, paginated) |
| `GET` | `/api/leads/export` | Export CSV |
| `GET` | `/api/leads/{id}` | Lead detail |
| `PATCH` | `/api/leads/{id}/status` | Update user status |
| `PATCH` | `/api/leads/{id}/notes` | Update notes |
| `PATCH` | `/api/leads/{id}/favorite` | Toggle favorite |
| `GET` | `/api/dashboard/stats` | Dashboard aggregates |
| `POST` | `/api/ai/pitch/{lead_id}` | Generate AI pitch |

---

## Search Pipeline Stages

| Stage | Progress | Description |
|-------|----------|-------------|
| `queued` | 0% | Search created, waiting for slot |
| `scraping` | 5-40% | Go binary scraping Google Maps |
| `analyzing` | 50-95% | Website analysis (5 concurrent) |
| `completed` | 100% | Counts finalized, leads ready |

- **Max concurrent searches**: 3 (asyncio semaphore)
- **Per-search timeout**: 10 minutes
- **Max results per search**: 50
- **Results preserved on timeout**: yes (partial CSV parsed)

---

## Lead Categories

| Category | Meaning | Website Health Score | Opportunity |
|----------|---------|---------------------|-------------|
| **Hot** | No website found | N/A | Build a new site |
| **Warm** | Poor or broken website | 0-49 | Redesign opportunity |
| **Skip** | Decent website | 50-100 | Low opportunity |

---

## Deployment

### Docker
```bash
docker build -t leadforge-backend -f backend/Dockerfile .
docker run -p 8000:8000 --env-file backend/.env leadforge-backend
```

### Frontend Build
```powershell
cd frontend
npm run build
npm start
```

### Systemd (Linux)
```bash
sudo cp backend/scripts/systemd/leadforge-backend.service /etc/systemd/system/
sudo systemctl enable leadforge-backend
sudo systemctl start leadforge-backend
```

---

## Tech Notes

- **Supabase client** is created with `lru_cache` to reuse connections
- **Scraper runs** in a subprocess via `asyncio.to_thread` — doesn't block the event loop
- **Website analysis** uses Scrapling with a synchronous-fallback-to-httpx pattern, also threaded
- **Auth middleware** verifies the Bearer token via Supabase `auth.get_user()` on every request
- **Pitch generation** uses DeepSeek's `deepseek-chat` model with a system prompt for sales copywriting
- **CSV export** streams the response using FastAPI's `StreamingResponse`

---

## License

Apache License 2.0 — see `backend/LICENSE`.
