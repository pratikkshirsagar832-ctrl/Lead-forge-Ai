import paramiko, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('85.239.237.53', username='root', password='YOUR_VPS_ROOT_PASSWORD', timeout=15)

def run(cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return stdout.read().decode('utf-8', errors='replace').strip()

print('=== go.mod first 5 lines ===')
print(run('head -5 /root/leadforge/backend/google-maps-scraper/go.mod'))

print('\n=== go.mod last 5 lines ===')
print(run('tail -5 /root/leadforge/backend/google-maps-scraper/go.mod'))

print('\n=== Old binary check ===')
print(run('ls -la /root/leadforge/backend/google-maps-scraper/google-maps-scraper 2>/dev/null || echo "not found"'))

print('\n=== Check available Go images ===')
print(run('docker pull golang:latest 2>&1 | tail -3'))
print(run('docker run --rm golang:latest go version 2>&1'))

client.close()
print('\n=== Done ===')
