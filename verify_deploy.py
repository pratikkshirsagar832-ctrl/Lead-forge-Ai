import paramiko, time, httpx

host = '178.16.138.221'
user = 'root'
pw = 'Kshirsagar@12341111'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=30)

def run(cmd, timeout=120):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return stdout.read().decode('utf-8', 'replace'), stderr.read().decode('utf-8', 'replace')

time.sleep(15)

# 1. Confirm git version on server
out, _ = run('cd /root/leadforge && git log --oneline -1')
print("=== SERVER COMMIT ===")
print(out.strip())

# 2. Backend startup logs
out, _ = run('docker logs --tail 25 leadforge-backend-1 2>&1')
print("\n=== BACKEND STARTUP ===")
print(out[-1200:])

# 3. Frontend up?
out, _ = run('docker ps --format "{{.Names}} {{.Status}}" | grep leadforge')
print("\n=== CONTAINERS ===")
print(out)

client.close()

# 4. Public health
r = httpx.get('https://hyperclients.online/api/hyper-agent/health', timeout=30)
print("\n=== HEALTH ===")
print(r.text[:300])
