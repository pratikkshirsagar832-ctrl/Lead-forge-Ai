import httpx, json, os

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

H = {'apikey': SR, 'Authorization': 'Bearer ' + SR}
BASE = URL + '/rest/v1'

search_id = 'b2ba03b7-6815-4384-8b8c-f73d0d37d203'

# Search record
r = httpx.get(BASE + '/searches', headers=H,
    params={'select': 'niche,location,max_results,total_results,status,message,created_at', 'id': 'eq.' + search_id}, timeout=30)
s = r.json()[0]
print(f"SEARCH: {s.get('niche')} | {s.get('location')} | requested={s.get('max_results')} got={s.get('total_results')} | {s.get('status')}")
print(f"MESSAGE: {s.get('message')}\n")

# Leads
r = httpx.get(BASE + '/leads', headers=H,
    params={'select': 'business_name,headline,category,full_address,post_type,ai_confidence_score,ai_reason,linkedin_url,post_url', 'search_id': 'eq.' + search_id}, timeout=30)
leads = r.json()
print(f"=== {len(leads)} LEADS ===")
for i, l in enumerate(leads):
    print(f"\n{i+1}. {l.get('business_name')} | type={l.get('post_type')} | score={l.get('ai_confidence_score')}")
    print(f"   headline: {l.get('headline','')}")
    print(f"   location: {l.get('full_address','')}")
    print(f"   reason: {l.get('ai_reason','')}")
    print(f"   linkedin: {l.get('linkedin_url','')}")
    print(f"   post_url: {l.get('post_url','')}")
