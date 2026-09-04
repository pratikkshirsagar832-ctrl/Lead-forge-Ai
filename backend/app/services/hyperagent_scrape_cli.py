#!/usr/bin/env python
"""HyperAgent LinkedIn Scraper — standalone CLI.

Runs INSIDE the browser-use venv (which has browser_use but not supabase).
Reads JSON from stdin:
  {"queries":[...], "kind":"post|job|people", "cookies_json":"...", "location":"",
   "max_per_query":15, "headless":true, "proxy":"", "agent":true,
   "service":"...", "lead_type":"...", "country":"...", "count":5}
Writes JSON to stdout: {"ok":n, "total":n, "items":[...], "errors":[]}

When "agent":true, the genuine autonomous HyperAgent (DeepSeek brain + browser-use
hands via the Agent class + the HyperAgent LinkedIn system prompt) performs the
search and returns parsed lead items. Otherwise it falls back to deterministic
DOM/text extraction.

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


async def _run_agent(req: dict) -> list[dict]:
    """Run the autonomous HyperAgent (browser-use Agent + DeepSeek + system prompt)."""
    from app.services.hyperagent_agent import (
        LINKEDIN_AGENT_SYSTEM_PROMPT,
        build_linkedin_task,
        parse_agent_result,
    )
    from app.config import Settings
    from browser_use import BrowserProfile
    from browser_use.browser.session import BrowserSession
    from browser_use.agent.service import Agent
    from browser_use.llm.deepseek.chat import ChatDeepSeek

    s = Settings()
    query = (req.get("queries") or [""])[0] or (req.get("service") or "")
    service = req.get("service") or query or "service"
    lead_type = req.get("lead_type") or "freelancer_needed"
    country = req.get("country") or ""
    count = int(req.get("count") or req.get("max_per_query") or 5)
    cookies_json = req.get("cookies_json") or ""
    proxy = req.get("proxy") or ""
    headless = bool(req.get("headless", True))

    from app.services.hyperagent_browser import _normalize_cookie, _build_proxy_settings
    raw = json.loads(cookies_json) if cookies_json else []
    raw = raw if isinstance(raw, list) else (raw or {}).get("cookies", [])
    sstate = {"cookies": [_normalize_cookie(c) for c in raw if isinstance(c, dict)], "origins": []}
    bp = BrowserProfile(headless=headless, allowed_domains=["www.linkedin.com"],
                        storage_state=sstate, proxy=_build_proxy_settings(proxy))

    llm = ChatDeepSeek(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url,
                       model=s.deepseek_model, thinking=False)
    browser = BrowserSession(browser_profile=bp)
    await browser.start()
    try:
        task = build_linkedin_task(service, lead_type, country, count, query)
        agent = Agent(task=task, llm=llm, browser=browser,
                      override_system_message=LINKEDIN_AGENT_SYSTEM_PROMPT,
                      use_vision=False, flash_mode=True, max_steps=14, loop_detection_enabled=False)
        history = await agent.run(max_steps=14)
        final = history.final_result() or ""
        if "LOGIN_WALL" in final:
            raise RuntimeError("LinkedIn login wall (datacenter IP flagged — needs residential proxy)")
        return parse_agent_result(final)
    finally:
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass


async def _scrape(req: dict) -> dict:
    queries = req.get("queries", [])
    kind = req.get("kind", "post")
    cookies_json = req.get("cookies_json", "")
    location = req.get("location", "")
    max_per = int(req.get("max_per_query", 15))
    headless = bool(req.get("headless", True))
    proxy = req.get("proxy", "")

    ok, errors, items = 0, [], []
    if not queries and not req.get("enrich_urls") and not req.get("agent"):
        return {"ok": 0, "total": 0, "items": [], "errors": ["no_queries"]}

    # Mode: genuine autonomous HyperAgent (DeepSeek + browser-use Agent).
    if req.get("agent"):
        if not cookies_json:
            return {"ok": 0, "total": 1, "items": [], "errors": ["no_cookies"]}
        try:
            items = await _run_agent(req)
            return {"ok": 1 if items else 0, "total": 1, "items": items, "errors": errors}
        except Exception as exc:  # noqa: BLE001
            return {"ok": 0, "total": 1, "items": [], "errors": [f"agent: {str(exc)[:200]}"]}

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
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
