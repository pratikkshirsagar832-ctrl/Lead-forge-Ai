"""Clean the server - remove old code and processes"""
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

print('Killing processes...')
run('pkill -f uvicorn 2>/dev/null || true')
run('pkill -f "next-server" 2>/dev/null || true')
run('pkill -f google-maps-scraper 2>/dev/null || true')

print('Removing old code...')
run('rm -rf /root/leadforge')

print('Removing old nginx config...')
run('rm -f /etc/nginx/sites-enabled/hyperclients')
run('rm -f /etc/nginx/sites-available/hyperclients')

print('Restarting nginx...')
run('systemctl restart nginx')

print('Verifying cleanup...')
out, _ = run('ls /root/leadforge 2>/dev/null || echo "CLEAN"')
print(f'  /root/leadforge: {out}')

out, _ = run('ps aux | grep -E "uvicorn|next" | grep -v grep || echo "No processes"')
print(f'  Processes: {out}')

client.close()
print('\nServer cleaned.')
