# 02 — BACKEND API (FastAPI)

## Architecture

```
backend/app/
├── main.py              # FastAPI app factory + lifespan
├── config.py            # Pydantic Settings (env vars)
├── database.py          # Supabase client singletons
├── routers/             # HTTP endpoints (7 modules)
├── schemas/             # Pydantic request/response models
├── services/            # Business logic
├── middleware/           # Auth + rate limiting
└── utils/               # Helpers
```

**No ORM** — all DB operations use the Supabase Python client directly. This means:
- No SQLAlchemy, no Alembic migrations
- Supabase handles RLS, auth, real-time
- Backend uses `supabase.table("leads").select(...)` style queries

---

## Entry Point: `main.py`

```python
app = create_app()
```

### Lifespan Events

| Event | Action |
|-------|--------|
| **Startup** | Recover stale searches (queued/scraping/analyzing > 15min → failed) |
| **Shutdown** | Log exit |

### CORS Configuration

```python
# Production: only frontend URL
# Development: frontend + localhost variants
origins = settings.cors_origins
```

### API Routes (all mounted)

| Router | Prefix | File |
|--------|--------|------|
| `auth_router` | `/api/auth` | `routers/auth.py` |
| `subscriptions_router` | `/api/subscriptions` | `routers/subscriptions.py` |
| `search_router` | `/api/searches` | `routers/search.py` |
| `leads_router` | `/api/leads` | `routers/leads.py` |
| `dashboard_router` | `/api/dashboard` | `routers/dashboard.py` |
| `ai_router` | `/api/ai` | `routers/ai.py` |

---

## Configuration: `config.py`

Pydantic Settings class that reads from `.env`:

```python
class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    
    # OpenAI
    openai_api_key: str
    
    # Apify (24 possible keys)
    apify_api_key: str = ""
    apify_api_key_2: str = ""
    # ... up to apify_api_key_24
    
    # Razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    
    # URLs
    frontend_url: str = "http://localhost:3001"
    backend_url: str = "http://localhost:8000"
    site_url: str = "http://localhost:3001"
```

### Key Properties

| Property | Description |
|----------|-------------|
| `is_production` | `True` if `ENVIRONMENT=production` |
| `apify_keys` | List of all non-empty Apify keys (collected via model_validator) |
| `scraper_binary_path` | Absolute path to Go scraper binary |
| `cors_origins` | Frontend URL + localhost in dev |

---

## Database: `database.py`

Two singleton clients:

```python
# Anon key — respects RLS (for user-facing ops)
def get_supabase_client() -> Client:
    return create_client(url, anon_key)

# Service role — bypasses RLS (for admin/background ops)
def get_supabase_admin() -> Client:
    return create_client(url, service_role_key)
```

---

## Router: Auth (`/api/auth`)

### Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/auth/me` | Get current user + subscription | Yes |
| `GET` | `/api/auth/team` | List team members | Yes (Pro/Agency) |
| `POST` | `/api/auth/team` | Add team member | Yes (Pro/Agency) |
| `DELETE` | `/api/auth/team/{id}` | Remove team member | Yes (Pro/Agency) |
| `POST` | `/api/auth/team-resolve` | Convert team username → email | No |

### Key Logic: Team System

```
Team member row:
  razorpay_order_id = "team:{owner_uuid}:{username}"
  
  → On login, detect this pattern
  → Resolve owner's subscription
  → Copy owner's plan to team member
```

**Plan Seats:**
- `pro` = 2 seats
- `agency` = 10 seats

### `GET /api/auth/me`

