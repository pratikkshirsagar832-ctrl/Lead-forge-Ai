import sys, requests, json
sys.path.insert(0, '/root/leadforge/backend')
from app.config import Settings

settings = Settings()
print('Supabase URL:', settings.supabase_url)
print('Anon key prefix:', settings.supabase_anon_key[:30] + '...')

# Test sign-in
url = settings.supabase_url + '/auth/v1/token?grant_type=password'
headers = {'apikey': settings.supabase_anon_key, 'Content-Type': 'application/json'}
data = {'email': 'test@example.com', 'password': 'testpassword123'}
r = requests.post(url, headers=headers, json=data)
print('Status:', r.status_code)
resp = r.json()
if r.status_code == 200:
    print('SUCCESS: Got session token')
    print('User:', resp.get('user', {}).get('email'))
else:
    print('Error:', resp.get('error_description') or resp.get('msg') or resp.get('message') or 'unknown')

# Also test the anon key directly
print('\n--- Testing anon key directly ---')
r2 = requests.get(settings.supabase_url + '/rest/v1/users?limit=1', headers={
    'apikey': settings.supabase_anon_key,
    'Authorization': 'Bearer ' + settings.supabase_anon_key
})
print('Status:', r2.status_code)
print('Response:', r2.text[:200] if r2.text else 'empty')
