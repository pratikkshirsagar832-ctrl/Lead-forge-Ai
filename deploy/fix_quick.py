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

# Fix next.config.ts
print('=== Fixing next.config.ts ===')
run("sed -i '/output:/d' /root/leadforge/frontend/next.config.ts")
out, _ = run('cat /root/leadforge/frontend/next.config.ts')
print(out)

# Fix Dockerfile
print('\n=== Fixing Frontend Dockerfile ===')
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

# Remove old nginx site
print('\n=== Cleaning Nginx ===')
run('rm -f /etc/nginx/sites-enabled/leadforge')
out, _ = run('ls -la /etc/nginx/sites-enabled/')
print(out)

# Stop & cleanup old containers
print('\n=== Cleaning old containers ===')
run('docker compose -f /root/leadforge/docker-compose.yml down 2>&1', 60)
run('docker rm -f $(docker ps -aq) 2>/dev/null')

# Build frontend (with cache - faster)
print('\n=== Building frontend ===')
run('cd /root/leadforge && docker compose build frontend 2>&1', 600)

# Build backend (with cache - faster since only the Dockerfile changed)
print('\n=== Building backend ===')
run('cd /root/leadforge && docker compose build backend 2>&1', 600)

# Start everything
print('\n=== Starting services ===')
out, _ = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:300])

time.sleep(15)

# Status
out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(f'\nContainers:\n{out}')

# Logs if issues
out, _ = run('docker compose -f /root/leadforge/docker-compose.yml logs --tail=30 2>&1')
if 'Error' in out or 'error' in out:
    print(f'Logs: {out[:1500]}')

# Health
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'\nBackend: {be[:150]}')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')
ng, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
print(f'Nginx: HTTP {ng}')

client.close()
print(f'\n{"="*40}')
print(f'DONE: http://85.239.237.53')
print(f'{"="*40}')
