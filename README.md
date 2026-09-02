# Lead Forge AI (Hyperclients)

**AI-Powered Lead Generation & Outreach Platform** — Find qualified B2B leads from LinkedIn and Google Maps, score them with AI, and generate personalized outreach pitches.

> **Production:** [https://hyperclients.online](https://hyperclients.online)
> **Version:** 2.2.0
> **License:** Apache 2.0

---

## What It Does

```
User: "website development" + "India" + "buyer"
                    ↓
┌─────────────────────────────────────────────┐
│  1. SEARCH                                 │
│  LinkedIn (Apify) + Google Maps (Go binary) │
│  12 parallel lanes × 4 queries = 720 posts  │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  2. AI QUALIFICATION                        │
│  Stage 1: Triage (cheap filter)             │
│  Stage 2: 6-dimension scoring (0-100)       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  3. FILTER & SAVE                           │
│  Country gate + type gate + tier acceptance  │
│  Hot (≥85) / Warm (50-84) categories        │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  4. MANAGE & OUTREACH                       │
│  CRM dashboard + AI pitch generation        │
│  Pipeline: New → Contacted → Converted      │
└─────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 16, React 18, TypeScript 5, Tailwind CSS 4 |
| **State** | Zustand, Framer Motion, @dnd-kit |
| **Backend** | Python 3.12, FastAPI, uvicorn |
| **Database** | Supabase (PostgreSQL + RLS) |
| **Auth** | Supabase Auth (email + Google OAuth) |
| **AI** | OpenAI gpt-4o-mini (scoring, pitches), gpt-4o (website analysis) |
| **Scraping** | Apify (LinkedIn), Go binary (Google Maps), Scrapling (websites) |
| **Payments** | Razorpay (subscriptions) |
| **Deploy** | Docker Compose, Contabo VPS |

---

## Quick Start

### Docker (Recommended)
```bash
git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai.git
cd Lead-Forge-Ai

# Set up environment
cp backend/.env.example backend/.env   # Fill in API keys
cp frontend/.env.local.example frontend/.env.local

# Run
docker compose up -d --build

# Access
# Frontend: http://localhost:3001
# Backend:  http://localhost:8000
```

### Local Development
```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

---

## Environment Variables

### Backend (`.env`)
```bash
# Required
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
OPENAI_API_KEY=sk-...
APIFY_API_KEY=apify_api_...

# Optional (for payments)
RAZORPAY_KEY_ID=rzp_...
RAZORPAY_KEY_SECRET=...

# URLs
FRONTEND_URL=http://localhost:3001
BACKEND_URL=http://localhost:8000
```

### Frontend (`.env.local`)
```bash
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=http://localhost:8000
ADMIN_PASSWORD=@PatilHyperclients@1234
```

---

## Project Structure

```
Lead-Forge-Ai/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Settings (env vars)
│   │   ├── database.py          # Supabase clients
│   │   ├── routers/             # API endpoints (7 files)
│   │   ├── schemas/             # Pydantic models
│   │   ├── services/            # Business logic
│   │   │   ├── linkedin_pipeline.py   # CORE: LinkedIn pipeline (2,540 lines)
│   │   │   ├── apify_service.py       # Apify multi-key failover
│   │   │   ├── pipeline.py            # Google Maps pipeline
│   │   │   ├── enhanced_analyzer.py   # Website crawling
│   │   │   ├── deep_analyzer.py       # AI website scoring
│   │   │   └── ai_service.py          # Pitch generation
│   │   ├── middleware/           # Auth + rate limiting
│   │   └── utils/               # Helpers
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js pages (23 pages)
│   │   ├── components/          # React components (39 files)
│   │   ├── hooks/               # Custom hooks
│   │   ├── stores/              # Zustand state
│   │   ├── lib/                 # Utilities
│   │   └── styles/              # CSS (495 lines)
│   ├── Dockerfile
│   └── package.json
│
├── supabase/
│   └── migration.sql            # Database schema
│
├── docker-compose.yml
└── docs/                        # Documentation (12 files)
    ├── 01-PROJECT-OVERVIEW.md
    ├── 02-BACKEND-API.md
    ├── 03-LINKEDIN-PIPELINE.md
    ├── 04-FRONTEND.md
    ├── 05-SERVICES-EXTERNAL.md
    ├── 06-DATABASE-AND-DEPLOYMENT.md
    ├── 07-AI-SCORING-GUIDE.md
    ├── 08-APIFY-INTEGRATION.md
    ├── 09-FRONTEND-COMPONENTS.md
    ├── 10-API-ENDPOINTS.md
    ├── 11-TROUBLESHOOTING.md
    └── 12-DEPLOYMENT-GUIDE.md
```

---

## API Endpoints

### Auth
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/me` | Current user + subscription |
| `GET` | `/api/auth/team` | List team members |
| `POST` | `/api/auth/team` | Add team member |

### Searches
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/searches` | Create search |
| `GET` | `/api/searches` | Search history |
| `GET` | `/api/searches/{id}/status` | Polling status |
| `GET` | `/api/searches/{id}/results` | Progressive results |
| `POST` | `/api/searches/{id}/cancel` | Cancel search |

### Leads
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/leads` | List leads (filters) |
| `GET` | `/api/leads/export` | CSV export |
| `GET` | `/api/leads/{id}` | Lead detail |
| `PATCH` | `/api/leads/{id}/status` | Update status |
| `PATCH` | `/api/leads/{id}/notes` | Update notes |
| `PATCH` | `/api/leads/{id}/favorite` | Toggle favorite |

### AI
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ai/pitch/{lead_id}` | Generate pitch |
| `POST` | `/api/ai/website-message/{lead_id}` | Short message |

### Subscriptions
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/subscriptions/plans` | List plans |
| `POST` | `/api/subscriptions/create-order` | Create order |
| `POST` | `/api/subscriptions/verify` | Verify payment |

---

## AI Scoring System

### Two-Stage Pipeline

**Stage 1: Triage** (gpt-4o-mini, $0.001/batch)
- Binary classification: is_lead?
- Classifies lead_type: explicit_need, problem_awareness, research, hiring, seller, irrelevant
- Rejects sellers, irrelevant, non-English

**Stage 2: Deep Scoring** (gpt-4o-mini, $0.002/lead)
- 6 dimensions, each 0-100:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Intent | 30% | Buying/hiring signal clarity |
| Fit | 20% | Niche match |
| Urgency | 15% | How urgently they need help |
| Engagement | 10% | Post reactions/comments |
| Recency | 10% | How recent is the post |
| Decision-Maker | 15% | Is author a decision-maker |

### Lead Categories
- **Hot** (≥85): High intent + good fit + decision-maker
- **Warm** (50-84): Moderate quality
- **Rejected** (<50): Not qualified

---

## LinkedIn Pipeline

### Search Flow
1. Generate 12 discovery phrases from niche
2. Fire 12 parallel Apify lanes (4 queries × 15 posts)
3. Dedupe by author (keep best post)
4. Country filtering (user-driven)
5. AI triage + deep scoring
6. Tiered acceptance (≥80, ≥65, ≥50)
7. Job filler (hiring searches only)
8. Save to database

### Buyer Mode
When searching for genuine buyers (not hiring):
- Boolean NOT operators: `NOT "I offer" NOT "available for"`
- Author keywords: Founder, CEO, Owner, Director, Manager

### Key Constants
```python
MAX_RESULTS_CAP = 50
AI_ASYNC_CONCURRENCY = 12
MAX_WAVES = 4
WAVE_DEADLINE_SECONDS = 480
```

---

## Database Schema

### Tables
| Table | Purpose |
|-------|---------|
| `plans` | Subscription plans |
| `user_subscriptions` | User subscriptions |
| `daily_usage` | Daily usage tracking |
| `searches` | Search history |
| `leads` | Lead data (core) |
| `website_analyses` | Website analysis |

### Key Features
- Row Level Security (RLS) on all tables
- Auto-create free trial on signup
- Auto-increment usage on lead insert
- Team system via razorpay_order_id marker

---

## Deployment

### Production Server
- **Host:** Contabo VPS (`178.16.138.221`)
- **Containers:** backend, frontend
- **Deploy:** `docker compose up -d --build`

### Deploy Script
```bash
# From local
ssh root@178.16.138.221 "cd /root/leadforge && docker compose up -d --build"
```

### SSL/HTTPS
```bash
# Using Nginx + Let's Encrypt
apt install certbot python3-certbot-nginx
certbot --nginx -d hyperclients.online
```

---

## Monitoring

### Health Check
```bash
curl http://localhost:8000/api/health
```

### Docker Stats
```bash
docker stats
docker compose logs backend --tail 50
```

---

## Cost Analysis

### Per Search (10 leads)
| Stage | Cost |
|-------|------|
| Apify (180 posts) | $0.27 |
| AI Triage | $0.001 |
| AI Scoring | $0.002 |
| **Total** | **~$0.27** |

### Monthly (100 searches)
| Item | Cost |
|------|------|
| Apify | $27 |
| OpenAI | $0.40 |
| **Total** | **~$27.40** |

---

## Documentation

Complete documentation in `docs/`:

| File | Content |
|------|---------|
| `01-PROJECT-OVERVIEW.md` | Project description, tech stack, directory structure |
| `02-BACKEND-API.md` | FastAPI routers, endpoints, schemas |
| `03-LINKEDIN-PIPELINE.md` | Core pipeline, AI scoring, Apify |
| `04-FRONTEND.md` | Next.js pages, components, hooks |
| `05-SERVICES-EXTERNAL.md` | Apify, OpenAI, Supabase, Razorpay |
| `06-DATABASE-AND-DEPLOYMENT.md` | DB schema, Docker, deploy |
| `07-AI-SCORING-GUIDE.md` | Complete AI scoring system |
| `08-APIFY-INTEGRATION.md` | Full Apify guide |
| `09-FRONTEND-COMPONENTS.md` | All components detailed |
| `10-API-ENDPOINTS.md` | All endpoints with examples |
| `11-TROUBLESHOOTING.md` | Common issues and fixes |
| `12-DEPLOYMENT-GUIDE.md` | Step-by-step deploy |

---

## License

Apache License 2.0
