import httpx, json

key = '50ac65ec-f58e-4af1-889c-0f415c097e91'

# Test 1: Profile scraper (sync, up to 20 URLs)
print("=" * 60)
print("TEST 1: LinkedIn Profile Scraper")
print("=" * 60)
r = httpx.post(
    'https://api.brightdata.com/datasets/v3/scrape',
    params={'dataset_id': 'gd_l1viktl72bvl7bjuj0', 'format': 'json', 'include_errors': 'true'},
    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
    json=[{'url': 'https://www.linkedin.com/in/satyanadella'}],
    timeout=120
)
print('Status:', r.status_code)
data = json.loads(r.text)
if data and isinstance(data[0], dict) and 'name' in data[0]:
    p = data[0]
    print('Name:', p.get('name'))
    print('City:', p.get('city'))
    print('Country:', p.get('country_code'))
    print('Position:', p.get('position'))
    posts = p.get('posts', [])
    print('Posts attached:', len(posts))
    for i, post in enumerate(posts[:3]):
        print(f"  Post {i+1}: {post.get('title', 'N/A')[:80]}")
        print(f"    Link: {post.get('link', 'N/A')}")
        print(f"    Date: {post.get('created_at', 'N/A')}")
        print(f"    Interaction: {post.get('interaction', 'N/A')}")
else:
    print('Raw:', r.text[:500])

# Test 2: Multiple profiles in one request
print()
print("=" * 60)
print("TEST 2: Multiple Profiles (batch)")
print("=" * 60)
r2 = httpx.post(
    'https://api.brightdata.com/datasets/v3/scrape',
    params={'dataset_id': 'gd_l1viktl72bvl7bjuj0', 'format': 'json', 'include_errors': 'true'},
    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
    json=[
        {'url': 'https://www.linkedin.com/in/satyanadella'},
        {'url': 'https://www.linkedin.com/in/jeffweiner08'},
    ],
    timeout=120
)
print('Status:', r2.status_code)
data2 = json.loads(r2.text)
for p in data2:
    if 'name' in p:
        print(f"  {p.get('name')} | {p.get('city')} | {p.get('country_code')} | posts: {len(p.get('posts', []))}")
    elif 'error' in p:
        print(f"  ERROR: {p.get('error')}")
    else:
        print(f"  Unknown: {str(p)[:100]}")
