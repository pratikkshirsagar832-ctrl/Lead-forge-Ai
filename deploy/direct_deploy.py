import paramiko, sys, io, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=300):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

print('â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—')
print('â•‘  HYPERCLIENTS DIRECT DEPLOYMENT        â•‘')
print('â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•')

# â”€â”€ 1. Kill old processes & clean â”€â”€
print('\nâ”€â”€ 1. Cleaning old processes â”€â”€')
run("fuser -k 8000/tcp 2>/dev/null || true")
run("fuser -k 3000/tcp 2>/dev/null || true")
run("pkill -f uvicorn 2>/dev/null || true")
run("pkill -f 'next-server' 2>/dev/null || true")
run("pkill -f 'node.*next' 2>/dev/null || true")
time.sleep(2)

# â”€â”€ 2. Remove Docker completely â”€â”€
print('\nâ”€â”€ 2. Removing Docker â”€â”€')
run('docker rm -f $(docker ps -aq) 2>/dev/null')
run('docker system prune -af 2>/dev/null')
run('apt-get remove -y -qq docker docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null')
run('apt-get autoremove -y -qq 2>/dev/null')
run('rm -rf /var/lib/docker /etc/docker 2>/dev/null')
run('rm -f /usr/bin/docker 2>/dev/null')
print('Docker removed')

# â”€â”€ 3. Clean old code â”€â”€
print('\nâ”€â”€ 3. Cleaning old code â”€â”€')
run('rm -rf /root/leadforge')
run('rm -f /etc/nginx/sites-enabled/leadforge 2>/dev/null')
print('Old code cleaned')

# â”€â”€ 4. Clone fresh code â”€â”€
print('\nâ”€â”€ 4. Cloning from GitHub â”€â”€')
out, err = run('cd /root && git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai-2.git leadforge 2>&1', 120)
if 'fatal' in err or 'fatal' in out:
    print(f'CLONE FAILED: {err}')
    client.close()
    exit(1)
run('cd /root/leadforge && git config core.autocrlf false')
out, _ = run('cd /root/leadforge && git log --oneline -1')
print(f'Commit: {out}')

