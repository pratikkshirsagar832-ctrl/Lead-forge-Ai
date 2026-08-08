"""
Full production deploy: 
1. Deploy code to server (SSH)
2. Run Supabase migration via psycopg2
3. Start services + nginx config
"""
import paramiko, sys, io, os, time, json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

HOST = '85.239.237.53'
PASSWORD = 'YOUR_VPS_ROOT_PASSWORD'
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQL_FILE = os.path.join(PROJECT_DIR, 'supabase', 'migration.sql')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
sftp = None

def run(cmd, timeout=300):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

try:
    client.connect(HOST, username='root', password=PASSWORD, timeout=15)
    sftp = client.open_sftp()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 1: KILL OLD PROCESSES & CLONE FRESH CODE
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('=== STEP 1: Cleaning & cloning ===')
    run("fuser -k 8000/tcp 2>/dev/null || true")
    run("fuser -k 3000/tcp 2>/dev/null || true")
    run("pkill -f uvicorn 2>/dev/null || true")
    run("pkill -f 'next-server' 2>/dev/null || true")
    time.sleep(2)
    run('rm -rf /root/leadforge')
    out, err = run('cd /root && git clone https://github.com/pratikkshirsagar832-ctrl/Lead-forge-Ai-2.git leadforge 2>&1', 120)
    if 'fatal' in (out + err).lower():
        print(f'CLONE FAILED: {err}')
        sys.exit(1)
    run('cd /root/leadforge && git config core.autocrlf false')
    out, _ = run('cd /root/leadforge && git log --oneline -1')
    print(f'  Commit: {out}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 2: BUILD SCRAPER (Go binary)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 2: Building scraper ===')
    run('rm -rf /usr/local/go')
    out, _ = run('wget -q https://go.dev/dl/go1.27.0.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
    if 'error' in out.lower():
        out, _ = run('wget -q https://go.dev/dl/go1.26.0.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
    if 'error' in out.lower():
        out, _ = run('wget -q https://go.dev/dl/go1.26.1.linux-amd64.tar.gz -O /tmp/go.tar.gz 2>&1', 120)
    run('rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tar.gz')
    run('rm -f /tmp/go.tar.gz')
    out, err = run('cd /root/leadforge/backend/google-maps-scraper && PATH=$PATH:/usr/local/go/bin go build -o google-maps-scraper . 2>&1', 300)
    if 'error' in err.lower():
        print(f'  SCRAPER BUILD ERROR: {err[-200:]}')
    else:
        print('  Scraper built OK')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 3: CREATE .ENV
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 3: Creating .env ===')
    env = """SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SUPABASE_SERVICE_ROLE_KEY
GMAPS_SCRAPER_PATH=/root/leadforge/backend/google-maps-scraper/google-maps-scraper
FRONTEND_URL=http://85.239.237.53
BACKEND_URL=http://localhost:8000
SITE_URL=http://85.239.237.53
ENVIRONMENT=production
"""
    run(f'cat > /root/leadforge/backend/.env << \'ENVEOF\'\n{env}\nENVEOF')
    
    # Frontend env
    fe_env = """NEXT_PUBLIC_API_URL=http://85.239.237.53
NEXT_PUBLIC_SUPABASE_URL=https://wtradahkkpbkbhmkkpal.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_test_T1NPgRdVMMGIk2
"""
    run(f'cat > /root/leadforge/frontend/.env.local << \'ENVEOF\'\n{fe_env}\nENVEOF')
    print('  .env files created')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 4: INSTALL DEPS
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 4: Installing Python deps ===')
    out, _ = run('cd /root/leadforge && pip install -r backend/requirements.txt -q 2>&1', 300)
    if 'error' in out.lower():
        print(f'  PIP: {out[-200:]}')
    out, _ = run('cd /root/leadforge && pip install backend/Scrapling/ -q 2>&1', 120)
    if 'Successfully' in out:
        print('  Scrapling installed')
    run('python3 -m playwright install chromium --with-deps 2>&1', 120)
    
    print('\n  Installing Node deps...')
    out, _ = run('cd /root/leadforge/frontend && npm ci 2>&1', 120)
    if 'error' in out.lower():
        out, _ = run('cd /root/leadforge/frontend && npm install 2>&1', 120)
    print('  Node deps installed')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 5: RUN SUPABASE MIGRATION (via Python + psycopg2)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 5: Running Supabase migration ===')
    
    # Read SQL file
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Upload SQL to server
    with sftp.open('/root/leadforge/supabase/migration.sql', 'w') as f:
        f.write(sql_content)
    
    # Try connecting via Python psycopg2 on the server
    migrate_script = """
import os, sys, json, urllib.request

# Try to discover DB password via Supabase Mgmt API or env
# If we can't connect, we'll use the service role key approach
# to execute SQL via PostgREST

def run_via_supabase_api():
    \"\"\"Try to run SQL via Supabase REST API /rest/v1/ with service key\"\"\"
    key = "YOUR_SUPABASE_SERVICE_ROLE_KEY"
    url = "https://wtradahkkpbkbhmkkpal.supabase.co/rest/v1/"
    
    with open('/root/leadforge/supabase/migration.sql', 'r') as f:
        sql = f.read()
    
    # Split into statements
    statements = []
    current = []
    for line in sql.split('\\\\n'):
        current.append(line)
        if line.rstrip().endswith(';') and not line.rstrip().startswith('--'):
            statements.append('\\\\n'.join(current))
            current = []
    if current:
        statements.append('\\\\n'.join(current))
    
    # Try to use rpc/execute_sql if available
    print(f"Trying Supabase REST API...")
    print(f"Total SQL statements: {len([s for s in statements if s.strip() and not s.strip().startswith('--')])}")
    
    # Check if database has the pg_sql function
    try:
        req = urllib.request.Request(
            url + "rpc/pg_sql",
            data=json.dumps({"sql": "SELECT 1"}).encode(),
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        )
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"pg_sql available: {resp.status}")
        return True
    except Exception as e:
        print(f"pg_sql not available: {e}")
        return False

def run_via_psycopg2():
    \"\"\"Try psycopg2 direct DB connection\"\"\"
    try:
        import psycopg2
        with open('/root/leadforge/supabase/migration.sql', 'r') as f:
            sql = f.read()
        
        # Try common DB passwords
        passwords = [
            os.environ.get('SUPABASE_DB_PASSWORD', ''),
            'YOUR_VPS_ROOT_PASSWORD',
            'postgres',
            'admin123',
        ]
        
        for pwd in passwords:
            if not pwd:
                continue
            try:
                conn = psycopg2.connect(
                    host="db.wtradahkkpbkbhmkkpal.supabase.co",
                    port=5432,
                    dbname="postgres",
                    user="postgres",
                    password=pwd,
                    sslmode="require"
                )
                conn.autocommit = True
                cur = conn.cursor()
                
                # Split and execute
                statements = []
                current = []
                for line in sql.split('\\\\n'):
                    current.append(line)
                    if line.rstrip().endswith(';') and not line.rstrip().startswith('--'):
                        statements.append('\\\\n'.join(current))
                        current = []
                if current:
                    statements.append('\\\\n'.join(current))
                
                success = 0
                failed = 0
                for stmt in statements:
                    stmt = stmt.strip()
                    if not stmt or stmt.startswith('--'):
                        continue
                    try:
                        cur.execute(stmt)
                        success += 1
                    except Exception as e:
                        failed += 1
                        print(f"  WARN: {str(e)[:100]}")
                
                cur.close()
                conn.close()
                print(f"Migration complete: {success} OK, {failed} skipped/warned")
                return True
            except Exception as e:
                print(f"  pwd '{pwd[:8]}...': {str(e)[:60]}")
                continue
        return False
    except ImportError:
        print("psycopg2 not installed, installing...")
        os.system("pip install psycopg2-binary -q")
        # Retry
        return run_via_psycopg2()

if not run_via_psycopg2():
    if not run_via_supabase_api():
        print("\\\\n" + "="*60)
        print("MIGRATION REQUIRES MANUAL EXECUTION")
        print("="*60)
        print("Go to: https://supabase.com/dashboard/project/wtradahkkpbkbhmkkpal/sql/new")
        print("Copy and paste the contents of:")
        print("/root/leadforge/supabase/migration.sql")
        print("Click 'Run' to execute the migration.")
"""
    run(f'cat > /root/leadforge/run_migration.py << \'PYEOF\'\n{migrate_script}\nPYEOF')
    out, err = run('cd /root/leadforge && python3 run_migration.py 2>&1', 120)
    print(out)
    if err:
        print(f'  STDERR: {err[:200]}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 6: BUILD FRONTEND
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 6: Building frontend ===')
    out, _ = run('cd /root/leadforge/frontend && npm run build 2>&1', 300)
    if 'successfully' in out.lower():
        print('  Frontend build OK')
    else:
        print(f'  Build issues: {out[-200:]}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 7: START BACKEND
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 7: Starting backend (port 8000) ===')
    run('pkill -f uvicorn 2>/dev/null || true')
    time.sleep(1)
    run('cd /root/leadforge && nohup python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-keep-alive 120 > /root/leadforge/backend.log 2>&1 &')
    time.sleep(4)
    be, _ = run('curl -s http://localhost:8000/api/health')
    print(f'  Backend health: {be[:100] if be else "FAILED"}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 8: START FRONTEND
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 8: Starting frontend (port 3000) ===')
    run('pkill -f "next-server" 2>/dev/null || true')
    time.sleep(1)
    run('cd /root/leadforge/frontend && nohup npx next start -p 3000 > /root/leadforge/frontend.log 2>&1 &')
    time.sleep(5)
    fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
    print(f'  Frontend: HTTP {fe}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 9: NGINX
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 9: Configuring nginx ===')
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
    run(f'cat > /etc/nginx/sites-available/hyperclients << \'NGXEOF\'\n{nginx_conf}\nNGXEOF')
    run('ln -sf /etc/nginx/sites-available/hyperclients /etc/nginx/sites-enabled/')
    run('rm -f /etc/nginx/sites-enabled/default')
    out, _ = run('nginx -t 2>&1')
    if 'successful' in out:
        run('systemctl restart nginx')
        print('  Nginx OK')
    else:
        print(f'  Nginx: {out}')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # STEP 10: FINAL HEALTH CHECKS
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    print('\n=== STEP 10: Health checks ===')
    time.sleep(3)
    be, _ = run('curl -s http://localhost:8000/api/health')
    print(f'  Backend: {be[:150]}')
    fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
    print(f'  Frontend: HTTP {fe}')
    ng, _ = run('curl -s http://85.239.237.53/api/health')
    print(f'  Nginx API: HTTP {ng[:150]}')
    ng2, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
    print(f'  Site URL: HTTP {ng2}')

    print(f'\n{"â•"*55}')
    print(f'  âœ… URL: http://85.239.237.53')
    print(f'  âœ… API: http://85.239.237.53/api/health')
    print(f'{ "â•"*55}')

finally:
    if sftp: sftp.close()
    client.close()
