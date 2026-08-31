import httpx, json, os, time, uuid, random, string

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
email = f'teste2e-{suffix}@leadforge.test'
password = 'TestE2E@' + ''.join(random.choices(string.ascii_letters + string.digits, k=8))
print(f"Test user: {email}")

# 1. Create user via Supabase admin API
r = httpx.post(URL + '/auth/v1/admin/users', headers=H_ADMIN,
    json={'email': email, 'password': password, 'email_confirm': True}, timeout=30)
print("1. create user:", r.status_code)
if r.status_code not in (200, 201):
    print(r.text[:300]); raise SystemExit(1)
user_id = r.json()['id']

# 2. Grant agency plan (user_subscriptions)
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

# 4. Trigger scrape: 3 hiring leads, web/app development, India
conversation = [
    {"role": "user", "content": "I need 3 leads (count: 3)"},
    {"role": "assistant", "content": "Got it — 3 hiring leads."},
    {"role": "user", "content": "yes"},
]
context = {
    "niche": "app development, web development",
    "roles": "CTO, Founder, Marketing Manager",
    "location": "India",
    "count": 3,
    "lead_types": ["hiring"],
    "posted_within": "month",
}
r = httpx.post(API + '/hyper-agent/scrape', headers=H_USER, json={'context': context, 'conversation': conversation}, timeout=30)
print("4. scrape:", r.status_code, r.text[:150])
if r.status_code != 200:
    print(r.text[:400]); raise SystemExit(1)
search_id = r.json()['search_id']
print("   search_id:", search_id)

# 5. Poll until done (max ~4 min)
t0 = time.time()
final = None
while time.time() - t0 < 300:
    time.sleep(5)
    r = httpx.get(f'{API}/hyper-agent/results/{search_id}', headers=H_USER, timeout=30)
    d = r.json()
    status = d.get('search', {}).get('status')
    if status in ('completed', 'failed'):
        final = d
        print(f"5. status={status} after {int(time.time()-t0)}s, leads={len(d.get('leads', []))}")
        print("   message:", d.get('search', {}).get('message', '')[:150])
        break

if final and final.get('search', {}).get('status') == 'completed':
    leads = final['leads']
    print(f"\n=== RESULTS: {len(leads)} leads (requested 3) ===")
    for i, l in enumerate(leads[:10]):
        print(f"{i+1}. {str(l.get('business_name',''))[:28]:28} | {str(l.get('post_type','')):9} | score={l.get('ai_confidence_score')} | {str(l.get('full_address',''))[:22]}")
        print(f"   headline: {str(l.get('headline',''))[:75]}")
        print(f"   reason: {str(l.get('ai_reason',''))[:65]}")
        print(f"   post_url: {str(l.get('post_url',''))[:80]}")
        print()

# Keep test user + search in DB so we can audit actual posts afterwards
print("\nSearch ID for audit:", search_id)
print("Test user kept for audit:", email, "|", password)
