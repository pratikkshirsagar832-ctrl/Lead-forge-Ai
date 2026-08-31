import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('178.16.138.221', username='root', password='Kshirsagar@12341111', timeout=30)
cmd = "docker logs --tail 200 leadforge-backend-1 2>&1 | grep -A 30 'UnboundLocalError'"
i, o, e = c.exec_command(cmd, timeout=30)
print(o.read().decode('utf-8', 'replace')[-3000:])
c.close()
