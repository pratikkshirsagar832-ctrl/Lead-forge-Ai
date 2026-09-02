# 01 — PROJECT OVERVIEW

## What Is This?

**Lead Forge AI (Hyperclients)** is an AI-powered lead generation and outreach platform. It finds potential clients (buyers) on LinkedIn and Google Maps, qualifies them with AI, scores them, and generates personalized outreach pitches.

**Production URL:** `https://hyperclients.online`
**Version:** 2.2.0
**License:** Apache 2.0

---

## How It Works (End to End)

```
User enters: "website development" + "India" + "buyer"
                ↓
┌─────────────────────────────────────────────┐
│  1. SEARCH PHASE                            │
│  - Apify LinkedIn Post Search (12 lanes)    │
│  - Apify LinkedIn Job Search (job filler)   │
│  - Google Maps Scraper (Go binary)          │
└─────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────┐
│  2. AI QUALIFICATION (2 stages)             │
│  - Triage: gpt-4o-mini (cheap, batches)     │
│  - Score: gpt-4o-mini (12 concurrent async) │
│  - Score: 0-100 across 6 dimensions         │
└─────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────┐
│  3. FILTERING                               │
│  - Country gate (user-driven)               │
│  - Lead type filter (buyer/hiring)           │
│  - Tiered acceptance (strict → relaxed)     │
│  - Job filler (hiring searches only)        │
└─────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────┐
│  4. SAVE & DISPLAY                          │
│  - Supabase bulk insert                     │
│  - Progressive loading (batches of 4)       │
│  - AI pitch generation on demand            │
└─────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend
| Technology | Purpose |
|-----------|---------|
| **Python 3.12** | Core runtime |
| **FastAPI** | REST API framework |
| **Supabase Python Client** | Database (no ORM) |
| **OpenAI gpt-4o-mini** | AI scoring, triage, pitch generation |
| **OpenAI gpt-4o** | Website quality analysis |
| **Apify** | LinkedIn post search, job search, profile scraping |
| **Scrapling** | Website crawling for analysis |
| **Go (google-maps-scraper)** | Google Maps business scraping |
| **Razorpay** | Payment processing |
| **Docker** | Containerization |
| **uvicorn** | ASGI server |

### Frontend
| Technology | Purpose |
|-----------|---------|
| **Next.js 16.3** | React framework (App Router) |
| **React 18.3** | UI library |
| **TypeScript 5** | Type safety |
| **Tailwind CSS 4** | Utility-first CSS |
| **Framer Motion** | Animations |
| **Zustand** | State management |
| **Supabase JS** | Auth client |
| **Axios** | HTTP client |
| **Radix UI** | Accessible components |
| **Three.js** | 3D visual effects |

### Infrastructure
| Technology | Purpose |
|-----------|---------|
| **Docker Compose** | Multi-container orchestration |
| **Contabo VPS** | Production server (178.16.138.221) |
| **Supabase Cloud** | PostgreSQL database + auth |
| **GitHub** | Version control |

---

## Directory Structure

```
Lead-Forge-Ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint (99 lines)
│   │   ├── config.py            # Settings from env (110 lines)
│   │   ├── database.py          # Supabase clients (47 lines)
│   │   ├── routers/             # API endpoints (7 files, 1,823 lines)
│   │   │   ├── auth.py          # /api/auth/* (317 lines)
│   │   │   ├── search.py        # /api/searches/* (522 lines)
│   │   │   ├── leads.py         # /api/leads/* (377 lines)
│   │   │   ├── subscriptions.py # /api/subscriptions/* (345 lines)
│   │   │   ├── dashboard.py     # /api/dashboard/* (44 lines)
│   │   │   └── ai.py            # /api/ai/* (196 lines)
│   │   ├── schemas/             # Pydantic models (4 files, 241 lines)
│   │   │   ├── search.py        # SearchCreateRequest, SearchResponse
│   │   │   ├── lead.py          # LeadListItem, LeadDetail
│   │   │   └── user.py          # UserResponse, CurrentUserResponse
│   │   ├── services/            # Business logic (8 files, 4,444 lines)
│   │   │   ├── linkedin_pipeline.py   # CORE: LinkedIn pipeline (2,540 lines)
│   │   │   ├── apify_service.py       # Apify multi-key failover (572 lines)
│   │   │   ├── pipeline.py            # Google Maps pipeline (293 lines)
│   │   │   ├── scraper_service.py     # Go scraper wrapper (316 lines)
│   │   │   ├── enhanced_analyzer.py   # Website crawling (759 lines)
│   │   │   ├── deep_analyzer.py       # AI website scoring (261 lines)
│   │   │   ├── ai_service.py          # Pitch generation (280 lines)
│   │   │   ├── plans.py               # Plan resolution (122 lines)
│   │   │   └── analyzer_service.py    # Orchestrator (41 lines)
│   │   ├── middleware/           # Auth + rate limiting (3 files, 171 lines)
│   │   │   ├── auth_middleware.py  # JWT verification
│   │   │   └── usage_middleware.py # Search rate limit
│   │   └── utils/               # Helpers (87 lines)
│   │       └── helpers.py       # utc_now, safe_str, normalize_url
│   ├── Dockerfile               # Multi-stage: Go builder + Python runtime
│   ├── requirements.txt         # 12 Python dependencies
│   └── .env                     # Secrets (gitignored)
│
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router (23 pages)
│   │   │   ├── layout.tsx       # Root layout + fonts + scripts
│   │   │   ├── page.tsx         # Landing page
│   │   │   ├── login/page.tsx   # Auth login
│   │   │   ├── pricing/page.tsx # Pricing plans
│   │   │   ├── dashboard/       # Main app
│   │   │   │   ├── layout.tsx   # Dashboard shell
│   │   │   │   ├── page.tsx     # Overview stats
│   │   │   │   ├── search/page.tsx    # LinkedIn search UI
│   │   │   │   ├── leads/page.tsx     # Lead list
│   │   │   │   ├── leads/[id]/page.tsx # Lead detail
│   │   │   │   ├── history/page.tsx   # Search history
│   │   │   │   ├── billing/page.tsx   # Subscription
│   │   │   │   ├── settings/page.tsx  # Account
│   │   │   │   └── team/page.tsx      # Team management
│   │   │   ├── admin/           # Admin panel
│   │   │   ├── blogs/           # Content pages
│   │   │   └── tools/           # SEO tools
│   │   ├── components/          # React components (39 files)
│   │   │   ├── landing/         # Hero, Features, HowItWorks
│   │   │   ├── dashboard/       # Sidebar, LeadCard, FiltersBar
│   │   │   ├── auth/            # AuthGuard
│   │   │   ├── shared/          # GlassCard, Badge, Modal, Toast
│   │   │   └── ui/              # Radix-based primitives
│   │   ├── hooks/               # Custom React hooks (3 files)
│   │   │   ├── useSearch.ts     # Search orchestration (247 lines)
│   │   │   ├── useLeads.ts      # Lead CRUD (160 lines)
│   │   │   └── useToast.ts      # Notifications
│   │   ├── stores/              # Zustand stores (2 files)
│   │   │   ├── searchStore.ts   # Search state
│   │   │   └── leadStore.ts     # Leads state + filters
│   │   ├── lib/                 # Utilities (6 files)
│   │   │   ├── api.ts           # Axios with auth interceptor
│   │   │   ├── supabase.ts      # Supabase browser client
│   │   │   ├── constants.ts     # API routes, statuses, colors
│   │   │   ├── types.ts         # TypeScript interfaces
│   │   │   ├── utils.ts         # cn(), formatDate(), truncate()
│   │   │   └── animations.tsx   # Framer Motion variants
│   │   └── styles/
│   │       └── globals.css      # Design system (495 lines)
│   ├── Dockerfile               # Multi-stage Node build
│   ├── package.json             # Dependencies
│   └── next.config.mjs          # Proxy + rewrites
│
├── supabase/
│   ├── migration.sql            # Main schema (490 lines)
│   └── migration_linkedin*.sql  # Migration scripts
│
├── docker-compose.yml           # Backend + Frontend containers
├── deploy-contabo.sh            # Server deploy script
├── e2e_search.py                # End-to-end test script
├── API'S.txt                    # API reference notes
├── Design/                      # Design assets
├── New-assets/                  # Marketing assets
└── README.md                    # Project documentation (453 lines)
```

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Total files | ~113 |
| Total lines of code | ~16,800 |
| Largest file | `linkedin_pipeline.py` (2,540 lines) |
| Backend Python dependencies | 12 |
| Frontend npm packages | ~40 |
| Database tables | 7 |
| API endpoints | ~30 |
| React components | ~39 |
| Apify API keys supported | 24 |

---

## Environment Variables

### Backend (`.env`)
```bash
# Supabase
SUPABASE_URL=https://gzxmgdkpsdqkxrnpplyh.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# OpenAI
OPENAI_API_KEY=sk-...

