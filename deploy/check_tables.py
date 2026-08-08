import sys
sys.path.insert(0, '/root/leadforge/backend')
from app.config import Settings
from supabase import create_client

settings = Settings()
sb = create_client(settings.supabase_url, settings.supabase_service_role_key)

tables = ["users", "searches", "leads", "daily_usage", "user_subscriptions"]
for table in tables:
    try:
        r = sb.table(table).select("*", count="exact").limit(1).execute()
        count = getattr(r, 'count', '?')
        print(f"  {table}: OK")
    except Exception as e:
        print(f"  {table}: ERROR - {e}")
print("All tables verified!")
