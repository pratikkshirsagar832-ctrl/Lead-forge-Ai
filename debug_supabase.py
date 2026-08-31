import httpx, os

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

H = {'apikey': SR, 'Authorization': 'Bearer ' + SR}
BASE = URL + '/rest/v1'

# 1. Recent searches
r = httpx.get(BASE + '/searches', headers=H,
    params={'select': 'id,niche,status,total_results,max_results,created_at', 'source': 'eq.hyper_agent', 'order': 'created_at.desc', 'limit': 5}, timeout=30)
print("RECENT SEARCHES:")
for s in r.json():
    print(f"  {s['id'][:8]} | {s.get('created_at','')[:16]} | req={s.get('max_results')} got={s.get('total_results')} | {s.get('status')}")

# 2. Leads for the e2e search
sid = 'b4a3cf5b-df5c-456a-93b9-3d8ee2677870'
r = httpx.get(BASE + '/leads', headers=H, params={'select': 'id', 'search_id': 'eq.' + sid}, timeout=30)
print(f"\nLEADS for {sid[:8]}: {len(r.json())}")

# 3. All recent leads (no filter)
r = httpx.get(BASE + '/leads', headers=H, params={'select': 'id,search_id,business_name,post_type', 'order': 'created_at.desc', 'limit': 10}, timeout=30)
print("\nRECENT LEADS:")
for l in r.json():
    print(f"  {l['search_id'][:8]} | {l.get('business_name','')[:25]} | {l.get('post_type')}")
