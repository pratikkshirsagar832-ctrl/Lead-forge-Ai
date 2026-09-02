# 11 — TROUBLESHOOTING GUIDE

## Common Issues & Solutions

---

## Backend Issues

### 1. Backend Won't Start

**Symptom:** `docker compose logs backend` shows error

**Common Causes:**

```bash
# Check logs
docker compose logs backend --tail 50

# Common error: Missing .env file
Error: Field required: supabase_url

# Solution: Ensure .env exists with all required keys
cp backend/.env.example backend/.env
# Edit .env with your keys
```

**Required Environment Variables:**
```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
OPENAI_API_KEY=sk-...
APIFY_API_KEY=apify_api_...
```

---

### 2. Supabase Connection Error

**Symptom:** `Connection refused` or `Invalid API key`

**Solution:**
```bash
# Test Supabase connection
curl -H "apikey: YOUR_ANON_KEY" https://xxx.supabase.co/rest/v1/leads?limit=1

# Check if URL is correct (no trailing slash)
# Bad:  https://xxx.supabase.co/
# Good: https://xxx.supabase.co
```

---

### 3. OpenAI Rate Limit

**Symptom:** `429 Too Many Requests` from OpenAI

**Solution:**
```python
# The code handles this automatically with retries
# But if persistent, check your OpenAI billing:
# https://platform.openai.com/account/billing

# Or reduce concurrency:
AI_ASYNC_CONCURRENCY = 6  # Default is 12
```

---

### 4. Apify Keys Failing

**Symptom:** All Apify searches return empty results

**Check Key Health:**
```python
from app.services.apify_service import check_apify_keys_health

health = check_apify_keys_health()
print(health)
# {'key_1': 'healthy', 'key_2': 'rate_limited', ...}
```

**Common Issues:**
- Rate limited → Keys auto-cooldown for 600 seconds
- Auth failed → Key permanently blacklisted
- Budget exceeded → Check Apify dashboard

**Solution:**
```bash
# Add more keys in .env
APIFY_API_KEY=apify_api_key1
APIFY_API_KEY_2=apify_api_key2
APIFY_API_KEY_3=apify_api_key3
```

---

### 5. Google Maps Scraper Not Found

**Symptom:** `FileNotFoundError: google-maps-scraper`

**Solution:**
```bash
# Check binary exists
ls -la /app/google-maps-scraper/google-maps-scraper

# Rebuild Docker image
docker compose build --no-cache backend

# Or set path in .env
GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
```

---

### 6. Database Migration Errors

**Symptom:** `relation "leads" does not exist`

**Solution:**
```bash
# Run migration manually
psql -h db.xxx.supabase.co -U postgres -d postgres -f supabase/migration.sql

# Or via Supabase Dashboard:
# Go to SQL Editor → Paste migration.sql → Run
```

---

## Frontend Issues

### 1. Frontend Won't Build

**Symptom:** `npm run build` fails

**Common Causes:**
```bash
# Check Node version (needs 20+)
node --version

# Clear cache
rm -rf node_modules .next
npm install

# Check TypeScript errors
npm run typecheck
```

---

### 2. API Calls Failing

**Symptom:** Network error in browser console

**Check:**
```bash
# 1. Is backend running?
curl http://localhost:8000/api/health

# 2. Is CORS configured?
# In backend/app/config.py:
cors_origins = ["http://localhost:3001"]

# 3. Is NEXT_PUBLIC_API_URL correct?
# In frontend/.env.local:
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

### 3. Authentication Loop

**Symptom:** Redirects to /login repeatedly

**Solution:**
```bash
# Check Supabase keys match
# frontend/.env.local
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...

# backend/.env
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...  # Same as frontend
```

---

### 4. Build Fails with Tailwind

**Symptom:** `Cannot find module 'tailwindcss'`

**Solution:**
```bash
npm install tailwindcss @tailwindcss/postcss
npm run build
```

---

## Docker Issues

### 1. Port Already in Use

**Symptom:** `Bind for 0.0.0.0:8000 failed: port is already allocated`

**Solution:**
```bash
# Find process using port
netstat -ano | findstr :8000

