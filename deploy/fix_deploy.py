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

# â”€â”€ Fix 1: Replace frontend Dockerfile with simpler version â”€â”€
print('=== Fixing Frontend Dockerfile ===')
frontend_df = """FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 3000

CMD ["npx", "next", "start", "-p", "3000"]
"""
run(f'cat > /root/leadforge/frontend/Dockerfile << \'DFEOF\'\n{frontend_df}\nDFEOF')
out, _ = run('cat /root/leadforge/frontend/Dockerfile')
print(f'New Dockerfile:\n{out}')

# â”€â”€ Fix 2: Remove output: standalone from next.config.ts â”€â”€
run(r"sed -i 's/output: .standalone.,//g' /root/leadforge/frontend/next.config.ts")
run(r"sed -i 's/output: .standalone.,//g' /root/leadforge/frontend/next.config.ts")
out, _ = run('cat /root/leadforge/frontend/next.config.ts')
print(f'\nnext.config.ts:\n{out}')

# â”€â”€ Fix 3: Remove conflicting nginx site â”€â”€
print('\n=== Fixing Nginx ===')
run('rm -f /etc/nginx/sites-enabled/leadforge')
out, _ = run('ls -la /etc/nginx/sites-enabled/')
print(f'sites-enabled:\n{out}')

# â”€â”€ Fix 4: Clean rebuild â”€â”€
print('\n=== Cleaning & Rebuilding ===')
run('docker compose -f /root/leadforge/docker-compose.yml down 2>&1', 60)
run('docker rm -f $(docker ps -aq) 2>/dev/null')

# Build both
print('\n=== Building frontend ===')
out, err = run('cd /root/leadforge && docker compose build --no-cache frontend 2>&1', 600)
if 'error' in (out + err).lower() and 'failed' in (out + err).lower():
    print(f'BUILD ERROR:\n{(out+err)[-800:]}')
else:
    print('Frontend build OK')

print('\n=== Building backend ===')
out, err = run('cd /root/leadforge && docker compose build --no-cache backend 2>&1', 600)
if 'error' in (out + err).lower() and 'failed' in (out + err).lower():
    print(f'BUILD ERROR:\n{(out+err)[-800:]}')
else:
    print('Backend build OK')

# Start
print('\n=== Starting services ===')
out, err = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:500])

# Wait
import time
print('Waiting 20s for services...')
time.sleep(20)

# Check
out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(f'\nStatus:\n{out}')

# Logs if issues
out, err = run('docker compose -f /root/leadforge/docker-compose.yml logs --tail=50 2>&1')
if err: print(f'Logs: {err[:500]}')
if 'Error' in out: print(f'Errors: {out[:1000]}')

# Health
print('\n=== Health ===')
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'Backend: {be[:150]}')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')
ng, _ = run('curl -s http://85.239.237.53/ | head -c 200')
print(f'Nginx: {ng[:100]}')
ng_api, _ = run('curl -s http://85.239.237.53/api/health')
print(f'Nginx API: {ng_api[:100]}')

client.close()

print(f'\n{"="*50}')
print(f'DEPLOYED: http://85.239.237.53')
print(f'{"="*50}')
