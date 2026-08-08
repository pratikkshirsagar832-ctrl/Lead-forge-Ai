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

print('â•â•â• PHASE 1: KILL HOST PROCESSES â•â•â•')

# Find and kill all processes on port 8000 and 3000
print('Killing existing services on host...')
run("fuser -k 8000/tcp 2>/dev/null || true")
run("fuser -k 3000/tcp 2>/dev/null || true")
time.sleep(2)

# Also kill any python3/next-server processes from /root/leadforge
run("pkill -f 'uvicorn' 2>/dev/null || true")
run("pkill -f 'next-server' 2>/dev/null || true")
run("pkill -f 'python3.*leadforge' 2>/dev/null || true")
time.sleep(2)

# Verify ports are free
out, _ = run('ss -tlnp | grep -E ":(8000|3000) "')
print(f'Ports after kill: {out or "Free"}')

print('\nâ•â•â• PHASE 2: DOCKER CLEANUP â•â•â•')
run('docker compose -f /root/leadforge/docker-compose.yml down 2>&1', 60)
run('docker rm -f $(docker ps -aq) 2>/dev/null')
print('Docker cleaned')

print('\nâ•â•â• PHASE 3: BUILD â•â•â•')
# Build using cache (faster)
print('Building frontend...')
out, err = run('cd /root/leadforge && docker compose build frontend 2>&1', 600)
if 'error' in (out+err).lower() and 'failed' in (out+err).lower():
    print(f'FRONTEND BUILD ERROR:\n{(out+err)[-500:]}')
else:
    print('Frontend OK')

print('Building backend...')
out, err = run('cd /root/leadforge && docker compose build backend 2>&1', 600)
if 'error' in (out+err).lower() and 'failed' in (out+err).lower():
    print(f'BACKEND BUILD ERROR:\n{(out+err)[-500:]}')
else:
    print('Backend OK')

print('\nâ•â•â• PHASE 4: START â•â•â•')
out, err = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:300])

time.sleep(15)

print('\nâ•â•â• PHASE 5: VERIFY â•â•â•')
out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(f'Containers:\n{out}')

# Logs
out, _ = run('docker compose -f /root/leadforge/docker-compose.yml logs --tail=20 2>&1')
if 'Error' in out or 'Traceback' in out:
    print(f'Errors in logs:\n{out[:1500]}')

# Health checks
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'Backend: {be[:150]}')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')
ng, _ = run('curl -s http://85.239.237.53/ | head -c 200')
print(f'Nginx HTML: {ng[:100]}')
ng_api, _ = run('curl -s http://85.239.237.53/api/health')
print(f'Nginx API: {ng_api[:150]}')

client.close()
print(f'\n{"="*40}')
print(f'  URL: http://85.239.237.53')
print(f'  Dashboard: http://85.239.237.53/dashboard')
print(f'{"="*40}')