# Apify (up to 24 keys for rotation)
APIFY_API_KEY=apify_api_...
APIFY_API_KEY_2=apify_api_...
# ... up to APIFY_API_KEY_24

# Razorpay
RAZORPAY_KEY_ID=rzp_...
RAZORPAY_KEY_SECRET=...

# URLs
FRONTEND_URL=http://localhost:3001
BACKEND_URL=http://localhost:8000
SITE_URL=http://localhost:3001
```

### Frontend (`.env.local`)
```bash
NEXT_PUBLIC_SUPABASE_URL=https://gzxmgdkpsdqkxrnpplyh.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=http://localhost:8000
ADMIN_PASSWORD=@PatilHyperclients@1234
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai.git
cd Lead-Forge-Ai

# Set up environment
cp backend/.env.example backend/.env  # Fill in keys
cp frontend/.env.local.example frontend/.env.local  # Fill in keys

# Run with Docker
docker compose up -d --build

# Access
# Frontend: http://localhost:3001
# Backend:  http://localhost:8000
# API Docs: http://localhost:8000/docs (dev only)
```

---

## Production Server

- **Host:** Contabo VPS (`178.16.138.221`)
- **Containers:** `leadforge-backend-1`, `leadforge-frontend-1`, `leadforge-postgres-1`
- **Deploy:** SFTP upload + `docker compose up -d --build`
- **Admin:** `/admin/login` with password `@PatilHyperclients@1234`
