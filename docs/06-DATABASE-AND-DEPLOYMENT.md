# 06 — DATABASE & DEPLOYMENT

## Database Schema

### Tables

#### 1. `plans` — Subscription Plans

```sql
CREATE TABLE plans (
    id TEXT PRIMARY KEY,           -- "trial", "starter", "pro", "agency"
    name TEXT NOT NULL,
    description TEXT,
    leads_per_day INTEGER DEFAULT 10,
    searches_per_day INTEGER DEFAULT 3,
    price_monthly INTEGER DEFAULT 0,  -- USD cents
    trial_days INTEGER DEFAULT 7,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Seed Data:**
```sql
INSERT INTO plans (id, name, leads_per_day, searches_per_day, price_monthly, trial_days) VALUES
('trial', 'Free Trial', 10, 3, 0, 7),
('starter', 'Starter', 25, 5, 2900, 0),
('pro', 'Professional', 100, 20, 7900, 0),
('agency', 'Agency', 500, 100, 19900, 0);
```

---

#### 2. `user_subscriptions` — User Subscriptions

```sql
CREATE TABLE user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan_id TEXT NOT NULL REFERENCES plans(id),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'cancelled', 'expired', 'past_due')),
    
    -- Trial dates
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    
    -- Subscription dates
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    
    -- Razorpay
    razorpay_order_id TEXT,
    razorpay_subscription_id TEXT,
    razorpay_customer_id TEXT,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id)
);
```

**Team System:**
```sql
-- Team members have razorpay_order_id = "team:{owner_uuid}:{username}"
-- Their effective plan is resolved LIVE from owner's subscription
```

---

#### 3. `daily_usage` — Daily Usage Tracking

```sql
CREATE TABLE daily_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    leads_generated INTEGER DEFAULT 0,
    searches_run INTEGER DEFAULT 0,
    ai_calls INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, date)
);
```

**Auto-increment trigger:**
```sql
-- When a lead is inserted, increment leads_generated
CREATE TRIGGER on_lead_insert
    AFTER INSERT ON leads
    FOR EACH ROW
    EXECUTE FUNCTION handle_lead_insert();
```

---

#### 4. `searches` — Search History

```sql
CREATE TABLE searches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Search parameters
    niche TEXT NOT NULL,
    location TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'linkedin'
        CHECK (source IN ('google_maps', 'linkedin')),
    lead_types TEXT[] DEFAULT '{}',
    
    -- Status
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'scraping', 'analyzing', 'completed', 'failed', 'cancelled')),
    progress_percent INTEGER DEFAULT 0,
    message TEXT DEFAULT '',
    
    -- Results
    results_found INTEGER DEFAULT 0,
    leads_generated INTEGER DEFAULT 0,
    hot_leads INTEGER DEFAULT 0,
    warm_leads INTEGER DEFAULT 0,
    
    -- Metadata
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    elapsed_seconds FLOAT DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

#### 5. `leads` — Lead Data (Core Table)

```sql
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_id UUID NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    
    -- Contact info
    full_name TEXT DEFAULT '',
    company TEXT DEFAULT '',
    headline TEXT DEFAULT '',
    description TEXT DEFAULT '',
    
    -- URLs
    website_url TEXT,
    linkedin_url TEXT,
    post_url TEXT,
    
    -- Contact details
    email TEXT,
    phone TEXT,
    address TEXT,
    
    -- Location
    location TEXT DEFAULT '',
    country_code TEXT DEFAULT '',
    
    -- Post data
    post_text TEXT DEFAULT '',
    post_type TEXT DEFAULT 'buyer'
        CHECK (post_type IN ('buyer', 'hiring', 'job_seeker')),
    
    -- AI scoring
    ai_confidence_score FLOAT DEFAULT 0,
    lead_type TEXT DEFAULT '',
    category TEXT DEFAULT 'warm'
        CHECK (category IN ('hot', 'warm')),
    ai_pitch TEXT,
    
    -- Website analysis
    website_score FLOAT,
    website_issues TEXT[],
    estimated_deal_value FLOAT,
    
    -- User management
    user_status TEXT DEFAULT 'new'
        CHECK (user_status IN ('new', 'contacted', 'replied', 'converted', 'lost')),
    user_notes TEXT DEFAULT '',
    is_favorite BOOLEAN DEFAULT FALSE,
    
    -- Source
    source TEXT DEFAULT 'linkedin'
        CHECK (source IN ('google_maps', 'linkedin')),
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes:**
```sql
CREATE INDEX idx_leads_search_id ON leads(search_id);
CREATE INDEX idx_leads_user_id ON leads(user_id);
CREATE INDEX idx_leads_user_status ON leads(user_status);
CREATE INDEX idx_leads_category ON leads(category);
CREATE INDEX idx_leads_post_type ON leads(post_type);
CREATE INDEX idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX idx_leads_ai_score ON leads(ai_confidence_score DESC);
```

---

#### 6. `website_analyses` — Website Analysis Results

```sql
CREATE TABLE website_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    
    -- Scores
    overall_score FLOAT,
    category TEXT,
    
    -- Issues
    issues JSONB DEFAULT '[]',
    
    -- Contact info found
    emails_found TEXT[] DEFAULT '{}',
    phones_found TEXT[] DEFAULT '{}',
    
    -- Raw data
    raw_analysis JSONB,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

