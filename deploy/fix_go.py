import paramiko, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=600):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

# Fix Dockerfile to use golang:latest
print('=== Updating Dockerfile ===')
run('sed -i "s/golang:1.24-bookworm/golang:latest/g" /root/leadforge/backend/Dockerfile')
run('sed -i "s/golang:1.23-bookworm/golang:latest/g" /root/leadforge/backend/Dockerfile')
out, _ = run('head -8 /root/leadforge/backend/Dockerfile')
print(out)

# Rebuild backend
print('\n=== Rebuilding backend ===')
out, err = run('cd /root/leadforge && docker compose build --no-cache backend 2>&1', 600)
combined = out + err
if 'error' in combined.lower() or 'failed' in combined.lower():
    print('BUILD ERROR (last 1000 chars):')
    print(combined[-1000:])
else:
    print('Build completed successfully')

# Check if successful
print('\n=== Checking backend image ===')
out, _ = run('docker images leadforge-backend --format "{{.Repository}}:{{.Tag}} {{.Size}}"')
print(out)

# Start everything
print('\n=== Starting services ===')
out, err = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:500])
if err: print(f'ERR: {err[:300]}')

# Check status
print('\n=== Container status ===')
out, _ = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(out)

# Health check
print('\n=== Health checks ===')
be, _ = run('curl -s http://localhost:8000/api/health')
print(f'Backend: {be[:150]}')
fe, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/')
print(f'Frontend: HTTP {fe}')
ng, _ = run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/')
print(f'Nginx: HTTP {ng}')

client.close()

url = 'http://85.239.237.53'
print(f'\n{"="*50}')
print(f'DEPLOYMENT COMPLETE!')
print(f'URL: {url}')
print(f'API: {url}/api/health')
print(f'Dashboard: {url}/dashboard')
print(f'{"="*50}')
