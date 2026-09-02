# 12 — DEPLOYMENT GUIDE

## Complete Deployment Instructions

---

## Prerequisites

- Docker & Docker Compose installed
- SSH access to production server
- All API keys configured
- Domain name (optional)

---

## 1. Local Development Setup

### Clone Repository
```bash
git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai.git
cd Lead-Forge-Ai
```

### Environment Files

**Backend `.env`:**
```bash
# Supabase
SUPABASE_URL=https://gzxmgdkpsdqkxrnpplyh.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# OpenAI
OPENAI_API_KEY=sk-...

# Apify (add all keys you have)
APIFY_API_KEY=apify_api_...
APIFY_API_KEY_2=apify_api_...

# Razorpay
RAZORPAY_KEY_ID=rzp_...
RAZORPAY_KEY_SECRET=...

# URLs
FRONTEND_URL=http://localhost:3001
BACKEND_URL=http://localhost:8000
SITE_URL=http://localhost:3001

# Environment
ENVIRONMENT=development
```

**Frontend `.env.local`:**
```bash
NEXT_PUBLIC_SUPABASE_URL=https://gzxmgdkpsdqkxrnpplyh.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=http://localhost:8000
ADMIN_PASSWORD=@PatilHyperclients@1234
```

### Start Local
```bash
docker compose up -d --build

# Access:
# Frontend: http://localhost:3001
# Backend:  http://localhost:8000
# API Docs: http://localhost:8000/docs (dev only)
```

---

## 2. Production Server Setup

### Server Requirements
- **OS:** Ubuntu 22.04 LTS
- **RAM:** 4GB minimum (8GB recommended)
- **Storage:** 40GB minimum
- **Docker:** 24.0+

### Initial Server Setup
```bash
# SSH into server
ssh root@178.16.138.221

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt install docker-compose-plugin -y

# Create project directory
mkdir -p /root/leadforge
cd /root/leadforge
```

---

## 3. Deploy to Production

### Method 1: Git Pull (Recommended)

```bash
# SSH into server
ssh root@178.16.138.221

cd /root/leadforge

# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build
```

### Method 2: SCP Upload

```bash
# From local machine
scp -r backend/ root@178.16.138.221:/root/leadforge/backend/
scp -r frontend/ root@178.16.138.221:/root/leadforge/frontend/
scp docker-compose.yml root@178.16.138.221:/root/leadforge/

# SSH and rebuild
ssh root@178.16.138.221 "cd /root/leadforge && docker compose up -d --build"
```

### Method 3: Paramiko (Python Script)

```python
import paramiko

# Connect
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('178.16.138.221', username='root', password='YOUR_PASSWORD')

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
c.close()
```

---

## 4. Environment Variables on Server

```bash
# SSH into server
ssh root@178.16.138.221

# Check .env files exist
ls -la /root/leadforge/backend/.env
ls -la /root/leadforge/frontend/.env.local

# Edit if needed
nano /root/leadforge/backend/.env
nano /root/leadforge/frontend/.env.local
```

---

## 5. Database Setup

### Run Migration

**Option A: Supabase Dashboard**
1. Go to https://supabase.com/dashboard
2. Select your project
3. Go to SQL Editor
4. Paste contents of `supabase/migration.sql`
5. Click "Run"

**Option B: psql**
```bash
psql -h db.gzxmgdkpsdqkxrnpplyh.supabase.co \
     -U postgres \
     -d postgres \
     -f supabase/migration.sql
```

---

## 6. Verify Deployment

### Health Check
```bash
# From server
curl http://localhost:8000/api/health

# From external
curl https://hyperclients.online/api/health
```

### Check Containers
```bash
docker compose ps

# Should show:
# leadforge-backend-1    running
# leadforge-frontend-1   running
```

### Check Logs
```bash
docker compose logs backend --tail 20
docker compose logs frontend --tail 20
```

---

## 7. SSL/HTTPS Setup

### Using Nginx Reverse Proxy

```nginx
# /etc/nginx/sites-available/hyperclients

server {
    listen 443 ssl http2;
    server_name hyperclients.online;

    ssl_certificate /etc/letsencrypt/live/hyperclients.online/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/hyperclients.online/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name hyperclients.online;
    return 301 https://$server_name$request_uri;
}
```

### Install SSL Certificate
```bash
apt install certbot python3-certbot-nginx -y
certbot --nginx -d hyperclients.online
```

---

## 8. Monitoring

### Check Docker Stats
```bash
docker stats

# Output:
# CONTAINER       CPU %   MEM USAGE / LIMIT
# leadforge-backend-1   5.2%    256MiB / 2GiB
# leadforge-frontend-1  1.8%    128MiB / 1GiB
```

### Check Disk Usage
```bash
df -h

# Clean Docker cache
docker system prune -a
```

### Check Logs
```bash
# Real-time logs
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail 100 backend
```

---

## 9. Rollback

### If Something Breaks

```bash
# Stop current containers
docker compose down

# Checkout previous version
git checkout HEAD~1

# Rebuild
docker compose up -d --build

# Or restore from backup
git checkout <commit-hash>
docker compose up -d --build
```

---

## 10. Backup

### Database Backup
```bash
# Via Supabase Dashboard
# Go to Settings → Database → Backups

# Or via pg_dump
pg_dump -h db.xxx.supabase.co -U postgres -d postgres > backup.sql
```

### Code Backup
```bash
# Push to GitHub
git add .
git commit -m "backup: description"
git push origin main
```

---

## Quick Deploy Script

Create `deploy.sh`:
```bash
#!/bin/bash
echo "Deploying Lead Forge AI..."

# Build and restart
docker compose up -d --build

# Check status
docker compose ps

echo "Deployed successfully!"
echo "Frontend: http://localhost:3001"
echo "Backend: http://localhost:8000"
```

Make executable:
```bash
chmod +x deploy.sh
./deploy.sh
```