### Row Level Security (RLS)

All tables have RLS enabled:

```sql
-- Enable RLS
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_usage ENABLE ROW LEVEL SECURITY;

-- Policies
CREATE POLICY "Users can view own data" ON leads
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Users can insert own data" ON leads
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can update own data" ON leads
    FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "Users can delete own data" ON leads
    FOR DELETE USING (user_id = auth.uid());
```

---

### Stored Procedures (RPC)

```sql
-- Get remaining searches for today
CREATE OR REPLACE FUNCTION get_remaining_searches(p_user_id UUID)
RETURNS INTEGER AS $$
DECLARE
    v_plan searches_per_day%TYPE;
    v_used INTEGER;
BEGIN
    -- Get plan limit
    SELECT p.searches_per_day INTO v_plan
    FROM user_subscriptions us
    JOIN plans p ON p.id = us.plan_id
    WHERE us.user_id = p_user_id
    AND us.status = 'active';
    
    -- Get usage today
    SELECT COALESCE(searches_run, 0) INTO v_used
    FROM daily_usage
    WHERE user_id = p_user_id
    AND date = CURRENT_DATE;
    
    RETURN GREATEST(0, v_plan - v_used);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Get remaining leads for today
CREATE OR REPLACE FUNCTION get_remaining_leads(p_user_id UUID)
RETURNS INTEGER AS $$
DECLARE
    v_plan leads_per_day%TYPE;
    v_used INTEGER;
BEGIN
    SELECT p.leads_per_day INTO v_plan
    FROM user_subscriptions us
    JOIN plans p ON p.id = us.plan_id
    WHERE us.user_id = p_user_id
    AND us.status = 'active';
    
    SELECT COALESCE(leads_generated, 0) INTO v_used
    FROM daily_usage
    WHERE user_id = p_user_id
    AND date = CURRENT_DATE;
    
    RETURN GREATEST(0, v_plan - v_used);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Auto-create free trial on signup
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO user_subscriptions (user_id, plan_id, status, trial_start, trial_end)
    VALUES (NEW.id, 'trial', 'active', NOW(), NOW() + INTERVAL '7 days');
    
    INSERT INTO daily_usage (user_id, date)
    VALUES (NEW.id, CURRENT_DATE);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION handle_new_user();
```

---

## Deployment

### Server

- **Host:** Contabo VPS
- **IP:** `178.16.138.221`
- **OS:** Ubuntu 22.04
- **Docker:** 24.0.7

### Docker Compose

```yaml
version: "3.8"

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "127.0.0.1:8000:8000"
    env_file:
      - ./backend/.env
    volumes:
      - ./backend/sessions:/app/sessions
    environment:
      - ENVIRONMENT=production
      - GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
    networks:
      - leadforge

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "127.0.0.1:3001:3000"
    env_file:
      - ./frontend/.env.local
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - ADMIN_PASSWORD=@PatilHyperclients@1234
    volumes:
      - ./frontend/data:/app/data
    depends_on:
      - backend
    restart: unless-stopped
    networks:
      - leadforge

networks:
  leadforge:
    driver: bridge
```

