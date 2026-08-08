import paramiko, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

print('=== Current processes ===')
out, _ = run('ps aux | grep -E "uvicorn|next|node" | grep -v grep')
print(out[:1000] if out else '  No running processes')

print('\n=== Current code at /root/leadforge ===')
out, _ = run('ls -la /root/leadforge/ 2>/dev/null || echo "Directory not found"')
print(out[:500])

print('\n=== Backend structure ===')
out, _ = run('ls /root/leadforge/backend/ 2>/dev/null || echo "backend not found"')
print(out[:500])

print('\n=== Server health ===')
out, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>/dev/null || echo "no backend"')
print(f'Backend: HTTP {out}')
out, _ = run('curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/ 2>/dev/null || echo "no frontend"')
print(f'Frontend: HTTP {out}')

client.close()
