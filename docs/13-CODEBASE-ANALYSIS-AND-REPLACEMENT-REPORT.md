# Hyperclients (Lead-Forge-Ai) — Verified Codebase Analysis & Harvest→Our-Scraper Replacement Report

> Status: **static analysis of this repo snapshot** (frontend + backend + supabase + deploy), cross-checked by three independent deep-dive agents and direct file reads. Nothing in this report was produced by running the production stack. Items marked **[needs live check]** must be verified against the running production database / VPS before acting on them.
>
> Product: **Hyperclients** v2.2.0 — lead discovery & AI qualification SaaS (LinkedIn + Google Maps), live at `hyperclients.online`. Monorepo root: `F:\Lead-Forge-Ai`.

---

## 1. Executive summary

1. **What the SaaS is.** A user types `niche` + `location` + `lead_type` (buyer / hiring / agency_wanted); the backend finds **LinkedIn posts matching those keywords** (today via the **paid `harvestapi~linkedin-post-search`** Apify actor), AI-scores the post *authors*, applies a hard country gate and quality tiers, and saves the accepted people as **leads** (one row per author, holding that author's single "best post": `post_url`, `post_text`, `posted_at`, `post_type`). A second, cookie-based flow ("HyperAgent") does the same discovery with a logged-in LinkedIn browser session + DeepSeek. Google Maps is a parallel legacy source.

2. **Where harvest is actually called (verified).** Exactly **one live call site** in the whole app:
   - `backend/app/services/linkedin_pipeline.py:1093-1115` `_discover()` → `apify_service.run_lane_search()` (`apify_service.py:387-423`) → actor **`harvestapi~linkedin-post-search`** (`apify_service.py:341`) via `_run_sync_actor()` → `POST https://api.apify.com/v2/acts/{id}/run-sync-get-dataset-items?token=…&timeout=300`.
   - Every other harvest wrapper has **no active caller** (see §6): `run_post_search`, `run_harvest_post_search`, `run_job_search`, `enrich_profiles`, `fetch_profile_details` (its only call site sits in a dead no-op `_enrich_profiles_for`, `linkedin_pipeline.py:1046-1051`).

3. **Replacement verdict (hard technical fact, not opinion).**
   - **`harvestapi~linkedin-post-search` is a keyword search.** Input: `searchQueries: ["website development"]`. It searches all of LinkedIn and returns *other people's* posts whose text matches.
   - **Our `linkedin-post-scraper` actor is a profile extractor.** Input: `profileUrls: ["https://www.linkedin.com/in/…"]`. It returns *that profile's own public post history*. It has **no LinkedIn search capability** and, by design (public pages only, no login), cannot discover "posts about a keyword from unknown authors".
   - Therefore **it cannot be dropped into `_discover()` as a like-for-like substitute**. Replacing harvest *means changing the product's discovery model* from **keyword → profile-driven** (user supplies the profile URLs, or the system harvests posts from profiles it already knows). That is implementable — §8 specifies exactly how — but it changes the "LinkedIn Posts" search UX and what a "search" returns.
   - Secondary limitation: the actor fetches LinkedIn directly and is **blocked from datacenter IPs** (HTTP 999 / CAPTCHA — proven on the Apify cloud in this project's own run history; it returns `FORBIDDEN`/`CAPTCHA_OR_CHALLENGE` honestly). Running it from the Contabo VPS may hit the same wall **[needs live check: VPS IP vs LinkedIn]**. This report and the proposed code keep **honest classification** — no proxy/evasion is added to defeat LinkedIn's block.

4. **Broken / stale code — headline list** (full inventory in §7). This supports the "30–40% of the code is broken/stale" observation, with evidence:
   - **`Hyper_Agent/` folder is missing from the repo**, but `backend/Dockerfile` does `COPY Hyper_Agent/browser-use/…`, `backend/.dockerignore` references `Hyper_Agent/*`, and `app/routers/hyperagent.py` + `app/services/hyperagent_engine.py` do `import hyperagent.*` (top-level package). ⇒ **`docker compose build backend` cannot succeed from this snapshot**, and importing `app.main` locally fails unless that package exists in the environment. **[needs live check: the VPS copy of the repo probably still has the folder]**
   - `backend/supabase/supabase-schema.sql` is a **stale local-dev schema** (own `users` table, missing ~10 tables and dozens of columns the code already uses).
   - `searches.status` is created with `CHECK (status IN ('queued','scraping','analyzing','completed','failed','cancelled'))` (`supabase/migration.sql:78-79`), but `hyperagent_engine.py:137` writes **`'waiting'`**; no migration ever adds it ⇒ update would be rejected unless the live constraint differs. **[needs live check]**
   - Engagement counts are fetched from actors then **silently discarded**: `_parse_candidate` builds `engagement_likes/comments`, `_save_leads`' insert payload (`linkedin_pipeline.py:1005-1016`) omits them (the dropped `linkedin_leads` table used to have these columns).
   - Docs are badly drifted (README/docs claim 7 tables, wrong line counts, stale schemas) — treat `.sql` files as truth.
   - Orphaned frontend page `/dashboard/hyperagent` (exists, not in the Sidebar nav; Sidebar's "HyperAgent" points to `/dashboard/agent`).
   - `app/schemas/user.py` unused; several `deploy/*.py` scripts overlap; nested `backend/linkedin-post-scraper` git repo duplicates the actor source (version 0.1 vs deployed 0.1.3) and carries `node_modules/` + `dist/`.

---

## 2. Repository layout (verified)

```
F:\Lead-Forge-Ai\
├── backend/                FastAPI app (Python 3.12)  ← harvest usage lives here
│   ├── app/                main.py, config.py, database.py
│   │   ├── routers/        auth, search, leads, ai, dashboard, subscriptions,
│   │   │                   agent, agent_conversation, hyperagent
│   │   ├── services/       pipeline, linkedin_pipeline (1419 L), apify_service (632 L),
│   │   │                   hyperagent_*, analyzer_service, ai_service, usage, plans, scraper_service
│   │   ├── middleware/      auth_middleware (Bearer JWT), usage_middleware (daily search limit)
│   │   ├── schemas/        lead.py, search.py, user.py
│   │   └── utils/helpers.py
│   ├── google-maps-scraper/  Go scraper (separate local Postgres)
│   ├── Scrapling/          vendored scraping lib
│   ├── linkedin-post-scraper/  ← our Apify actor source (copy; version 0.1, stale vs deployed 0.1.3)
│   ├── Hyper_Agent/        *** MISSING in this snapshot *** (Dockerfile/.dockerignore/imports need it)
│   ├── scripts/, tools/, sessions/, supabase/, tests/   (pytest suite exists)
│   ├── .env                production-grade secrets (ENVIRONMENT=production)
│   └── Dockerfile          multi-stage (Go + Python + browser-use venv)
├── frontend/               Next.js 16 App Router + Tailwind v4 + axios + zustand
├── supabase/               migration*.sql (the real schema source of truth)
├── deploy/                 ~19 overlapping python deploy scripts
├── docs/                   docs 01–12 (+ this file)
├── docker-compose.yml      prod topology (backend :8000, frontend :3001, env_file backend/.env)
├── audit_posts.py, e2e_search.py   dev scripts hitting the live prod Supabase
└── README.md               partially stale
```

---

## 3. Backend map (verified)

**Entry**: `app/main.py` → `create_app()`; all routers included with their own prefixes; lifespan marks `searches` stuck >15 min in `queued|scraping|analyzing` as `failed`. Settings: pydantic-settings reading `.env` (`app/config.py`). DB: Supabase python client, service-role admin client cached in `app/database.py` (`get_supabase_admin()` everywhere). Logging: stdlib `logging`.

| Router | Prefix | Key endpoints | Notes |
|---|---|---|---|
| `auth.py` | `/api/auth` | GET/POST/DELETE `/team`, `POST /team-resolve`, `GET /me` | Bearer JWT via `get_current_user`; team encoded as `razorpay_order_id="team:{owner}:{name}"` |
| `search.py` | `/api/searches` | POST `` (201, job), GET `` history, GET `/{id}`, `/{id}/status`, `/{id}/results`, POST `/{id}/cancel`, `/{id}/load-more` | **The universal job pattern**: insert `searches` row `status=queued` + `reserved_leads`/`quota_source`, then `background_tasks.add_task(...)`, client polls `status` every ~2 s. LinkedIn source → `run_linkedin_pipeline_fast` (harvest keyword engine); gmaps → `run_search_pipeline` |
| `leads.py` | `/api/leads` | GET list/export, GET `/{id}`, PATCH `/{id}/status|notes|favorite`, POST `/{id}/analyze-website` | Lead filters incl. `post_type`, `source`; CSV export gated Pro/Agency; ownership mismatch → 404 |
| `ai.py` | `/api/ai` | POST `/pitch/{lead_id}`, `/website-message/{lead_id}` | inline daily AI-call cap |
| `dashboard.py` | `/api/dashboard` | GET `/stats` | RPC `get_dashboard_stats` |
| `subscriptions.py` | `/api/subscriptions` | plans, current, create-order, verify, cancel, webhook | Razorpay HMAC webhook (public) |
| `agent.py` + `agent_conversation.py` | `/api/agent` | POST/GET `/runs…`, GET `/chat`, POST `/chat` | guided chat state machine (`agent_chat_state`), then launches a `searches` job (`source="hyper_agent"`) |
| `hyperagent.py` | `/api/hyperagent` | POST `/runs`, GET `/runs/{id}/status|results`, session connect/status/delete, drafts approve/reject | browser-use + DeepSeek "Prime Agent"; **imports top-level `hyperagent` package** |

**Service patterns**: module-level functions; blocking Supabase calls wrapped in `await asyncio.to_thread(...)`; FastAPI `BackgroundTasks` for jobs (single worker, `--workers 1`); status lives in the DB `searches` row (`status, progress_percent, message, total_results, hot_leads, warm_leads, error_message, completed_at, quota_source, reserved_leads, quota_settled_at`); monthly quota in `monthly_usage` (`linkedin_hq_*` / `gmb_*`) settled by `usage.settle_search_quota` / SQL functions.

---

## 4. Frontend map (verified)

- **Stack**: Next.js 16 App Router, React 18, TS strict, Tailwind v4; axios only (no react-query). One axios client `src/lib/api.ts` with Supabase Bearer injection + 401 auto-refresh; **proxy**: `next.config.mjs` rewrites `/api/*` (except `admin/|tools/`) → backend ⇒ **new backend endpoints under `/api/...` need no frontend proxy change**.
- **Job polling pattern to copy**: `src/hooks/useSearch.ts` + `src/stores/searchStore.ts` — POST job → poll `GET /status` every 2 s until terminal → fetch `results`; `SearchProgressCard.tsx` renders progress. Agent/hyperagent pages duplicate simpler variants (2.5 s intervals).
- **Lead detail page** `src/app/dashboard/leads/[id]/page.tsx` renders the single LinkedIn post block (`post_url/post_text/posted_at/post_type`) — natural anchor for per-profile post lists.
- Types centralized in `src/lib/types.ts` (snake_case mirrors backend), routes registry `src/lib/constants.ts` (`API_ROUTES`), toasts via zustand `useToast`.
- **Orphan**: `src/app/dashboard/hyperagent/page.tsx` exists but Sidebar (`components/dashboard/Sidebar.tsx`) lists only `/dashboard/agent` as "HyperAgent".

---

## 5. Supabase real schema (verified from migrations, applied in order)

`migration.sql` → `migration_linkedin.sql` → `_v2` → `_v3` → `_v4` → `production_v5` → `engine_v6` → `agent_v7` → `migration_hyperagent.sql`.

- **`searches`** — unified job row for gmaps + linkedin + hyper_agent. `source` runtime values `google_maps|linkedin|hyper_agent` (no CHECK); `status` CHECK lacks `waiting` (see §7); v2 `enrich_emails/max_results/emails_found`; v4 `lead_types TEXT[]` + GIN; v5 `quota_source CHECK('linkedin','google_maps'), reserved_leads, quota_settled_at`.
- **`leads`** — one row per accepted author; LinkedIn columns folded in v2 (`source, linkedin_url, post_url, post_text, headline, profile_picture_url, connections_count, posted_at`), v3/v5/v6 `post_type` (constraint saga: `leads_post_type_check` dropped/recreated across versions — final values `buyer|agency|agency_wanted|hiring|job_seeker|unknown`), v4 AI columns (`ai_qualified, ai_confidence, ai_reason`) + `ai_confidence_score, ai_pitch` elsewhere. **No engagement columns. No unique(user_id, linkedin_url); dedupe is app-side.**
- **`plans`, `user_subscriptions`, `daily_usage`, `monthly_usage`** — quota/plan machinery (v5 RPCs `reserve_monthly_leads`, `settle_*`).
- **HyperAgent family** (`migration_hyperagent.sql`): `research_runs, lead_candidates, message_drafts, agent_events, usage_metrics, linkedin_sessions` — note `search_id TEXT` (not UUID), `lead_candidates` has the closest existing "post evidence" shape (`post_url, profile_url, author_name, author_headline, post_text, posted_at, …`). `agent_chat_state`, `agent_services` (v7) created **without RLS**.
- **RLS convention**: per-user `user_id` isolation; child tables inherit through parent via `EXISTS` (pattern: `website_analyses`).
- **Dropped tables** (do NOT recreate): `linkedin_searches`, `linkedin_leads` (v2) — the old `linkedin_leads` **had** `engagement_likes/engagement_comments`; that is the precedent for new post/engagement storage.

---

## 6. Apify usage inventory (verified, file:line)

| Actor | Wrapper (file:line) | Purpose | Live caller today? |
|---|---|---|---|
| `harvestapi~linkedin-post-search` | `run_lane_search` `apify_service.py:387`; const `:341` | **Keyword post search** (discovery lanes) | ✅ **YES** — `_discover` `linkedin_pipeline.py:1093-1115` → engine → `POST /api/searches` (source `linkedin`) |
| `scrapeforge~linkedin-all-in-one` | `run_post_search` `:276` (fallback), `fetch_profile_details` `:564`, `_run_post_search_chunk` `:535` | Post search fallback / profile-detail enrichment | ❌ no active callers (profile-detail call site inside dead `_enrich_profiles_for`) |
| `harvestapi~linkedin-profile-scraper` | `enrich_profiles` `:587` | Email enrichment | ❌ no callers |
| `shahidirfan~linkedin-job-scraper` | `run_job_search` `:603` | Jobs (hiring mode) | ❌ no callers in app code |
| key health | `check_apify_keys_health` `:143` | GET /v2/users/me per key | router `/api/searches/scraper-health`? (wired to gmaps binary check; Apify health not exposed) |

All runs share one engine: `_run_sync_actor(actor_id, payload)` → 24-key rotation, 600 s cooldown, permanent blacklist on revoked tokens (`apify_service.py:182-244`).

**Our actor** `linkedin-post-scraper` (id `2nZ0rjo0R3O4fzBy3`, user `handwoven_gharial_c6y`; deployed build 0.1.3): input `{profileUrls[], postUrls[], maxPostsPerProfile 1-50, includeEngagement, includeAuthor, maxConcurrency, requestTimeoutSecs, useBrowser}`; output records `{postUrl, postId, text, authorName, authorUrl, authorType, authorHeadline, datePosted, relativeDate, numLikes/numComments/numShares, hashtags, mentions, media, sourceUrl, extractionMethod, extractedAt, extractionStatus(success|partial|failed|unresolved), qualityScore}`. Public-pages only; access restrictions classified honestly (FORBIDDEN / CAPTCHA_OR_CHALLENGE / RATE_LIMITED …). **Private actor**: runnable only with the owner Apify token (`apify_api_eKWs…21i`, account `handwoven_gharial_c6y`), *not* the SaaS key currently in `backend/.env` (`…gF1`).

---

## 7. Broken / stale code inventory (evidence)

> Severity: 🔴 breaks build/run · 🟠 data or prod drift · 🟡 dead/stale/docs.

1. 🔴 **`Hyper_Agent/` missing but required.** `backend/Dockerfile`: `COPY Hyper_Agent/browser-use/ /app/Hyper_Agent/browser-use/` then builds its venv; `backend/.dockerignore` lists `Hyper_Agent/browser-use/*` + `Hyper_Agent/prime-agent/`; `app/routers/hyperagent.py:23-26` and `app/services/hyperagent_engine.py:21-23` `import hyperagent.{approval,linkedin_session,models,security,bridge}`. The directory exists nowhere under `F:\Lead-Forge-Ai` (searched). ⇒ `docker compose build backend` fails from this snapshot; `uvicorn app.main` also fails locally unless `hyperagent` is importable from the environment. **[needs live check: VPS copy]**
2. 🟠 **`searches.status` CHECK vs written values.** CHECK `migration.sql:78-79` = `queued|scraping|analyzing|completed|failed|cancelled`; `hyperagent_engine.py:137` writes `'waiting'` (no migration adds it). Update would be rejected unless live constraint was altered. **[needs live check]**
3. 🟠 **Engagement discarded.** `_parse_candidate` computes engagement; `_save_leads` payload (`linkedin_pipeline.py:1005-1016`) never inserts it; no engagement columns exist in `leads`.
4. 🟡 **Dead enrichment hook.** `_enrich_profiles_for` (`linkedin_pipeline.py:1046-1051`) returns immediately (kept "for compatibility"); the only `fetch_profile_details` call site.
5. 🟡 **Dead Apify wrappers** (§6) — `run_post_search`, `run_job_search`, `enrich_profiles`, `run_harvest_post_search` have no callers (cost nothing at runtime, but signal unfinished refactors).
6. 🟠 **Stale schema files.** `backend/supabase/supabase-schema.sql` predates the unified flow; `docs/06`, `README.md` table/line inventories are wrong. SQL migrations in `supabase/` are the only reliable source of truth.
7. 🟡 **Orphan page** `/dashboard/hyperagent` not in Sidebar (`frontend/src/components/dashboard/Sidebar.tsx`); Sidebar "HyperAgent" → `/dashboard/agent`.
8. 🟡 **Unused code**: `app/schemas/user.py` (no router imports it); many helpers in `utils/helpers.py` unused.
9. 🟡 **Deploy script sprawl** — `deploy/` holds ~19 overlapping python scripts (`deploy.py`, `full_deploy.py`, `final_deploy.py`, `direct_deploy.py`, `fix_*.py`, `check_*.py`…).
10. 🟡 **Duplicate actor repo** — `backend/linkedin-post-scraper/` is a nested git repo (own `.git`, `node_modules/`, `dist/`) with actor.json `version 0.1` (deployed is 0.1.3). The Dockerfile reference in its `.actor/actor.json` (`"../Dockerfile"`) only resolves inside its own context; it is **not** wired into the backend image.
11. 🟠 **HyperAgent tables without RLS** — `agent_chat_state`, `agent_services` (migration_agent_v7.sql) have no RLS (service-role writes assumed; risky if anon key is ever exposed).
12. 🟡 **Dev scripts hitting prod** — `audit_posts.py` (hard-coded search id) and `e2e_search.py` (creates admin users + writes) read prod Supabase service-role from `.env`. Useful, but no gating/flag.
13. 🟡 **Frontend polling duplication** — agent + hyperagent pages hand-roll polling loops instead of reusing the `useSearch` pattern.
14. 🟡 **Docs drift / line-count claims** (README says `linkedin_pipeline.py` 2,540 lines; actual 1,419).
15. 🟡 **Root API root claims** `docs_url` disabled in production — fine; note only.

**Not investigated** (needs live access): which of the above differ on the production VPS copy; actual prod Supabase constraints (esp. `status`, `post_type`); whether the VPS IP can reach LinkedIn logged-out; current pytest status against the *current* code (tests exist under `backend/tests/`).

---

## 8. Harvest → our-scraper replacement: feasibility + recommended path

### 8.1 What cannot be done (be clear with stakeholders)
- Our actor **cannot search LinkedIn by keyword**, so it cannot feed `_discover()` the way `harvestapi~linkedin-post-search` does. Any plan that keeps the current UX ("type niche → get unknown authors' posts") **must keep a search-capable provider** (harvest, or another Apify store actor, or the cookie-based HyperAgent browser search which the SaaS already runs logged-in).
- Our actor **cannot be made to bypass LinkedIn's datacenter block** in this project's compliance model (no proxy/evasion — honest classification only). If the VPS IP is blocked **[needs live check]**, per-profile fetches from the server return honest `FORBIDDEN` and 0 posts.

### 8.2 What CAN replace harvest spend genuinely
The SaaS already owns `linkedin_url` for every LinkedIn lead and `lead_candidates.profile_url` in the hyperagent flow. Our actor's output maps 1:1 onto the fields the product keeps throwing away or buying elsewhere:

- **Replace the paid per-profile enrichment** (`fetch_profile_details`/`enrich_profiles` — currently unused/dead) with our actor: for a profile URL it returns author name/headline + **real post history with engagement** (engagement is currently computed-then-discarded, §7.3).
- **New product capability (recommended): "profile → full public post history"** stored in a new table (precedent: old `linkedin_leads` columns `engagement_likes/engagement_comments`; RLS via the `website_analyses` EXISTS-through-parent pattern), surfaced on the lead detail page and/or a standalone "Profile Posts" tool. This gives pitch-generation and qualification real evidence and is the only honest "use our scraper instead of paid harvest data" path.
- **Optional pivot (bigger change): profile-driven discovery.** If the product moves to "the user pastes prospect profile URLs / imports from their network", `_discover()` is swapped for our actor (1 profile → its posts → author becomes a lead with post history). This is a real replacement of harvest keyword search, but it changes the `POST /api/searches` input contract, the `/dashboard/search` UI, and lead semantics (one profile = one lead + N evidence posts). Needs product sign-off before touching the engine.

### 8.3 Recommended implementation shape (for whichever path is approved)
- New backend service `app/services/post_scraper_service.py` (mirroring `apify_service` style): constant `POST_SCRAPER_ACTOR = "handwoven_gharial_c6y/linkedin-post-scraper"` (id `2nZ0rjo0R3O4fzBy3`); dedicated env token (`APIFY_POST_SCRAPER_TOKEN`, owned by `handwoven_gharial_c6y`) with fallback to the existing key rotation; payload `{profileUrls, maxPostsPerProfile, includeEngagement, includeAuthor}`; normalize dataset records to a stable schema.
- New migration `supabase/migration_post_scraper.sql`: `lead_posts` table (`id uuid PK`, `user_id` FK CASCADE, `lead_id` FK → `leads` nullable, `profile_url`, `post_url`, `post_id`, `post_text`, `author_name`, `author_headline`, `author_type`, `posted_at`, `num_likes/comments/shares`, `hashtags`, `mentions`, `media`, `extraction_status`, `raw` JSONB, `created_at`), idempotent, RLS isolation.
- Endpoints mirroring house style (job row + BackgroundTasks + status polling) or synchronous (axios timeout is 5.5 min) for small batches.
- Frontend: extend `LeadDetail` + `src/app/dashboard/leads/[id]/page.tsx` with a "All posts by this profile" section calling the new endpoint (auto-proxied), types in `src/lib/types.ts`, route in `API_ROUTES`.

### 8.4 Decisions captured from the owner
- Apify access: **add the owner token** (`handwoven_gharial_c6y` / `apify_api_eKWs…21i`) to the SaaS backend env for this actor (actor stays private). [token already shared earlier — rotate if worried]
- Deployment: owner authorized **deploy to the production VPS** after code is ready (deployment will be done explicitly, with SSH go-ahead, and only after local verification).
- Compliance: keep honest classification; **no proxy/evasion** to bypass LinkedIn blocks.

---

## 10. Implementation delivered (this session)

Owner direction (Rasta C): **LinkedIn keyword discovery moves to the cookie-based HyperAgent; the harvest-powered "LinkedIn Posts" option is removed from the New Search tab.** The in-house public post-scraper actor is integrated as the *extraction/verification* layer (profile URLs + post URLs → clean public records).

Backend (`backend/app/`):
- `config.py` — new settings `apify_post_scraper_actor_id` (default `2nZ0rjo0R3O4fzBy3`) and `apify_post_scraper_token` (owner token for the private actor; empty → shared rotation).
- `services/post_scraper_service.py` (new) — actor payload builder, honest runner (owner token first, shared rotation fallback), record normaliser (maps actor `PostRecord` → DB row, caps text at 3000), per-profile summary (success/partial/failed/unresolved), persistence with in-batch + stored dedupe, paginated listing.
- `schemas/post.py` (new) — pydantic request/response models (LinkedIn-URL validation).
- `routers/posts.py` (new) — `POST /api/posts/scrape`, `GET /api/posts`, plus `GET /api/leads/{lead_id}/posts` (registered via `register_lead_posts_endpoint`).
- `main.py` — router registered.

Database: `supabase/migration_post_scraper.sql` (new, idempotent) — `profile_posts` table + RLS + unique(user_id, post_url) partial index. **Not yet applied to production** — apply in the Supabase SQL Editor when ready.

Frontend (`frontend/src/`):
- `app/dashboard/search/page.tsx` — "LinkedIn Posts" source option **removed** from New Search; Google Maps only + a banner pointing LinkedIn discovery to HyperAgent (`/dashboard/agent`); dead `?source=linkedin` deep-link activation removed.
- Fixed two pre-existing build-blocking bugs: unbalanced JSX in `app/dashboard/agent/page.tsx` (missing `</div>`s from an uncommitted full-width refactor) and a `string | undefined` type error in `app/dashboard/hyperagent/page.tsx`.

Verification: `tsc --noEmit` clean (exit 0); backend `py_compile` clean; new tests `tests/test_post_scraper_service.py` 9/9 and `test_apify_rotation.py`+new 18/18 pass. Note: Turbopack `next build` is broken on this Windows box (native binding not a valid Win32 app — environment issue, not code); `next build --webpack` is the local validation path and production builds on the Linux VPS are unaffected.

**Not done / pending owner decision:** applying the SQL migration to prod; adding `APIFY_POST_SCRAPER_TOKEN` to `backend/.env`; deploying to the VPS (SSH go-ahead needed); frontend UI section on the lead page to render stored posts; and the HyperAgent cookie-connect UX improvements.

## 9. Open items before building/deploying

1. **[needs live check]** Confirm whether `Hyper_Agent/` exists in the VPS repo copy (it must, for the current image to have built).
2. **[needs live check]** Query live Supabase for `searches.status` / `leads.post_type` constraint values and existing tables.
3. **[needs live check]** From the VPS, one request to a public LinkedIn profile (or one actor run) to see whether the VPS IP is served or blocked — decides whether server-side per-profile scraping can return data today.
4. Confirm the owner Apify token is added to `backend/.env` (`APIFY_POST_SCRAPER_TOKEN`) before a live actor call from the backend.
5. Owner sign-off on the discovery model: **keyword stays on harvest** (recommended for now) vs **profile-driven pivot** (§8.2).
