import httpx, json, os, time, random, string, sys

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

API = 'https://hyperclients.online/api'
H_ADMIN = {'apikey': SR, 'Authorization': 'Bearer ' + SR, 'Content-Type': 'application/json'}
BASE = URL + '/rest/v1'

# args: niche | location | lead_type (comma list) | count
niche = sys.argv[1] if len(sys.argv) > 1 else 'graphics design, ui-ux design'
location = sys.argv[2] if len(sys.argv) > 2 else 'India'
lead_types = (sys.argv[3] if len(sys.argv) > 3 else 'buyer').split(',')
count = int(sys.argv[4]) if len(sys.argv) > 4 else 5
print(f"SEARCH: niche='{niche}' | location='{location}' | types={lead_types} | count={count}")

suffix = ''.join(random.choices(string.ascii_lowercase, k=6))
email = f'testsearch-{suffix}@leadforge.test'
password = 'TestS@' + ''.join(random.choices(string.ascii_letters + string.digits, k=8))

r = httpx.post(URL + '/auth/v1/admin/users', headers=H_ADMIN,
    json={'email': email, 'password': password, 'email_confirm': True}, timeout=30)
if r.status_code not in (200, 201):
    print(r.text[:300]); raise SystemExit(1)
user_id = r.json()['id']

r = httpx.post(BASE + '/user_subscriptions', headers=H_ADMIN, json={
    'user_id': user_id, 'plan_id': 'agency', 'status': 'active',
    'current_period_start': '2026-08-31T00:00:00.000Z',
    'current_period_end': '2026-12-31T23:59:59.000Z',
}, timeout=30)

r = httpx.post(URL + '/auth/v1/token?grant_type=password',
    headers={'apikey': SR, 'Content-Type': 'application/json'},
    json={'email': email, 'password': password}, timeout=30)
token = r.json()['access_token']
H_USER = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

payload = {
    "niche": niche, "location": location, "source": "linkedin",
    "enrich_emails": False, "max_results": count, "lead_types": lead_types,
}
r = httpx.post(API + '/searches', headers=H_USER, json=payload, timeout=30)
print("search:", r.status_code)
if r.status_code not in (200, 201):
    print(r.text[:400]); raise SystemExit(1)
data = r.json()
search_id = data['id'] if isinstance(data, dict) else data[0]['id']
print("search_id:", search_id)

t0 = time.time()
final = None
while time.time() - t0 < 420:
    time.sleep(6)
    rs = httpx.get(BASE + '/searches', headers=H_ADMIN,
        params={'select': 'status,total_results,max_results,message', 'id': 'eq.' + search_id}, timeout=30)
    if rs.status_code == 200 and rs.json():
        s = rs.json()[0]
        if s.get('status') in ('completed', 'failed'):
            r = httpx.get(f'{API}/searches/{search_id}/results?page=1&per_page=50', headers=H_USER, timeout=30)
            items = r.json().get('items') or [] if r.status_code == 200 else []
            final = {'search': s, 'leads': items}
            print(f"status={s.get('status')} after {int(time.time()-t0)}s, leads={len(items)}")
            print("message:", s.get('message', '')[:150])
            break

if final and final['search'].get('status') == 'completed':
    leads = final['leads']
    print(f"\n=== {len(leads)} LEADS (requested {count}) ===")
    for i, l in enumerate(leads[:10]):
        print(f"{i+1}. {str(l.get('business_name',''))[:26]:26} | {str(l.get('post_type','')):9} | score={l.get('ai_confidence_score')} | {str(l.get('full_address',''))[:30]}")
        print(f"   headline: {str(l.get('headline',''))[:65]}")
        print(f"   post_url: {str(l.get('post_url',''))[:80]}")
print("\nAUDIT SEARCH ID:", search_id)
