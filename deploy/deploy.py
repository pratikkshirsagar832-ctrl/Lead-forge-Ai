"""
LeadForge AI â€” Production Deploy Script
1. Verify Supabase migration has been run (manual step)
2. Build + deploy using docker-compose
3. Configure nginx
4. Health checks
"""

import paramiko
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST = '85.239.237.53'
PASSWORD = 'YOUR_VPS_ROOT_PASSWORD'
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(client, cmd, timeout=120):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    return out.strip(), err.strip()


print("""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘         LeadForge AI â€” Deploy to Production           â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

BEFORE RUNNING THIS SCRIPT:

1. Go to Supabase SQL Editor:
   https://supabase.com/dashboard/project/wtradahkkpbkbhmkkpal/sql/new

2. Run the complete migration from:
   supabase/migration.sql

3. Ensure these env vars are set in GitHub Secrets:
   - SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
""")

confirm = input("Have you run the Supabase migration? (yes/no): ")
if confirm.lower() != 'yes':
    print("Run the migration first, then re-run this script.")
    sys.exit(1)

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
sftp = None

try:
    client.connect(HOST, username='root', password=PASSWORD, timeout=15)
    sftp = client.open_sftp()

    # â”€â”€ STEP 1: Install Docker â”€â”€
    print('\n=== STEP 1: Installing Docker ===')
    run(client, 'apt-get update -qq')
    run(client, 'apt-get install -y -qq ca-certificates curl')
    run(client, 'install -m 0755 -d /etc/apt/keyrings')
    run(client, 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc')
    run(client, 'chmod a+r /etc/apt/keyrings/docker.asc')
    codename, _ = run(client, '. /etc/os-release && echo "$VERSION_CODENAME"')
    print(f'  Codename: {codename}')
    run(client, f'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu {codename} stable" > /etc/apt/sources.list.d/docker.list')
    run(client, 'apt-get update -qq')
    run(client, 'apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin', 120)
    v, _ = run(client, 'docker --version')
    print(f'  {v}')
    vc, _ = run(client, 'docker compose version')
    print(f'  {vc}')

    # â”€â”€ STEP 2: Clone code â”€â”€
    print('\n=== STEP 2: Cloning code ===')
    run(client, 'rm -rf /root/leadforge')
    run(client, 'cd /root && git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai-2.git leadforge')
    out, _ = run(client, 'ls /root/leadforge/')
    print(f'  Files: {out}')

    # â”€â”€ STEP 3: Upload .env â”€â”€
    print('\n=== STEP 3: Creating .env ===')
    env_local = os.path.join(PROJECT_DIR, 'backend', '.env')
    env_lines = []
    with open(env_local, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip()
            if line.startswith('GMAPS_SCRAPER_PATH'):
                line = 'GMAPS_SCRAPER_PATH=/app/google-maps-scraper/google-maps-scraper'
            elif line.startswith('ENVIRONMENT'):
                line = 'ENVIRONMENT=production'
            elif line.startswith('FRONTEND_URL'):
                line = 'FRONTEND_URL=http://85.239.237.53'
            elif line.startswith('SITE_URL'):
                line = 'SITE_URL=http://85.239.237.53'
            env_lines.append(line)
    env_content = '\n'.join(env_lines)

    with sftp.open('/root/leadforge/backend/.env', 'w') as f:
        f.write(env_content)
    print('  backend/.env uploaded')

    # Upload frontend .env.local
    fe_env_local = os.path.join(PROJECT_DIR, 'frontend', '.env.local')
    with open(fe_env_local, 'r', encoding='utf-8') as f:
        fe_env = f.read()
    fe_env = fe_env.replace('http://localhost:8000', 'http://85.239.237.53')
    with sftp.open('/root/leadforge/frontend/.env.local', 'w') as f:
        f.write(fe_env)
    print('  frontend/.env.local uploaded')

    # â”€â”€ STEP 4: Docker build & start â”€â”€
    print('\n=== STEP 4: Building containers ===')
    out, err = run(client, 'cd /root/leadforge && docker compose build 2>&1', 600)
    if 'error' in out.lower() or 'error' in err.lower():
        print(f'  BUILD ERR: {(err or out)[-500:]}')
    else:
        print('  Build OK')

    print('\n  Starting containers...')
    out, err = run(client, 'cd /root/leadforge && docker compose up -d 2>&1', 60)
    print(f'  {out[:500]}')
    if err:
        print(f'  ERR: {err[:300]}')

    out, _ = run(client, 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
    print(f'\n  Containers:\n{out}')

    # â”€â”€ STEP 5: Nginx configuration â”€â”€
    print('\n=== STEP 5: Setting up nginx ===')
    nginx_conf = """upstream backend { server 127.0.0.1:8000; }
upstream frontend { server 127.0.0.1:3000; }

server {
    listen 80;
    server_name hyperclients.ai www.hyperclients.ai 85.239.237.53;
    client_max_body_size 50M;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;
    gzip_min_length 1000;
    gzip_comp_level 6;

    location /api/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }

    location / {
        proxy_pass http://frontend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 90s;

        location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|webp|woff2?|ttf|eot)$ {
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_cache_valid 200 7d;
            add_header Cache-Control "public, immutable";
            expires 7d;
        }
    }

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}"""
    run(client, f'cat > /etc/nginx/sites-available/hyperclients << \'NGINXEOF\'\n{nginx_conf}\nNGINXEOF')
    run(client, 'ln -sf /etc/nginx/sites-available/hyperclients /etc/nginx/sites-enabled/')
    run(client, 'rm -f /etc/nginx/sites-enabled/default')
    out, err = run(client, 'nginx -t 2>&1')
    print(f'  Nginx test: {out}')
    if 'successful' in out:
        run(client, 'systemctl restart nginx')
        print('  Nginx restarted')
    else:
        print(f'  Nginx ERR: {err}')

    # â”€â”€ STEP 6: Health Check â”€â”€
    print('\n=== STEP 6: Health Check ===')
    be, _ = run(client, 'curl -s http://localhost:8000/api/health')
    print(f'  Backend: {be[:200]}')
    fe, _ = run(client, 'curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
    print(f'  Frontend: HTTP {fe}')
    ng, _ = run(client, 'curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
    print(f'  Nginx: HTTP {ng}')

    print("""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘              DEPLOYMENT COMPLETE!                      â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
  URL: http://85.239.237.53
  API: http://85.239.237.53/api/health
  Dashboard: http://85.239.237.53/dashboard
""")

finally:
    if sftp:
        sftp.close()
    client.close()
