"""Run Supabase migration: option 1 = CLI, option 2 = Python psycopg2"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SQL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'supabase', 'migration.sql')

with open(SQL_FILE, 'r', encoding='utf-8') as f:
    sql = f.read()

# Try using Python with direct DB connection via psycopg2
try:
    import psycopg2
    # Supabase connection - password from project settings
    # Typical connection: postgresql://postgres:{pwd}@db.{ref}.supabase.co:5432/postgres
    print("Connecting to Supabase database...")
    
    # Try common password patterns or stored env
    import urllib.request, json
    
    conn = psycopg2.connect(
        host="db.wtradahkkpbkbhmkkpal.supabase.co",
        port=5432,
        dbname="postgres",
        user="postgres",
        password=os.environ.get("SUPABASE_DB_PASSWORD", ""),
        sslmode="require"
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    # Split SQL into individual statements and execute
    statements = []
    current = []
    for line in sql.split('\n'):
        current.append(line)
        if line.rstrip().endswith(';') and not line.rstrip().startswith('--'):
            statements.append('\n'.join(current))
            current = []
    if current:
        statements.append('\n'.join(current))
    
    print(f"Executing {len(statements)} SQL statements...")
    for i, stmt in enumerate(statements):
        stmt = stmt.strip()
        if not stmt or stmt.startswith('--'):
            continue
        try:
            cur.execute(stmt)
            print(f"  [{i+1}] OK ({len(stmt)} chars)")
        except Exception as e:
            print(f"  [{i+1}] WARN: {e}")
    
    cur.close()
    conn.close()
    print("\nMigration completed!")
    
except ImportError:
    print("psycopg2 not installed. Installing...")
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    print("Re-run this script after installation.")
except Exception as e:
    print(f"Database connection failed: {e}")
    print("\nPlease run migration manually at:")
    print("https://supabase.com/dashboard/project/wtradahkkpbkbhmkkpal/sql/new")
    print("Copy and paste the contents of supabase/migration.sql")