Returns:
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "subscription": {
    "plan_id": "pro",
    "status": "active",
    "searches_remaining": 5,
    "leads_remaining": 50
  }
}
```

The `remaining` values are computed from `daily_usage` table:
```python
remaining_searches = plan.searches_per_day - usage.searches_run
remaining_leads = plan.leads_per_day - usage.leads_generated
```

---

## Router: Search (`/api/searches`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/searches` | Create search + spawn background task |
| `GET` | `/api/searches` | Paginated search history |
| `GET` | `/api/searches/scraper-health` | Check Go binary exists |
| `GET` | `/api/searches/{id}` | Full search detail |
| `GET` | `/api/searches/{id}/status` | Lightweight polling endpoint |
| `GET` | `/api/searches/{id}/results` | Progressive lead loading |
| `POST` | `/api/searches/{id}/cancel` | Cancel running search |
| `POST` | `/api/searches/{id}/load-more` | Load more Google Maps results |

### `POST /api/searches` — The Main Entry Point

**Request:**
```json
{
  "niche": "website development",
  "location": "India",
  "source": "linkedin",
  "lead_types": ["buyer", "hiring"],
  "max_results": 10
}
```

**Flow:**
1. Validate request body (`SearchCreateRequest`)
2. Check search limit via `check_search_limit()`
3. Create search row in DB
4. Increment `daily_usage.searches_run`
5. Spawn background task:
   - LinkedIn → `run_linkedin_pipeline_fast()`
   - Google Maps → `run_search_pipeline()`
6. Return search ID immediately

### `GET /api/searches/{id}/status` — Polling Endpoint

Returns lightweight data for the frontend polling loop:
```json
{
  "id": "search-uuid",
  "status": "scraping",
  "progress_percent": 45,
  "message": "AI qualifying 87 leads...",
  "results_found": 23,
  "leads_generated": 12,
  "elapsed_seconds": 34
}
```

### `GET /api/searches/{id}/results` — Progressive Loading

Returns leads in batches of 4 (for live display during search):
```python
leads = supabase.table("leads") \
    .select("*") \
    .eq("search_id", search_id) \
    .order("ai_confidence_score", desc=True) \
    .range(offset, offset + 3)
```

---

## Router: Leads (`/api/leads`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/leads` | Paginated leads with filters |
| `GET` | `/api/leads/export` | CSV export (Pro/Agency only) |
| `GET` | `/api/leads/{id}` | Full lead detail |
| `POST` | `/api/leads/{id}/analyze-website` | On-demand website analysis |
| `PATCH` | `/api/leads/{id}/status` | Update pipeline status |
| `PATCH` | `/api/leads/{id}/notes` | Update user notes |
| `PATCH` | `/api/leads/{id}/favorite` | Toggle favorite |

### `GET /api/leads` — Filtered Query

Query parameters:
```python
search_id: str          # Filter by search
source: str             # "google_maps" or "linkedin"
post_type: str          # "buyer", "hiring", "job_seeker"
lead_category: str      # "hot", "warm"
user_status: str        # "new", "contacted", "replied", "converted", "lost"
is_favorite: bool       # Only favorites
search: str             # Full-text search (name, company, description)
sort_by: str            # "created_at", "ai_confidence_score", etc.
sort_order: str         # "asc", "desc"
page: int               # Page number (1-indexed)
limit: int              # Results per page (default 20)
```

### `GET /api/leads/export` — CSV Export

- Only available for Pro/Agency plans
- Max 10,000 rows
- Returns `StreamingResponse` with CSV content
- Columns: all lead fields

---

## Router: AI (`/api/ai`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/ai/pitch/{lead_id}` | Generate outreach pitch |
| `POST` | `/api/ai/website-message/{lead_id}` | Generate short message |

### `POST /api/ai/pitch/{lead_id}`

**Flow:**
1. Fetch lead from DB
2. Check AI limit (100 calls/day)
3. Call `generate_pitch()` with lead data
4. Save pitch to `leads.ai_pitch` column
5. Increment `daily_usage.ai_calls`

**Request body (optional):**
```json
{
  "tone": "professional",
  "focus": "website redesign"
}
```

**Response:**
```json
{
  "pitch": "Hi John, I noticed your company Acme Corp is looking for...",
  "confidence": 0.85,
  "deal_value_estimate": "$2,500"
}
```

---

