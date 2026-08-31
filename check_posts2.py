import httpx, os

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

H = {'apikey': SR, 'Authorization': 'Bearer ' + SR}
BASE = URL + '/rest/v1'

r = httpx.get(BASE + '/leads', headers=H,
    params={'select': 'business_name,headline,post_text,post_url,ai_reason,ai_confidence_score', 'search_id': 'eq.96449500-5c55-4e2b-ba2c-6c36f45c8f7e'}, timeout=30)
leads = r.json()

print(f'=== {len(leads)} LEADS - ACTUAL POSTS ===')
for i, l in enumerate(leads):
    print()
    print('=' * 72)
    print(f"{i+1}. {l.get('business_name')} | score={l.get('ai_confidence_score')}")
    print(f"   headline: {l.get('headline','')}")
    print(f"   post_url: {l.get('post_url','')}")
    print(f"   reason: {l.get('ai_reason','')}")
    print(f"   --- POST TEXT (first 600) ---")
    print(f"   {str(l.get('post_text',''))[:600]}")
