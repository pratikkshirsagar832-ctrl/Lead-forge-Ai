import httpx, json, os
from datetime import datetime, timezone

os.chdir('backend')
SR = None
with open('.env') as f:
    for line in f:
        if line.startswith('SUPABASE_URL='): URL = line.split('=',1)[1].strip()
        if line.startswith('SUPABASE_SERVICE_ROLE_KEY='): SR = line.split('=',1)[1].strip()

H = {'apikey': SR, 'Authorization': 'Bearer ' + SR, 'Content-Type': 'application/json'}
BASE = URL + '/rest/v1'

# Recent hyper_agent searches
r = httpx.get(BASE + '/searches', headers=H,
    params={'select': 'id,niche,location,status,total_results,max_results,created_at,message',
            'source': 'eq.hyper_agent', 'order': 'created_at.desc', 'limit': 8}, timeout=30)
searches = r.json()
print(f"=== {len(searches)} recent HyperAgent searches ===")
for s in searches:
    print(f"  {s.get('created_at','')[:16]} | {s.get('niche','')[:35]} | {s.get('location','')[:12]} | req={s.get('max_results')} got={s.get('total_results')} | {s.get('status')}")

# For each recent search, get leads and inspect quality
print("\n=== LEADS QUALITY CHECK ===")
for s in searches[:4]:
    sid = s['id']
    r2 = httpx.get(BASE + '/leads', headers=H,
        params={'select': 'business_name,headline,category,full_address,post_type,ai_confidence_score,ai_reason,linkedin_url,post_url,created_at',
                'search_id': 'eq.' + sid, 'limit': 8}, timeout=30)
    leads = r2.json()
    print(f"\n--- {s.get('niche','')[:40]} ({s.get('location','')}) [{s.get('status')}] ---")
    for l in leads:
        score = l.get('ai_confidence_score')
        print(f"  {l.get('business_name','?')[:25]:25} | {l.get('post_type','?'):10} | score={score} | {str(l.get('full_address',''))[:20]}")
        print(f"      headline: {str(l.get('headline',''))[:80]}")
        print(f"      reason: {str(l.get('ai_reason',''))[:70]}")