### Backend Dockerfile (Multi-Stage)

```dockerfile
# Stage 1: Build Go binary
FROM golang:1.26-bookworm AS go-builder
WORKDIR /src
COPY google-maps-scraper/ .
RUN go build -o /google-maps-scraper ./cmd/scraper

# Stage 2: Python runtime
FROM python:3.12-slim-bookworm

# System dependencies for Scrapling/Playwright
RUN apt-get update && apt-get install -y \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libatspi2.0-0 libgtk-3-0 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Patchright (headless Chromium)
RUN patchright install chromium

# Copy Go binary
COPY --from=go-builder /google-maps-scraper /app/google-maps-scraper/google-maps-scraper

# Install Playwright driver
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m patchright.driver install

# Copy application code
COPY app/ /app/app/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-keep-alive", "120"]
```

### Frontend Dockerfile (Multi-Stage)

```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile
COPY . .
RUN npm run build

# Stage 2: Production
FROM node:20-alpine AS runner
WORKDIR /app
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy build output
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Install sharp for image optimization
RUN npm install sharp

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV NODE_ENV=production

CMD ["node", "server.js"]
```

---

### Deploy Script

```bash
#!/bin/bash
# deploy-contabo.sh

SERVER="root@178.16.138.221"
REMOTE_PATH="/root/leadforge"

# Upload files via SSH/SCP
scp -r backend/ $SERVER:$REMOTE_PATH/backend/
scp -r frontend/ $SERVER:$REMOTE_PATH/frontend/
scp docker-compose.yml $SERVER:$REMOTE_PATH/

# Rebuild and restart
ssh $SERVER "cd $REMOTE_PATH && docker compose up -d --build"

echo "Deployed successfully!"
```

### Manual Deploy via Paramiko

```python
import paramiko

# Connect
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('178.16.138.221', username='root', password='...')

# Upload files
sftp = c.open_sftp()
sftp.put('backend/app/services/linkedin_pipeline.py', 
         '/root/leadforge/backend/app/services/linkedin_pipeline.py')
sftp.close()

# Rebuild
stdin, stdout, stderr = c.exec_command(
    'cd /root/leadforge && docker compose up -d --build',
    timeout=300
)
print(stdout.read().decode())
```

---

## Monitoring

### Health Check

```bash
# Backend health
curl http://localhost:8000/api/health

# Response
{
    "status": "healthy",
    "environment": "production",
    "timestamp": "2025-01-15T10:30:00Z"
}
```

### Docker Logs

```bash
# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Check container status
docker compose ps
```

### Key Metrics

| Metric | Command |
|--------|---------|
| Container status | `docker compose ps` |
| Backend logs | `docker compose logs backend --tail 100` |
| Frontend logs | `docker compose logs frontend --tail 100` |
| Disk usage | `df -h` |
| Memory usage | `free -h` |
| Docker images | `docker images` |
| Container stats | `docker stats` |

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Backend won't start | Check `.env` file, verify all keys are set |
| Frontend can't reach API | Check `NEXT_PUBLIC_API_URL`, verify network |
| Apify keys failing | Check key health: `check_apify_keys_health()` |
| AI scoring failing | Verify `OPENAI_API_KEY`, check rate limits |
| Database errors | Check Supabase connection, verify RLS policies |
| Docker build fails | Clear cache: `docker compose build --no-cache` |

### Useful Commands

```bash
# Enter container
docker exec -it leadforge-backend-1 bash

# Check Python version
docker exec leadforge-backend-1 python --version

# Test API
curl -X POST http://localhost:8000/api/searches \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"niche": "web design", "source": "linkedin", "max_results": 5}'

# Check database
docker exec leadforge-postgres-1 psql -U postgres -c "SELECT COUNT(*) FROM leads;"
```

---

## Security Notes

1. **Never commit `.env` files** — they contain API keys
2. **RLS is enabled** — users can only access their own data
3. **JWT verification** — all endpoints require valid tokens
4. **Rate limiting** — search limits enforced per user
5. **API key rotation** — Apify keys rotate on failure
6. **HTTPS** — production uses TLS (via reverse proxy)
7. **CORS** — only frontend URL allowed in production
