import paramiko
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('178.16.138.221', username='root', password='Kshirsagar@12341111', timeout=30)
cmd = "docker logs --tail 400 leadforge-backend-1 2>&1 | grep -iE 'FAST start|wave done|lane|raw|Triage|Tier|scored|job filler|budget|country' | tail -35"
i, o, e = c.exec_command(cmd, timeout=30)
print(o.read().decode('utf-8', 'replace')[-4000:])
c.close()
