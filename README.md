# LeadForge AI

> Lead discovery and qualification SaaS for freelancers, agencies, and SEO consultants.

Discovers local businesses from Google Maps, checks their websites, and generates outreach-ready sales pitches using AI.

## Architecture

| Component | Technology | Hosting |
|-----------|-----------|---------|
| Backend | FastAPI + Uvicorn | Google Compute Engine VM (Docker) |
| Frontend | Next.js 14 + React | Vercel |
| Database | PostgreSQL | Supabase |
| Auth | Supabase Auth | Supabase |
| AI | DeepSeek API | — |
| Scraper | google-maps-scraper (Go) | Bundled in backend |
| Analysis | Scrapling | Bundled in backend |

---

## Local Development

### Prerequisites
- Python 3.12+
- Node.js 18+
- Go 1.23+ (only if building google-maps-scraper from source)

### Backend

```bash
cd backend

# Create virtualenv
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux:   source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install ./Scrapling

# Copy env file and fill in values
cp .env.example .env

# Run dev server
uvicorn app.main:app --reload --port 8000
```

Or use the PowerShell script (Windows):
```powershell
cd backend
.\scripts\run-api.ps1
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Copy env file
cp .env.local.example .env.local

# Run dev server
npm run dev
```

Visit `http://localhost:3000`

---

## Production Deployment

### 1. Backend — Google Compute Engine VM

#### Option A: Docker (Recommended)

```bash
# SSH into your GCE VM
cd /opt/leadforge

# Clone the repo
git clone <your-repo-url> .

# Create production .env
cp backend/.env.example backend/.env
nano backend/.env   # Fill in production values
```

Set these values in `backend/.env`:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
DEEPSEEK_API_KEY=your-deepseek-key
GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
FRONTEND_URL=https://your-app.vercel.app
BACKEND_URL=https://your-backend-domain.com
ENVIRONMENT=production
```

```bash
# Build Docker image
cd backend
docker build -t leadforge-backend .

# Run container
docker run -d \
  --name leadforge-backend \
  --env-file .env \
  -p 8000:8000 \
  --restart unless-stopped \
  leadforge-backend
```

#### Option B: Direct on VM (without Docker)

```bash
# Install Python 3.12, Go 1.23
sudo apt update && sudo apt install -y python3.12 python3.12-venv golang-go

cd /opt/leadforge/backend

# Setup Python
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install ./Scrapling

# Build google-maps-scraper
chmod +x scripts/build-gmaps.sh
./scripts/build-gmaps.sh

# Create .env
cp .env.example .env && nano .env

# Run
chmod +x scripts/run-api.sh
./scripts/run-api.sh
```

#### Systemd Service (for Option B)

```bash
# Copy service file
sudo cp backend/scripts/systemd/leadforge-backend.service /etc/systemd/system/

# Create a dedicated user
sudo useradd -r -s /bin/false leadforge

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable leadforge-backend
sudo systemctl start leadforge-backend

# Check logs
sudo journalctl -u leadforge-backend -f
```

#### Firewall

Open port 8000 (or use a reverse proxy like Nginx on port 80/443):

```bash
# GCE firewall rule (via gcloud)
gcloud compute firewall-rules create allow-leadforge \
  --allow=tcp:8000 \
  --target-tags=leadforge \
  --description="Allow LeadForge backend"
```

---

### 2. Frontend — Vercel

1. **Import the repo** into Vercel
2. Set **Root Directory** to `frontend`
3. Set **Framework Preset** to `Next.js`
4. Set **Environment Variables** in Vercel dashboard:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `http://YOUR_VM_IP:8000` or `https://your-backend-domain.com` |
| `NEXT_PUBLIC_SUPABASE_URL` | `https://your-project.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Your Supabase anon key |

5. **Deploy**

---

### 3. Supabase Configuration

#### Auth Redirect URLs

In Supabase Dashboard → **Authentication** → **URL Configuration**:

| Setting | Value |
|---------|-------|
| Site URL | `https://your-app.vercel.app` |
| Redirect URLs | `https://your-app.vercel.app/**` |
| | `http://localhost:3000/**` (for local dev) |

This allows Supabase Auth to redirect back to your app after login/signup.

#### Keys

| Key | Used by |
|-----|---------|
| `anon` key | Frontend only (public, safe to expose) |
| `service_role` key | Backend only (secret, never expose to frontend) |

---

### 4. Post-Deploy Checklist

- [ ] Backend health check: `curl https://your-backend/api/health`
- [ ] Frontend loads and shows login page
- [ ] Sign up / login works via Supabase Auth
- [ ] Create a search — results populate
- [ ] Lead cards show real business data
- [ ] AI pitch generation works
- [ ] CSV export works
- [ ] Swagger docs are disabled (`/docs` returns 404)

---

## Environment Variables Summary

### Backend (`backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_ANON_KEY` | ✅ | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Supabase service role key (secret) |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API key for AI pitches |
| `GMAPS_SCRAPER_PATH` | ✅ | Path to google-maps-scraper binary |
| `FRONTEND_URL` | ✅ | Frontend URL (for CORS) |
| `BACKEND_URL` | ✅ | Backend public URL |
| `ENVIRONMENT` | ✅ | `development` or `production` |

### Frontend (`frontend/.env.local` or Vercel dashboard)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | ✅ | Backend API URL |
| `NEXT_PUBLIC_SUPABASE_URL` | ✅ | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | ✅ | Supabase anonymous key |

---

## Project Structure

```
Lead-Forge-Ai/
├── backend/
│   ├── app/                    # FastAPI application
│   │   ├── main.py             # App entry point
│   │   ├── config.py           # Settings (env-driven)
│   │   ├── database.py         # Supabase client
│   │   ├── routers/            # API routes
│   │   ├── services/           # Business logic
│   │   ├── schemas/            # Pydantic models
│   │   └── middleware/         # Auth middleware
│   ├── google-maps-scraper/    # Go scraper (submodule)
│   ├── Scrapling/              # Website analysis lib
│   ├── scripts/                # Startup & build scripts
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/                # Next.js pages
│   │   ├── components/         # React components
│   │   ├── hooks/              # Custom hooks
│   │   ├── lib/                # Utils, API, store
│   │   └── providers/          # Auth provider
│   ├── next.config.js
│   ├── package.json
│   └── .env.local.example
├── prd.MD                      # Product requirements
└── README.md                   # This file
```
