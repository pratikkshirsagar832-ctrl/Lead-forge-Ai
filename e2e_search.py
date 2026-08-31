import httpx, json, os, time, random, string

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

API = 'https://hyperclients.online/api'
H_ADMIN = {'apikey': SR, 'Authorization': 'Bearer ' + SR, 'Content-Type': 'application/json'}
BASE = URL + '/rest/v1'

suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
email = f'testsearch-{suffix}@leadforge.test'
password = 'TestS@' + ''.join(random.choices(string.ascii_letters + string.digits, k=8))
print(f"Test user: {email}")

# 1. Create user
r = httpx.post(URL + '/auth/v1/admin/users', headers=H_ADMIN,
    json={'email': email, 'password': password, 'email_confirm': True}, timeout=30)
print("1. create user:", r.status_code)
if r.status_code not in (200, 201):
    print(r.text[:300]); raise SystemExit(1)
user_id = r.json()['id']

# 2. Agency plan
r = httpx.post(BASE + '/user_subscriptions', headers=H_ADMIN, json={
    'user_id': user_id, 'plan_id': 'agency', 'status': 'active',
    'current_period_start': '2026-08-31T00:00:00.000Z',
    'current_period_end': '2026-12-31T23:59:59.000Z',
}, timeout=30)
print("2. agency plan:", r.status_code)

# 3. Login
r = httpx.post(URL + '/auth/v1/token?grant_type=password',
    headers={'apikey': SR, 'Content-Type': 'application/json'},
    json={'email': email, 'password': password}, timeout=30)
print("3. login:", r.status_code)
token = r.json()['access_token']
H_USER = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

# 4. Start LinkedIn search: 3 hiring leads, web/app development, India
payload = {
    "niche": "app development, web development",
    "location": "India",
    "source": "linkedin",
    "enrich_emails": False,
    "max_results": 3,
    "lead_types": ["hiring"],
}
r = httpx.post(API + '/searches', headers=H_USER, json=payload, timeout=30)
print("4. search:", r.status_code)
if r.status_code not in (200, 201):
    print(r.text[:400]); raise SystemExit(1)
data = r.json()
search_id = data['id'] if isinstance(data, dict) else data[0]['id']
print("   search_id:", search_id)

# 5. Poll results
t0 = time.time()
final = None
while time.time() - t0 < 360:
    time.sleep(5)
    r = httpx.get(f'{API}/searches/{search_id}/results?page=1&per_page=50', headers=H_USER, timeout=30)
    if r.status_code != 200:
        continue
    d = r.json()
    items = d.get('items') or []
    status = d.get('search', {}).get('status') if 'search' in d else None
    # fetch status via searches table
    rs = httpx.get(BASE + '/searches', headers=H_ADMIN, params={'select': 'status,total_results,max_results,message', 'id': 'eq.' + search_id}, timeout=30)
    if rs.status_code == 200 and rs.json():
        s = rs.json()[0]
        status = s.get('status')
        if status in ('completed', 'failed'):
            final = {'search': s, 'leads': items}
            print(f"5. status={status} after {int(time.time()-t0)}s, leads={len(items)}")
            print("   message:", s.get('message', '')[:150])
            break

if final and final['search'].get('status') == 'completed':
    leads = final['leads']
    print(f"\n=== {len(leads)} LEADS (requested 3) ===")
    for i, l in enumerate(leads[:10]):
        print(f"{i+1}. {str(l.get('business_name',''))[:28]:28} | {str(l.get('post_type','')):9} | score={l.get('ai_confidence_score')} | {str(l.get('full_address',''))[:25]}")
        print(f"   headline: {str(l.get('headline',''))[:70]}")
        print(f"   post_url: {str(l.get('post_url',''))[:80]}")
print("\nSearch ID for audit:", search_id)
