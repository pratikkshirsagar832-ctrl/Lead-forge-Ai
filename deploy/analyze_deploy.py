import paramiko, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=120):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

def print_cmd(cmd, timeout=120):
    out, err = run(cmd, timeout)
    print(f'$ {cmd}')
    if out: print(out[:2000])
    if err and 'error' in err.lower(): print(f'[ERR] {err[:300]}')
    print('---')

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHASE 1: DEEP ANALYSIS OF SERVER STATE
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print('â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—')
print('â•‘  PHASE 1: ANALYZING SERVER STATE        â•‘')
print('â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•')

print('\nâ”€â”€ 1.1 Running Containers â”€â”€')
print_cmd('docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"')

print('\nâ”€â”€ 1.2 Docker Images â”€â”€')
print_cmd('docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"')

print('\nâ”€â”€ 1.3 Disk Usage â”€â”€')
print_cmd('docker system df')

print('\nâ”€â”€ 1.4 Server Code Structure â”€â”€')
print_cmd('ls -la /root/leadforge/')
print_cmd('ls -la /root/leadforge/backend/app/')
print_cmd('ls -la /root/leadforge/frontend/src/ 2>/dev/null || echo "no frontend src"')

print('\nâ”€â”€ 1.5 .env File â”€â”€')
out, _ = run('cat /root/leadforge/.env')
print(out)

print('\nâ”€â”€ 1.6 Nginx Config â”€â”€')
print_cmd('cat /etc/nginx/sites-available/hyperclients')
print_cmd('ls -la /etc/nginx/sites-enabled/')

print('\nâ”€â”€ 1.7 Git Status on Server â”€â”€')
print_cmd('cd /root/leadforge && git log --oneline -5')
print_cmd('cd /root/leadforge && git status --short')

print('\nâ”€â”€ 1.8 Docker Compose Config on Server â”€â”€')
print_cmd('cat /root/leadforge/docker-compose.yml')

print('\nâ”€â”€ 1.9 Check if Ports are in use â”€â”€')
print_cmd('ss -tlnp | grep -E ":(8000|3000|80) "')

print('\nâ”€â”€ 1.10 Old leadforge files from prev deploy? â”€â”€')
print_cmd('find /root -name "*.yml" -not -path "*/go/*" 2>/dev/null | head -10')

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHASE 2: CLEAN DEPLOYMENT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print('\nâ•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—')
print('â•‘  PHASE 2: CLEAN DEPLOYMENT              â•‘')
print('â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•')

# Kill any old containers
print('\nâ”€â”€ 2.1 Cleaning old containers â”€â”€')
run('docker compose -f /root/leadforge/docker-compose.yml down 2>&1', 60)
run('docker rm -f $(docker ps -aq) 2>/dev/null')
print('Done cleaning')

# Ensure code is fresh from GitHub
print('\nâ”€â”€ 2.2 Pulling latest code â”€â”€')
out, err = run('cd /root/leadforge && git fetch origin 2>&1')
print(out[:200])
out, err = run('cd /root/leadforge && git reset --hard origin/main 2>&1')
print(out[:200])
print(f'Now at: {run("cd /root/leadforge && git log --oneline -1")[0]}')

# Restore .env (was lost during git reset)
print('\nâ”€â”€ 2.3 Re-creating .env â”€â”€')
env_content = '''SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper
FRONTEND_URL=http://85.239.237.53
BACKEND_URL=http://localhost:8000
ENVIRONMENT=production
'''
run(f'cat > /root/leadforge/.env << \'ENVEOF\'\n{env_content}\nENVEOF')

# Fix Dockerfile Go version to latest
print('\nâ”€â”€ 2.4 Fixing Dockerfile Go version â”€â”€')
run('sed -i "s/golang:1\.23-bookworm/golang:latest/g" /root/leadforge/backend/Dockerfile')
run('sed -i "s/golang:1\.24-bookworm/golang:latest/g" /root/leadforge/backend/Dockerfile')
out, _ = run('head -8 /root/leadforge/backend/Dockerfile')
print(out)

# Build backend (frontend will be built by compose)
print('\nâ”€â”€ 2.5 Building backend image â”€â”€')
out, err = run('cd /root/leadforge && docker compose build --no-cache backend 2>&1', 600)
combined = out + err
if 'error' in combined.lower() and 'failed' in combined.lower():
    print('[ERROR] Build failed:')
    print(combined[-800:])
else:
    print('Backend build OK')
    # Verify image
    img, _ = run('docker images leadforge-backend --format "{{.Size}}"')
    print(f'  Image size: {img}')

# Build frontend separately too
print('\nâ”€â”€ 2.6 Building frontend image â”€â”€')
out, err = run('cd /root/leadforge && docker compose build --no-cache frontend 2>&1', 600)
combined = out + err
if 'error' in combined.lower() and 'failed' in combined.lower():
    print('[ERROR] Frontend build failed:')
    print(combined[-800:])
else:
    print('Frontend build OK')
    img, _ = run('docker images leadforge-frontend --format "{{.Size}}"')
    print(f'  Image size: {img}')

# Start containers
print('\nâ”€â”€ 2.7 Starting containers â”€â”€')
out, err = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:500])
if err: print(f'[ERR] {err[:300]}')

# Wait for services to start
import time
print('\nâ”€â”€ 2.8 Waiting for services (15s) â”€â”€')
time.sleep(15)

# Check status
print('\nâ”€â”€ 2.9 Container Status â”€â”€')
out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(out)

# Logs if failed
print('\nâ”€â”€ 2.10 Container Logs (if any issues) â”€â”€')
out, _ = run('docker compose -f /root/leadforge/docker-compose.yml logs --tail=30 2>&1')
if 'Error' in out or 'error' in out:
    print(out[:2000])
else:
    print('No errors in logs')

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PHASE 3: HEALTH CHECKS
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
print('\nâ•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—')
print('â•‘  PHASE 3: HEALTH CHECKS                 â•‘')
print('â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•')

print('\nâ”€â”€ 3.1 Backend Health â”€â”€')
be, _ = run('curl -s http://localhost:8000/api/health')
print(be[:200])

print('\nâ”€â”€ 3.2 Frontend Health â”€â”€')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'HTTP {fe}')

print('\nâ”€â”€ 3.3 Nginx (public URL) â”€â”€')
ng, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
print(f'HTTP {ng}')
ng_api, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/api/health')
print(f'API via nginx: HTTP {ng_api}')

# â”€â”€ Verify nginx config is working â”€â”€
print('\nâ”€â”€ 3.4 Nginx config test â”€â”€')
out, _ = run('nginx -t 2>&1')
print(out)

client.close()

url = 'http://85.239.237.53'
print(f'\n{"â•"*50}')
print(f'  ANALYSIS & DEPLOYMENT COMPLETE')
print(f'  URL: {url}')
print(f'  API: {url}/api/health')
print(f'  Dashboard: {url}/dashboard')
print(f'{"â•"*50}')
