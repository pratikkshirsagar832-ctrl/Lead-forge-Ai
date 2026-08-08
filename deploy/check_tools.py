import paramiko, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

for cmd in [
    'which python3 && python3 --version',
    'which node && node --version',
    'which npm && npm --version',
    'which go && go version 2>/dev/null || echo "Go not installed"',
    'which nginx && nginx -v 2>&1',
    'ls /root/leadforge/backend/google-maps-scraper/ | head -5',
    'cat /root/leadforge/backend/google-maps-scraper/go.mod | head -3',
]:
    out, err = run(cmd)
    print(f'$ {cmd.split("&&")[0].strip()}')
    print(f'  {out[:100]}')
    if err: print(f'  ERR: {err[:100]}')

client.close()
