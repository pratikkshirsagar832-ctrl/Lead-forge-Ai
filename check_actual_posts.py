import httpx, os

os.chdir('backend')
SR = URL = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

H = {'apikey': SR, 'Authorization': 'Bearer ' + SR}
BASE = URL + '/rest/v1'

search_id = 'b4a3cf5b-df5c-456a-93b9-3d8ee2677870'

r = httpx.get(BASE + '/leads', headers=H,
    params={'select': 'business_name,headline,post_text,post_url,ai_reason,ai_confidence_score,post_type', 'search_id': 'eq.' + search_id}, timeout=30)
leads = r.json()

print(f"=== {len(leads)} LEADS — ACTUAL POSTS ===")
for i, l in enumerate(leads):
    print(f"\n{'='*70}")
    print(f"{i+1}. {l.get('business_name')} | score={l.get('ai_confidence_score')} | type={l.get('post_type')}")
    print(f"   headline: {l.get('headline','')}")
    print(f"   post_url: {l.get('post_url','')}")
    print(f"   reason: {l.get('ai_reason','')}")
    print(f"   --- POST TEXT (first 700 chars) ---")
    print(f"   {str(l.get('post_text',''))[:700]}")
