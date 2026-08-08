import requests, json

supabase_url = "https://wtradahkkpbkbhmkkpal.supabase.co"
service_key = "YOUR_SUPABASE_SERVICE_ROLE_KEY"
headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Type": "application/json"}

uid = "8627ce24-6bd5-48b7-9b1f-595d042bfcf6"

# Check subscription directly
r = requests.get(f"{supabase_url}/rest/v1/user_subscriptions?select=*&user_id=eq.{uid}", headers=headers)
print("Subscription:", r.status_code, json.dumps(r.json(), indent=2)[:300] if r.status_code == 200 else r.text[:200])

# Check remaining searches
r = requests.post(f"{supabase_url}/rest/v1/rpc/get_remaining_searches", headers=headers, json={"p_user_id": uid})
print("\nRemaining searches:", r.status_code, r.text[:200])

# Check daily usage
r = requests.get(f"{supabase_url}/rest/v1/daily_usage?select=*&user_id=eq.{uid}", headers=headers)
print("\nDaily usage:", r.status_code, r.text[:300] if r.text else "empty")
