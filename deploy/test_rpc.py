import sys, requests, json
sys.path.insert(0, '/root/leadforge/backend')
from app.config import Settings

settings = Settings()
supabase_url = settings.supabase_url
service_key = settings.supabase_service_role_key
headers = {'apikey': service_key, 'Authorization': f'Bearer {service_key}', 'Content-Type': 'application/json'}

# Get list of users
r = requests.get(f'{supabase_url}/rest/v1/user_subscriptions?select=*', headers=headers)
print('Subscriptions:', r.status_code, r.text[:500] if r.text else 'empty')
if r.status_code == 200:
    subs = r.json()
    if subs:
        for sub in subs[:3]:
            uid = sub.get('user_id', 'unknown')
            print(f'\nUser: {uid}')
            r2 = requests.post(f'{supabase_url}/rest/v1/rpc/get_remaining_searches', 
                headers=headers, json={'p_user_id': uid})
            print(f'  get_remaining_searches: {r2.status_code} -> {r2.text[:200]}')
            r3 = requests.post(f'{supabase_url}/rest/v1/rpc/get_user_subscription', 
                headers=headers, json={'p_user_id': uid})
            print(f'  get_user_subscription: {r3.status_code} -> {r3.text[:500]}')
    else:
        print('No subscriptions found - checking users...')
        r4 = requests.get(f'{supabase_url}/rest/v1/users?select=id', headers=headers)
        print(f'Users: {r4.status_code} -> {r4.text[:500]}')