# â”€â”€ 5. Install latest Go and build scraper â”€â”€
print('\nâ”€â”€ 5. Installing Go 1.26+ for scraper â”€â”€')
run('rm -rf /usr/local/go')
out, _ = run('wget -q https://go.dev/dl/go1.27.0.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
if 'error' in out.lower():
    out, _ = run('wget -q https://go.dev/dl/go1.26.0.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
if 'error' in out.lower():
    out, _ = run('wget -q https://go.dev/dl/go1.26.1.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
run('rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tar.gz')
run('rm -f /tmp/go.tar.gz')
out, _ = run('export PATH=$PATH:/usr/local/go/bin && go version')
print(f'Go: {out.split("version")[-1].strip() if out else "FAILED"}')

# Build scraper
print('\n  Building scraper binary...')
out, err = run('cd /root/leadforge/backend/google-maps-scraper && /usr/local/go/bin/go build -o google-maps-scraper . 2>&1', 300)
if err and 'error' in err.lower():
    print(f'SCRAPER BUILD ERROR: {err[-300:]}')
else:
    print(f'Scraper built: {out[-100:]}')
out, _ = run('ls -lh /root/leadforge/backend/google-maps-scraper/google-maps-scraper 2>/dev/null || echo "binary not found"')
print(f'  {out}')

# â”€â”€ 6. Create .env â”€â”€
print('\nâ”€â”€ 6. Creating .env â”€â”€')
env_content = """SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
GMAPS_SCRAPER_PATH=/root/leadforge/backend/google-maps-scraper/google-maps-scraper
FRONTEND_URL=http://85.239.237.53
BACKEND_URL=http://localhost:8000
ENVIRONMENT=production
"""
run(f'cat > /root/leadforge/.env << \'ENVEOF\'\n{env_content}\nENVEOF')
print('.env created')

# â”€â”€ 7. Python deps â”€â”€
print('\nâ”€â”€ 7. Python backend â”€â”€')
out, _ = run('cd /root/leadforge && pip install -r backend/requirements.txt 2>&1', 300)
if 'error' in (out + ' ').lower() and 'not' not in out.lower():
    print(f'PIP issues: {out[-200:]}')
print('Deps installed')
out, _ = run('cd /root/leadforge && pip install backend/Scrapling/ 2>&1', 120)
if 'Successfully' in out: print('Scrapling installed')
out, _ = run('python3 -m playwright install chromium --with-deps 2>&1', 120)
if 'already' in out.lower() or 'done' in out.lower(): print('Playwright chromium ready')

# â”€â”€ 8. Node frontend â”€â”€
print('\nâ”€â”€ 8. Node frontend â”€â”€')
out, _ = run('cd /root/leadforge/frontend && npm ci 2>&1', 120)
if 'error' in out.lower() and 'code' in out.lower():
    print(f'npm ci error: {out[-200:]}')
    # try npm install instead
    out, _ = run('cd /root/leadforge/frontend && npm install 2>&1', 120)
    print('Used npm install instead')
print('Deps installed')

# Create frontend env
run('cat > /root/leadforge/frontend/.env.local << \'ENVEOF\'\nNEXT_PUBLIC_API_URL=http://localhost:8000\nENVEOF')

# Build
out, _ = run('cd /root/leadforge/frontend && npm run build 2>&1', 300)
if 'successfully' in out.lower():
    print('Frontend build OK')
else:
    print(f'Build output (last 200): {out[-200:]}')

# â”€â”€ 9. Start Backend â”€â”€
print('\nâ”€â”€ 9. Starting backend (port 8000) â”€â”€')
run('pkill -f uvicorn 2>/dev/null || true')
time.sleep(1)
run('cd /root/leadforge && nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 120 > /root/leadforge/backend.log 2>&1 &')
time.sleep(4)
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'Backend: {be[:100] if be else "FAILED"}')

# â”€â”€ 10. Start Frontend â”€â”€
print('\nâ”€â”€ 10. Starting frontend (port 3000) â”€â”€')
run('pkill -f "next-server" 2>/dev/null || true')
time.sleep(1)
run('cd /root/leadforge/frontend && nohup npx next start -p 3000 > /root/leadforge/frontend.log 2>&1 &')
time.sleep(5)
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')

# â”€â”€ 11. Nginx â”€â”€
print('\nâ”€â”€ 11. Configuring nginx â”€â”€')
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
run(f'cat > /etc/nginx/sites-available/hyperclients << \'NGINXEOF\'\n{nginx_conf}\nNGINXEOF')
run('ln -sf /etc/nginx/sites-available/hyperclients /etc/nginx/sites-enabled/')
run('rm -f /etc/nginx/sites-enabled/default')
out, _ = run('nginx -t 2>&1')
print(f'Nginx test: {"OK" if "successful" in out else out}')
if 'successful' in out:
    run('systemctl restart nginx')
    print('Nginx restarted')

# â”€â”€ 12. Final checks â”€â”€
print('\nâ”€â”€ 12. Final health checks â”€â”€')
time.sleep(3)
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'Backend: {be[:150]}')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')
ng, _ = run('curl -s http://85.239.237.53/api/health')
print(f'Nginx API: {ng[:150]}')
ng2, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
print(f'Nginx URL: HTTP {ng2}')

# If something failed, check logs
if 'healthy' not in be:
    print('\n>>> Backend logs:')
    out, _ = run('tail -30 /root/leadforge/backend.log')
    print(out)
if fe != '200':
    print('\n>>> Frontend logs:')
    out, _ = run('tail -30 /root/leadforge/frontend.log')
    print(out)

client.close()
print(f'\n{"â•"*50}')
print(f'  âœ… URL: http://85.239.237.53')
print(f'  âœ… API: http://85.239.237.53/api/health')
print(f'  âœ… Dashboard: http://85.239.237.53/dashboard')
print(f'{"â•"*50}')
