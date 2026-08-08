import sys
sys.path.insert(0, '/root/leadforge/backend')
from app.config import Settings
settings = Settings()
from supabase import create_client

sb = create_client(settings.supabase_url, settings.supabase_service_role_key)
for table in ["users", "searches", "leads", "usage", "subscriptions"]:
    try:
        r = sb.table(table).select("*", count="exact").limit(1).execute()
        print(f"  {table}: OK")
    except Exception as e:
        print(f"  {table}: ERROR - {e}")
print("Done")
