import paramiko, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=120):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return stdout.read().decode('utf-8', errors='replace').strip()

print('=== Current containers ===')
print(run('docker ps -a'))

print('\n=== Fixing Go version in Dockerfile ===')
out = run(r"sed -i 's/golang:1.23-bookworm/golang:1.24-bookworm/g' /root/leadforge/backend/Dockerfile")
out = run('head -12 /root/leadforge/backend/Dockerfile')
print(out)

print('\n=== Rebuilding backend ===')
out = run('cd /root/leadforge && docker compose build --no-cache backend 2>&1', 600)
print(out[-800:] if len(out) > 800 else out)

print('\n=== Starting services ===')
out = run('cd /root/leadforge && docker compose up -d 2>&1', 60)
print(out[:500])

print('\n=== Container status ===')
out = run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
print(out)

print('\n=== Health checks ===')
print('Backend:', run('curl -s http://localhost:8000/api/health')[:100])
print('Frontend:', run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/'))
print('Nginx:', run('curl -s -o /dev/null -w "%{http_code}" http://85.239.237.53/'))

client.close()
print('\n=== DONE ===')