# Kill process
taskkill /PID <pid> /F

# Or change port in docker-compose.yml
ports:
  - "127.0.0.1:8001:8000"  # Changed to 8001
```

---

### 2. Docker Build Slow

**Solution:**
```bash
# Use BuildKit (faster)
DOCKER_BUILDKIT=1 docker compose build

# Or clear cache
docker system prune -a
docker compose build --no-cache
```

---

### 3. Container Keeps Restarting

**Check logs:**
```bash
docker compose logs backend --tail 100

# Common: Missing .env
# Common: Port conflict
# Common: Health check failing
```

---

## AI Issues

### 1. AI Scoring Returns 0

**Symptom:** All leads have score 0

**Check:**
```python
# Test OpenAI directly
import openai
client = openai.OpenAI(api_key="sk-...")
response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

---

### 2. AI Response Parsing Error

**Symptom:** `json.JSONDecodeError`

**The code handles this:**
```python
try:
    result = json.loads(response.choices[0].message.content)
except json.JSONDecodeError:
    # Fallback: extract JSON from text
    result = extract_json_from_text(response.choices[0].message.content)
```

---

### 3. AI Hallucinating Scores

**Symptom:** Scores don't match content

**Solution:** The prompts include strict scoring guides. If persistent:
```python
# Lower temperature for more consistent results
temperature=0.1  # Default is 0.2
```

---

## Performance Issues

### 1. Searches Taking Too Long

**Symptom:** Search takes > 5 minutes

**Check:**
```bash
# Check Apify response times
# Check AI concurrency
# Check network latency

# Reduce search scope
max_results: 5  # Instead of 50
```

---

### 2. High Memory Usage

**Symptom:** Docker container using too much RAM

**Solution:**
```yaml
# In docker-compose.yml
services:
  backend:
    deploy:
      resources:
        limits:
          memory: 2G
```

---

### 3. Database Slow

**Symptom:** Queries timing out

**Check indexes:**
```sql
-- Ensure indexes exist
CREATE INDEX IF NOT EXISTS idx_leads_search_id ON leads(search_id);
CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
```

---

## Deployment Issues

### 1. Deploy Script Fails

**Check SSH access:**
```bash
ssh root@178.16.138.221 "echo 'connected'"
```

**Check Docker:**
```bash
ssh root@178.16.138.221 "docker compose ps"
```

---

### 2. Server Out of Disk Space

**Check:**
```bash
ssh root@178.16.138.221 "df -h"

# Clean Docker
ssh root@178.16.138.221 "docker system prune -a"
```

---

### 3. Container Won't Start After Deploy

**Check logs:**
```bash
ssh root@178.16.138.221 "cd /root/leadforge && docker compose logs backend --tail 50"
```

**Common:**
- Missing .env on server
- Port conflict
- Image build failed

---

## Quick Reference

### Useful Commands

```bash
# Backend
docker compose logs backend --tail 50
docker compose restart backend
docker compose down && docker compose up -d --build

# Frontend
docker compose logs frontend --tail 50
docker compose restart frontend

# Database (via Supabase)
# Go to Dashboard → SQL Editor

# Test API
curl http://localhost:8000/api/health

# Check Apify health
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/apify/health
```

### Log Locations

```bash
# Docker logs
docker compose logs backend > backend.log 2>&1
docker compose logs frontend > frontend.log 2>&1

# Application logs (in container)
docker exec leadforge-backend-1 cat /app/app.log
```

### Reset Everything

```bash
# Stop all containers
docker compose down

# Remove volumes
docker compose down -v

# Remove images
docker compose down --rmi all

# Rebuild fresh
docker compose up -d --build
```
