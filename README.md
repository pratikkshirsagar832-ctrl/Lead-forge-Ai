# Hyperclients (Lead Forge AI)

**AI lead generation platform.** Find people who are asking for your service right now on LinkedIn, pull local businesses from Google Maps, and qualify everything with AI.

> **Production:** [https://hyperclients.online](https://hyperclients.online)

---

## What it does

| Feature | How it works |
|---|---|
| **LinkedIn buyer leads** | SocialCrawl searches public LinkedIn posts with buyer phrases ("can anyone recommend an accountant"), DeepSeek classifies each post, and only genuine, fresh buyers are saved: exactly the number you asked for |
| **Google Maps leads** | A Go scraper pulls local businesses; websites can be analysed on demand |
| **CRM + AI outreach** | Pipeline board, notes, CSV export, AI pitches and short outreach messages |
| **Public API** | Pay-per-lead REST API with a prepaid wallet and signed webhooks (`/v1`) |
| **Teams** | Pro and Agency owners add team seats that share the owner's plan |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (app router), React 18, TypeScript 5, Tailwind CSS 4, Zustand, Framer Motion |
| Backend | Python 3.12, FastAPI, uvicorn |
| Database / auth | Supabase (Postgres + RLS, email + Google login) |
| AI | DeepSeek (lead classification), OpenAI (pitches, website analysis) |
| Data sources | SocialCrawl (LinkedIn posts), Go google-maps-scraper (Maps), Scrapling (websites) |
| Payments | Razorpay |
| Deploy | Docker Compose on a VPS behind nginx |

---

## Quick start

```bash
git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai.git
cd Lead-forge-Ai
# create backend/.env and frontend/.env.local (see below)
docker compose up -d --build
# frontend http://localhost:3001  |  backend http://localhost:8000
```

Local development:

```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev
```

Tests: `cd backend && python -m pytest tests ha/tests -q` and `cd frontend && npx tsc --noEmit`.

---

## Environment variables

### `backend/.env`

```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
DEEPSEEK_API_KEY=...            # lead classifier
OPENAI_API_KEY=...              # pitches + website analysis
SOCIALCRAWL_API_KEY=sc_...      # LinkedIn post search
SOCIALCRAWL_API_KEYS=sc_...,sc_...  # more keys; rotated automatically when one runs out
ADMIN_API_TOKEN=...             # long random secret, SAME value in frontend/.env.local
RAZORPAY_KEY_ID=...             # payments (optional in dev)
RAZORPAY_KEY_SECRET=...
FRONTEND_URL=https://hyperclients.online
ENVIRONMENT=production

LINKEDIN_TOKEN_KEY=...          # Fernet key encrypting stored SocialCrawl keys - never change it
```

### `frontend/.env.local` (template: `frontend/.env.example`)

```bash
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
NEXT_PUBLIC_API_URL=http://localhost:8000
ADMIN_PASSWORD=...              # /admin blog CMS + API keys page
ADMIN_API_TOKEN=...             # same value as the backend
```

---

## Project structure

```
backend/
  app/
    main.py                 FastAPI app, routers
    routers/                auth, search, leads, dashboard, ai, subscriptions,
                            developer, public_api (/v1)
    services/
      hyperagent_service.py LinkedIn lead engine wiring (SocialCrawl + DeepSeek)
      pipeline.py, scraper_service.py   Google Maps pipeline
      plans.py, usage.py    plans, quotas, team seats
  ha/                       lead engine: query builder, discovery, classifier, scoring
  google-maps-scraper/      Go scraper (built in the Docker image)
  tests/, ha/tests/
frontend/
  src/app/                  pages (dashboard, search, leads, blogs, admin)
  src/components/, src/lib/, src/stores/, src/hooks/
  lib/                      server-side blog / admin helpers
  data/                     seed content for the blog (runtime copy lives in a Docker volume)
supabase/                   SQL migrations (run in order in the SQL editor)
deploy/nginx/               nginx site config
docs/                       documentation
```

---

## How a LinkedIn search works

1. The query builder turns the service into many buyer phrasings, one quoted phrase per query.
2. SocialCrawl returns fresh public posts (full text, author, exact publish time), newest first.
3. Cheap filters drop duplicates, stale posts, sellers and job ads before any AI call.
4. DeepSeek classifies intent, service match and lead quality; strict gates decide.
5. Deleted posts are checked and dropped; exactly N new leads are saved per user.

Details: `docs/03-LINKEDIN-PIPELINE.md` and `docs/linkedin-pipeline-audit.md`.

---

## SocialCrawl keys (auto-rotation)

All SocialCrawl keys live in one pool (`socialcrawl_keys` table, encrypted; migration v23). LinkedIn searches use the first active key; when it runs out of credits (HTTP 402) the **same request is retried on the next key** and the empty key is marked "Out of credits". Manage keys at **`/admin/keys`**: add (validated live), disable, remove, check balances, and see credits left / used / calls per key. Keys in `SOCIALCRAWL_API_KEY(S)` are imported automatically.

## Blog data

Blogs and drafts published from `/admin` are stored in the `blog-data` Docker volume (`BLOGS_DATA_DIR=/app/storage`), **not** in the git checkout, so deploys (`git pull`, re-clone, rebuild) never delete them. `frontend/data/*.json` only seeds the volume the first time.

---

## Documentation

| File | Content |
|---|---|
| `docs/14-PUBLIC-API.md` | Public API v1, wallet, webhooks |
| `docs/linkedin-pipeline-audit.md` | LinkedIn lead engine deep dive |
| `docs/01` - `docs/12` | Original project docs (some sections predate the SocialCrawl engine) |

---

## License

Apache License 2.0
