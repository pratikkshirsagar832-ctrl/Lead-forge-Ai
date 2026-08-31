import paramiko, sys

host = '178.16.138.221'
user = 'root'
pw = 'Kshirsagar@12341111'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=30)

def run(cmd, timeout=600):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace')
    err = stderr.read().decode('utf-8', 'replace')
    return out, err

# 1. Verify SSH + current git state
out, err = run('cd /root/leadforge && git log --oneline -3 && git status --short | head -5')
print("=== GIT STATE ===")
print(out[:800])
if err.strip():
    print("ERR:", err[:200])

# 2. Pull latest
print("\n=== GIT PULL ===")
out, err = run('cd /root/leadforge && git pull 2>&1 | tail -5')
print(out[:500])

# 3. Rebuild + restart backend & frontend
print("\n=== DEPLOY (build may take a few minutes) ===")
out, err = run('cd /root/leadforge && docker compose up -d --build 2>&1 | tail -15', timeout=900)
print(out[:1500])

# 4. Container status
print("\n=== CONTAINERS ===")
out, err = run('docker ps --format "{{.Names}} {{.Status}}" | grep leadforge')
print(out)

# 5. Check backend logs for startup + last search
print("\n=== BACKEND LOG TAIL ===")
out, err = run('docker logs --tail 15 leadforge-backend-1 2>&1')
print(out[:1500])

client.close()
print("\nDONE")
