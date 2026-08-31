import paramiko, json, httpx

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('178.16.138.221', username='root', password='Kshirsagar@12341111', timeout=30)

stdin, stdout, stderr = c.exec_command("docker exec leadforge-backend-1 env | grep SUPABASE", timeout=10)
env = stdout.read().decode('utf-8', 'replace')
supabase_url = supabase_key = ""
for line in env.split('\n'):
    if 'SUPABASE_URL' in line and '=' in line:
        supabase_url = line.split('=', 1)[1].strip()
    if 'SUPABASE_SERVICE_ROLE_KEY' in line and '=' in line:
        supabase_key = line.split('=', 1)[1].strip()

headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}

# Fetch with CORRECT column names
r = httpx.get(f"{supabase_url}/rest/v1/leads", headers=headers, params={
    "select": "business_name,post_url,linkedin_url,full_address,post_type,ai_confidence_score,lead_category,headline,profile_picture_url,connections_count",
    "category": "eq.LinkedIn",
    "order": "created_at.desc",
    "limit": 10
}, timeout=15)
leads = r.json()
print(f"=== {len(leads)} RECENT LINKEDIN LEADS (correct columns) ===")
for lead in leads:
    bn = lead.get('business_name', '?')
    post_url = lead.get('post_url', '')
    li_url = lead.get('linkedin_url', '')
    addr = lead.get('full_address', '')
    pt = lead.get('post_type', '')
    score = lead.get('ai_confidence_score', 0)
    cat = lead.get('lead_category', '')
    hl = lead.get('headline', '')
    avatar = lead.get('profile_picture_url', '')
    conn = lead.get('connections_count', 0)
    
    has_post = "YES" if post_url else "NO"
    has_li = "YES" if li_url else "NO"
    has_addr = "YES" if addr else "NO"
    
    print(f"\n--- {bn} [{cat}] score={score} ---")
    print(f"  Type: {pt} | Connections: {conn}")
    print(f"  Headline: {hl[:100] if hl else '(empty)'}")
    print(f"  Location: {addr[:80] if addr else '(empty)'} [{has_addr}]")
    print(f"  Post URL: {post_url[:80] if post_url else '(empty)'} [{has_post}]")
    print(f"  LinkedIn: {li_url[:80] if li_url else '(empty)'} [{has_li}]")
    print(f"  Avatar: {'YES' if avatar else 'NO'}")

# Summary
total = len(leads)
with_post = sum(1 for l in leads if l.get('post_url'))
with_li = sum(1 for l in leads if l.get('linkedin_url'))
with_addr = sum(1 for l in leads if l.get('full_address'))
print(f"\n=== SUMMARY: {total} leads | post_url: {with_post}/{total} | linkedin_url: {with_li}/{total} | location: {with_addr}/{total} ===")

c.close()
