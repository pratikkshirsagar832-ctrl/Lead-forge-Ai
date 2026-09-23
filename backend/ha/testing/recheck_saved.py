"""Report which already-saved LinkedIn leads are deleted or already filled.

REPORT ONLY - nothing is modified or deleted. Leads saved before the
liveness check existed can point at posts their authors have since deleted
("Post not found"); this lists them so a decision can be made separately.

    cd backend && python ha/testing/recheck_saved.py [--limit 200] [--user <uuid>]
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from liveness import check_post, is_filled  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--user", default="", help="only this user's leads")
    args = ap.parse_args()

    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    q = client.table("ha_leads").select("id,post_url,user_id,created_at").order("created_at", desc=True)
    if args.user:
        q = q.eq("user_id", args.user)
    rows = q.limit(args.limit).execute().data or []

    with ThreadPoolExecutor(max_workers=6) as ex:
        checks = list(ex.map(lambda r: check_post(r["post_url"]), rows))

    counts = {"alive": 0, "dead": 0, "filled": 0, "unknown": 0}
    for row, chk in zip(rows, checks):
        state = "filled" if chk.status == "alive" and is_filled(chk.text) else chk.status
        counts[state] += 1
        if state != "alive":
            print(f"{state:8} {row['id']}  {row['post_url']}")
    print(f"\nchecked {len(rows)}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
