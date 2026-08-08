"""Deploy services to server - install deps + start backend/frontend + nginx"""
import paramiko, io, sys, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST = '85.239.237.53'
PASSWORD = 'YOUR_VPS_ROOT_PASSWORD'
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_FILE = os.path.join(PROJECT_DIR, 'supabase', 'migration.sql')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

def run(cmd, timeout=300):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

try:
    client.connect(HOST, username='root', password=PASSWORD, timeout=15)
    code_dir = '/root/leadforge'

    # Check code exists
    out, _ = run(f'ls {code_dir}/backend/app/main.py 2>/dev/null || echo "MISSING"')
    if 'MISSING' in out:
        print('Code not found. Cloning...')
        run(f'cd /root && git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai-2.git leadforge 2>&1', 120)
        run(f'cd {code_dir} && git config core.autocrlf false')
    else:
        print('Code exists, pulling latest...')
        run(f'cd {code_dir} && git pull 2>&1', 60)

    out, _ = run(f'cd {code_dir} && git log --oneline -1')
    print(f'  Commit: {out}')

    # Build scraper if Go available
    print('\n=== Building scraper ===')
    out, _ = run(f'cd {code_dir}/backend/google-maps-scraper && PATH=$PATH:/usr/local/go/bin go build -o google-maps-scraper . 2>&1', 300)
    if 'error' in out.lower():
        print(f'  Scraper build: {out[-200:]}')
    else:
        out2, _ = run(f'ls -lh {code_dir}/backend/google-maps-scraper/google-maps-scraper 2>/dev/null || echo "missing"')
        print(f'  {out2}')

    # Ensure correct .env
    print('\n=== Creating .env ===')
    env = f"""SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
GMAPS_SCRAPER_PATH={code_dir}/backend/google-maps-scraper/google-maps-scraper
FRONTEND_URL=http://85.239.237.53
BACKEND_URL=http://localhost:8000
SITE_URL=http://85.239.237.53
ENVIRONMENT=production
"""
    run(f'cat > {code_dir}/backend/.env << \'ENVEOF\'\n{env}\nENVEOF')
    
    fe_env = """NEXT_PUBLIC_API_URL=http://85.239.237.53
NEXT_PUBLIC_SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_test_T1NPgRdVMMGIk2
"""
    run(f'cat > {code_dir}/frontend/.env.local << \'ENVEOF\'\n{fe_env}\nENVEOF')
    print('  .env files created')

    # Install Python deps
    print('\n=== Installing Python deps ===')
    out, _ = run(f'cd {code_dir} && pip install -r backend/requirements.txt -q 2>&1', 300)
    if out:
        print(f'  pip: {out[-150:]}')
    out, _ = run(f'cd {code_dir} && pip install backend/Scrapling/ -q 2>&1', 120)
    if out:
        print(f'  Scrapling: {out[-100:]}')
    run('python3 -m playwright install chromium --with-deps 2>&1', 120)

    # Install Node deps
    print('\n=== Installing Node deps ===')
    out, _ = run(f'cd {code_dir}/frontend && npm ci 2>&1', 120)
    if 'error' in out.lower():
        run(f'cd {code_dir}/frontend && npm install 2>&1', 120)
    print('  Done')

    # Build frontend
    print('\n=== Building frontend ===')
    out, _ = run(f'cd {code_dir}/frontend && npm run build 2>&1', 300)
    if 'successfully' in out.lower():
        print('  Frontend build OK')
    else:
        print(f'  Build: {out[-200:]}')

    # Kill old processes
    print('\n=== Starting services ===')
    run('pkill -f uvicorn 2>/dev/null || true')
    run('pkill -f "next-server" 2>/dev/null || true')
    time.sleep(2)

    # Start backend (from code_dir working directory)
    run(f'cd {code_dir} && nohup python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 120 > {code_dir}/backend.log 2>&1 &')
    time.sleep(5)
    
    # Try starting with correct path if that failed
    be, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health')
    if be != '200':
        # Try running from backend directory instead
        run('pkill -f uvicorn 2>/dev/null || true')
        time.sleep(1)
        run(f'cd {code_dir}/backend && nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 120 > {code_dir}/backend.log 2>&1 &')
        time.sleep(5)

    be, err = run('curl -s http://localhost:8000/api/health')
    if be:
        print(f'  Backend: HTTP OK - {be[:100]}')
    else:
        print(f'  Backend FAILED')
        out, _ = run(f'tail -30 {code_dir}/backend.log')
        print(f'  Logs: {out[-500:]}')

    # Start frontend
    run(f'cd {code_dir}/frontend && nohup npx next start -p 3000 > {code_dir}/frontend.log 2>&1 &')
    time.sleep(5)
    fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
    print(f'  Frontend: HTTP {fe}')

    # Nginx
    print('\n=== Configuring nginx ===')
    nginx_conf = f"""upstream backend {{ server 127.0.0.1:8000; }}
upstream frontend {{ server 127.0.0.1:3000; }}
server {{
    listen 80;
    server_name hyperclients.ai www.hyperclients.ai 85.239.237.53;
    client_max_body_size 50M;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;
    gzip_min_length 1000; gzip_comp_level 6;
    location /api/ {{
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 120s; proxy_send_timeout 120s;
    }}
    location / {{
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
        location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|webp|woff2?|ttf|eot)$ {{
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_cache_valid 200 7d;
            add_header Cache-Control "public, immutable";
            expires 7d;
        }}
    }}
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}}"""
    run(f'cat > /etc/nginx/sites-available/hyperclients << \'NGXEOF\'\n{nginx_conf}\nNGXEOF')
    run('ln -sf /etc/nginx/sites-available/hyperclients /etc/nginx/sites-enabled/')
    run('rm -f /etc/nginx/sites-enabled/default')
    out, _ = run('nginx -t 2>&1')
    if 'successful' in out:
        run('systemctl restart nginx')
        print('  Nginx OK')
    else:
        print(f'  Nginx: {out}')

    # Final health check
    time.sleep(3)
    print(f'\n{"â•"*50}')
    be, _ = run('curl -s http://localhost:8000/api/health')
    print(f'Backend: {be[:100]}')
    fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
    print(f'Frontend: HTTP {fe}')
    ng, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
    print(f'Nginx:  HTTP {ng}')
    print(f'URL:    http://85.239.237.53')

finally:
    client.close()