## Router: Subscriptions (`/api/subscriptions`)

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/subscriptions/plans` | List all plans |
| `GET` | `/api/subscriptions/current` | Current subscription |
| `POST` | `/api/subscriptions/create-order` | Create Razorpay order |
| `POST` | `/api/subscriptions/verify` | Verify payment |
| `POST` | `/api/subscriptions/webhook` | Razorpay webhook |
| `POST` | `/api/subscriptions/cancel` | Cancel subscription |

### Payment Flow

```
1. Frontend calls POST /create-order
   → Backend creates Razorpay order (USD→INR at 95.75 rate)
   → Returns order_id

2. Frontend opens Razorpay checkout
   → User pays
   → Razorpay returns payment_signature

3. Frontend calls POST /verify
   → Backend verifies HMAC-SHA256 signature
   → Activates subscription in DB
   → Returns success

4. Razorpay sends webhook to POST /webhook
   → Backend verifies webhook signature
   → Handles payment.captured, subscription.charged
   → Resets daily_usage
```

---

## Middleware

### Auth Middleware (`auth_middleware.py`)

```python
async def get_current_user(token: str = Depends(oauth2_scheme)):
    # 1. Check cache (60s TTL)
    # 2. Call supabase.auth.get_user(token)
    # 3. If first auth, auto-create free trial subscription
    # 4. Cache result
    # 5. Return user object
```

**Cache:** `_token_cache` dict with TTL-based expiry, cleanup every 5 minutes.

### Usage Middleware (`usage_middleware.py`)

```python
async def check_search_limit(user_id: str):
    # 1. Resolve effective subscription (team-aware)
    # 2. Check trial expiry
    # 3. Check daily search limit
    # 4. Return 429 with upgrade_url if exceeded
```

---

## Schemas

### `SearchCreateRequest`

```python
class SearchCreateRequest(BaseModel):
    niche: str                    # Required, 2-200 chars
    location: str = ""            # Optional location
    source: str = "linkedin"      # "linkedin" or "google_maps"
    lead_types: list[str] = []    # ["buyer", "hiring"]
    max_results: int = 10         # 1-50
    enrich_emails: bool = False
```

### `LeadListItem`

Compact lead for list views (42 fields):
```python
class LeadListItem(BaseModel):
    id: str
    full_name: str
    company: str
    headline: str
    description: str
    website_url: str | None
    linkedin_url: str | None
    email: str | None
    phone: str | None
    location: str
    source: str                   # "google_maps" or "linkedin"
    post_type: str                # "buyer", "hiring", "job_seeker"
    lead_category: str            # "hot", "warm"
    user_status: str
    ai_confidence_score: float
    ai_pitch: str | None
    estimated_deal_value: float | None
    is_favorite: bool
    created_at: str
    # ... and more
```

### `SearchStatusResponse`

Lightweight polling response:
```python
class SearchStatusResponse(BaseModel):
    id: str
    status: str                   # "queued", "scraping", "analyzing", "completed"
    source: str
    progress_percent: int
    message: str
    results_found: int
    leads_generated: int
    elapsed_seconds: float
```

---

## Error Handling

All routers use consistent error responses:

```python
# 400 Bad Request
raise HTTPException(status_code=400, detail="Invalid request")

# 401 Unauthorized
raise HTTPException(status_code=401, detail="Not authenticated")

# 403 Forbidden
raise HTTPException(status_code=403, detail="Upgrade required")

# 404 Not Found
raise HTTPException(status_code=404, detail="Search not found")

# 429 Too Many Requests
raise HTTPException(status_code=429, detail={
    "error": "Daily search limit reached",
    "upgrade_url": "/pricing"
})
```

---

## Request Flow Diagram

```
Client Request
    ↓
[CORS Middleware] → Check Origin
    ↓
[Auth Middleware] → Verify JWT, cache user
    ↓
[Rate Limiter] → Check daily limits
    ↓
[Router Handler] → Validate request body
    ↓
[Service Layer] → Business logic
    ↓
[Database] → Supabase query
    ↓
Response JSON
```
