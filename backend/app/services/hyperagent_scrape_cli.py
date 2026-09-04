#!/usr/bin/env python
"""HyperAgent LinkedIn Scraper — standalone CLI.

Runs INSIDE the browser-use venv (which has browser_use but not supabase).
Reads JSON from stdin: {"queries":[...], "kind":"post|job|people",
"cookies_json":"...", "location":"", "max_per_query":15,
"headless":true}
Writes JSON to stdout: {"ok":n, "total":n, "items":[...], "errors":[]}

Usage:
  echo '{"queries":[...]}' | python hyperagent_scrape_cli.py
"""
import sys, json, asyncio, os

# Force UTF-8 for both stdout and stderr so emoji/unicode in scraped posts
# survive on Windows (default console codepage is cp1252/charmap).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.services.hyperagent_browser import LinkedInBrowser  # noqa: E402


async def _scrape(req: dict) -> dict:
    queries = req.get("queries", [])
    kind = req.get("kind", "post")
    cookies_json = req.get("cookies_json", "")
    location = req.get("location", "")
    max_per = int(req.get("max_per_query", 15))
    headless = bool(req.get("headless", True))
    proxy = req.get("proxy", "")

    ok, errors, items = 0, [], []
    if not queries and not req.get("enrich_urls"):
        return {"ok": 0, "total": 0, "items": [], "errors": ["no_queries"]}

    # Mode: location-enrichment only (no new search).
    enrich_urls = req.get("enrich_urls") or []
    if enrich_urls:
        async with LinkedInBrowser(headless=headless, cookies_json=cookies_json, proxy=proxy) as browser:
            locs = await browser.enrich_authors(enrich_urls, int(req.get("enrich_max", 20)))
            return {"ok": 1, "total": 1, "items": [], "errors": [], "locations": locs}

    async with LinkedInBrowser(headless=headless, cookies_json=cookies_json, proxy=proxy) as browser:
        for q in queries[:3]:
            try:
                if kind == "job":
                    batch = await browser.search_jobs(q, location, max_per)
                elif kind == "people":
                    batch = await browser.search_people(q, max_per)
                else:
                    batch = await browser.search_posts(q, max_per)
                if batch:
                    ok += 1
                    items.extend(batch)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{q}: {str(exc)[:160]}")
    return {"ok": ok, "total": min(3, max(1, len(queries))), "items": items, "errors": errors}


def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": 0, "total": 0, "items": [], "errors": [f"bad_json: {exc}"]}))
        return
    try:
        result = asyncio.run(_scrape(req))
    except Exception as exc:  # noqa: BLE001
        result = {"ok": 0, "total": 0, "items": [], "errors": [f"fatal: {str(exc)[:400]}"]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
