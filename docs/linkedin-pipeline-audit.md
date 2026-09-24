# LinkedIn Lead Pipeline — Deep Audit Report

> **Update (Sep 2026):** discovery no longer uses Serper. LinkedIn posts now come from **SocialCrawl** (`backend/ha/discovery/socialcrawl_client.py`, one quoted buyer phrase per query, full post text + exact publish time). Serper references below describe the old pipeline.

**Date:** 2026-09-08 · **Scope:** read-only audit of the LinkedIn (Hyperagent) lead
pipeline. No code was changed to produce this report. All file references are to
`backend/` under the repo root unless prefixed otherwise.

---

## 0. Executive summary

- **The single biggest driver of wasted DeepSeek calls is Google-SERP sourcing
  itself, not any single code defect.** Across 15 logged production runs plus 2
  live test runs, `scanned` (posts sent to DeepSeek) ranges from ~1 to ~152 per
  search and `saved` from 0 to 3. DeepSeek calls per **saved** lead range from
  **7 (saas development / agency)** to **~90 (ui ux designer / freelancer)** —
  median roughly 20–30. The dominant rejection category, wherever a breakdown is
  logged, is `type_mismatch` (= DeepSeek correctly says "irrelevant"): 31–146
  posts per run reach DeepSeek and are rejected there. Google returns mostly
  sellers/job-ads/self-promotion for buyer-phrased LinkedIn queries; the code
  filters them, but the overwhelming majority of that filtering currently
  happens *after* an LLM call, not before it.

- **The current safe-baseline content gate is roughly right for precision but
  under-filters for cost.** It drops only near-certain wrong-direction content
  (employee job-ads without freelance wording; agency-recruiting-for-its-clients
  posts). The two attempts to tighten it cheaply (see §3 history) both over- or
  mis-filtered genuine leads (e.g., real buyers who also write "contact us",
  "DM me", "book a call") and were reverted. A Google-SERP-sourced pipeline has
  an inherent noise floor; the audit found no evidence the baseline silently
  drops genuine leads.

- **Dollar cost per search is small.** DeepSeek is cheap (~$0.10–0.35/search at
  the scanned volumes seen); Serper is comparable or higher per search depending
  on the plan. The "credits" a user watches are most likely **Serper query
  credits** (~30–60 requests per search), not DeepSeek dollars. Details + the
  assumption caveat in §8.

- **Incidental findings** (not fixed): stale "GPT-4o" naming in several files
  despite DeepSeek being the real provider; `hiring_buyer`/`marketplace_match`
  survive only as defensive string literals; cross-search duplicates consume a
  DeepSeek call before being skipped (`dup_owned` up to 11 in one run);
  rejected-post text and the classifier's `reason` are **never persisted**, so
  rejection quality cannot be audited after the fact. Details in §10.

---

## 1. End-to-end pipeline map (call order, per file/function)

A LinkedIn search request flows as follows:

1. **`backend/app/routers/search.py` → `create_search()`** (POST `/api/searches`).
   - Rejects non-`buyer`/`agency_wanted` lead types, maps them, reserves monthly
     quota, inserts a row into the **`searches`** table (status `queued`), then
     schedules `run_hyperagent_pipeline` via FastAPI `BackgroundTasks`.
2. **`backend/app/services/hyperagent_service.py` → `run_hyperagent_pipeline()`**
   - Builds `_ha_settings()` (injects env for the engine), creates the
     `HaSupabaseStore`, pre-creates the **`ha_searches`** row (same UUID as
     `searches.id`), and starts a **thread** → `_run_search_worker`.
3. **`_run_search_worker()`** — acquires a `threading.BoundedSemaphore(4)` engine
   slot, then calls `_run_search_worker_body()`.
4. **`_run_search_worker_body()`** builds:
   - `build_discovery(settings)` → `SerperDiscoveryClient` (`backend/ha/discovery/serp_client.py`).
   - `build_classifier(settings)` → `GptClassifier` (`backend/ha/classifier.py`).
   - wraps the store in `_ForceTypeStore(store, lead_type)` and passes
     `content_filter=lambda t: _content_matches_requested_type(t, lead_type)`.
   - then calls **`backend/ha/engine.py` → `run_search()`**.
5. **`engine.py → run_search()`** — the orchestrator loop:
   - `next_queries(service, lead_type, iteration)` (`backend/ha/query_builder.py`)
     → a set of buyer-phrase queries (each with the shared negative suffix).
   - `discovery.search_posts(queries, cutoff)` → for each query: page 1..N
     HTTP POSTs to `google.serper.dev/search`; filters to `linkedin.com/posts`
     URLs; derives `author`/`profile` from the URL slug; dedupes **within** the
     batch by `canonical_post_url`.
   - per-post loop (engine `seen_urls` dedupe → `prefilter.prefilter()` → the
     pre-LLM **content gate** `content_filter`).
   - `classifier.classify_batch(...)` → concurrent **DeepSeek** chat calls
     (system prompt + per-post JSON payload) → `LeadClassification | None`.
   - per-classified post: `compute_score(...)` (`backend/ha/scoring.py`) with
     hard gates; then `store.find_existing_post_urls(...)` (DB-level
     cross-search dedupe) before appending to `accepted`.
   - **Loop control:** if short of `leads_needed`, re-enter with `iteration+1`
     (new query slice from the pool); bounded by max iterations + wall-clock
     deadline + early stop on consecutive empty rounds (see §6).
   - Slice to exactly `leads_needed`, `store.insert_leads_many(rows)` (writes
     `ha_leads`; the `_ForceTypeStore` stamps the requested type and re-applies
     the same predicate).
6. **`hyperagent_service.py → _sync_main_search_row()`** — copies the outcome
   into the main `searches` row (status/messages/hot_warm counts) and settles
   monthly quota (`usage.py`).

**Names that don't match their location (worth knowing):**
- The "content gate" that actually matters for direction is **not in
  `prefilter.py`**; it lives as `_content_matches_requested_type` in
  `hyperagent_service.py` and is passed into the engine as a callback.
- `prefilter.py` (`prefilter()`) is a *cheap seller/job-seeker/marketplace
  pre-screen* that deliberately **keeps** any post containing a buyer phrase
  (precision doctrine) — so most noise passes it by design.
- Files/comments still say "GPT-4o" (`engine.py:5`, `classifier.py` docstring,
  `models.py` docstrings, `serp_client.py` comments) but the provider is
  DeepSeek (see §4). Stale naming only.

---

## 2. Query generation — verbatim

Module `backend/ha/query_builder.py`. Negatives **are** used at the query level:

```python
NEGATIVE_QUERY_PHRASES: tuple[str, ...] = (
    "we offer", "our services", "book a call", "dm us", "we specialize",
    "we help", "open to work", "available for hire", "join our talent network",
    "we are a leading",
)
```
Every emitted query is suffixed with these as ` -"..."` terms:
```python
def _with_negatives(query: str) -> str:
    suffix = "".join(f' -"{p}"' for p in NEGATIVE_QUERY_PHRASES)
    return query + suffix
```
`SerperDiscoveryClient._full_query` additionally appends the site + date clamp
(`backend/ha/discovery/serp_client.py:131-136`):
```python
parts = [query]
if self.site_restriction:
    parts.append(f"site:{self.site_restriction}")   # "linkedin.com/posts"
parts.append(f"after:{since.date().isoformat()}")   # fresh per request
return " ".join(parts)
```

Base templates per lead type (verbatim, `query_builder.py`):

`need_freelancer` base set (`_need_freelancer`, role-variant branch):
```python
qs = [
    f"looking for {A_role}",
    f"need {A_role}",
    f"anyone know a good {role}",
    f"need someone to help with {svc}",
]
```
where `{A_role}` is e.g. "a video editor" / "an seo specialist" derived from the
service phrase (e.g. "video editing" → role "video editor"), and `{svc}` is the
service as typed.

`our_agency` base set (`_our_agency`):
```python
qs = [
    f"looking for an agency for {svc}",
    f"need an agency for {svc}",
    f"recommendations for a {svc} agency",
    f"looking for a {svc} agency",
    f"hiring an agency for {svc}",
]
```
`build_plan()` also builds a large deterministic `pool` (raw phrasings such as
"looking for a freelance {role}", "we are looking for {A} for some work",
"need {A} with a budget", agency lanes "white label {svc} partner wanted",
"need an agency to handle {svc}", etc.). `next_queries()` returns the base set
at iteration 0, then a bounded fresh slice of the pool (≤6 queries/round) on
later iterations.

**`hiring`/`hiring_buyer` status:** no requestable `hiring` lead type exists
anywhere in the request path. `backend/ha/models.py` defines only
`need_freelancer` and `our_agency`. The DB `ha_leads`/`ha_searches` CHECK
constraints allow only those two (plus the tables were retagged by
`supabase/migration_lead_types_v9.sql`). The frontend sends only
`buyer`/`agency_wanted`. The strings `"hiring_buyer"` and `"marketplace_match"`
survive **only** as defensive fallbacks in
`backend/app/routers/search.py:433` and `backend/app/routers/leads.py:219`
(`lt in ("marketplace_match","hiring_buyer") → "buyer"`), and as a stale comment
in `backend/ha/config.py:90`. No behavior reaches them.

---

## 3. Pre-LLM content gate — verbatim + history

### 3.1 Current implementation (the safe baseline, in effect since commit `d7d15fc`)

`backend/app/services/hyperagent_service.py` — marker sets used by the gate
(markers only, all lowercase substring lists):

```python
_EMPLOYEE_HIRING = ("we are hiring", "we're hiring", "hiring:", "vacancy", "open role",
    "open position", "job opening", "position available", "salary",
    "recruiting", "headcount", "careers page", "apply now", "benefits package",
    "full-time", "full time", "part-time", "part time", "join our team",
    "join our growing team", "to join our team", "for our team")
_FREELANCER_WORDS = ("freelance", "freelancer", "freelancers", "contractor",
    "contract work", "independent contractor", "one-off project", "project basis", "gig")
_AGENCY_WORDS = ("agency", "agencies", "an agency", "agency for", "marketing agency",
    "digital agency", "creative agency", "design agency", "development agency",
    "outsource", "white label", "white-label", "a firm", "creative partner",
    "agency to handle", "for our agency", "a team of", "our partner agency",
    "looking for a team", "need a team", "hire a team")
_AGENCY_TEAM_CONTEXT = ("we need", "we are looking for", "we're looking for",
    "looking for a few", "looking for several", "we want to build",
    "help us build", "for our brand", "for our company", "for our startup",
    "for our business", "for our channel", "for our clients", "build our content",
    "video editors and", "editors and writers", "freelancers to work with")
_AGENCY_SOURCING = ("for client projects", "on client projects", "for our clients",
    "client projects", "client work", "work with our agency", "freelance bench",
    "overflow work", "white label freelancers", "white-label freelancers")
```

The predicate itself (verbatim, current):

```python
def _content_matches_requested_type(text: str, lead_type: str) -> bool:
    """Pure text gate: is this post's content compatible with the REQUESTED
    buyer direction? ... [docstring] ..."""
    low = (text or "").lower()
    if not low:
        return True
    emp_hiring = any(m in low for m in _ForceTypeStore._EMPLOYEE_HIRING)
    freelance = any(m in low for m in _ForceTypeStore._FREELANCER_WORDS)
    agency = any(m in low for m in _ForceTypeStore._AGENCY_WORDS)
    agency_sourcing = any(m in low for m in _ForceTypeStore._AGENCY_SOURCING)
    if lead_type == "need_freelancer":
        if agency_sourcing:
            return False
        if emp_hiring and not freelance:
            return False
        return True
    if lead_type == "our_agency":
        team_ctx = any(m in low for m in _ForceTypeStore._AGENCY_TEAM_CONTEXT)
        return bool(agency or team_ctx)
    return True
```

Net behavior: for **need_freelancer** it drops (a) agency-recruiting-for-its-own
clients and (b) employee job-ads **unless** freelance wording appears ("We are
hiring a freelance video editor" survives). For **our_agency** it drops pure
individual freelance asks and keeps anything referencing an agency/outside team
or team-sourcing context. Everything else — sellers, job-seekers, marketplace
posts, advice posts that contain a buyer phrase — is passed through to DeepSeek.

### 3.2 History of this gate (git log, most recent first)

| Commit | What changed (plain terms) |
|---|---|
| `a9432fa` | Introduced the gate: extracted the save-time store logic into this shared predicate and wired it into the engine as a pre-LLM `content_filter`. Baseline = rules above. Also switched model default to `deepseek-chat`, Serper pages 3→2. |
| `d3ca89e` | "Credit-saving" tightening: added two new marker sets (`_STRONG_NEGATIVES` ≈ 50 seller/job-ad/job-seeker/marketplace/thought-leadership phrases; `_STRONG_NEED` ≈ buyer-ask phrases) and dropped posts where a negative was present without a strong ask. |
| `b667c21` | Removed the `not freelance` carve-out in that rule so job-seekers/sellers that merely contain the word "freelance" were also dropped. |
| `d7d15fc` | **Reverted both** — back to the `a9432fa` baseline — after live runs showed genuine leads being dropped (e.g., buyers who wrote "contact us", "DM me", "book a call", "get a quote") and after the model itself was correctly labelling those posts' seller/job-seeker cousins as `irrelevant` anyway. All extra marker sets + their tests were removed. |

Lesson recorded here so it is not re-learned the expensive way: cheap keyword
drops on a source that returns real buyers using real-world language (which
overlaps seller language) trade genuine recall for call-count savings, and the
savings only move the DeepSeek call-count while the accept-rate stays bounded
by SERP precision.

---

## 4. DeepSeek classification — verbatim + model

Provider: **DeepSeek**. `GptClassifier.__init__` default `provider="deepseek"`,
`json_mode="json_object"` (DeepSeek does not support OpenAI `json_schema`).
Model string actually configured: `deepseek-chat` (default in
`backend/ha/classifier.py:277`; `backend/app/config.py` default; `DEEPSEEK_MODEL`
is **not** set in `backend/.env`, so the app default flows through
`hyperagent_service._ha_settings`). Per DeepSeek's current API docs and a live
response observed this session, requesting `deepseek-chat` is served by
**`deepseek-v4-flash` (DeepSeek V4-Flash-0731)** — i.e., the chat alias maps to
the v4-flash model. Base URL `https://api.deepseek.com`, `temperature=0.0`,
`response_format={"type":"json_object"}`.

The full system prompt sent on every candidate is the string
`_SYSTEM_PROMPT` in `backend/ha/classifier.py:27-144`. It is quoted in full in
the appendix (end of this file) because it is the classification contract; its
salient structure:

- One question: "WHO NEEDS and WHO OFFERS?"
- Output `lead_type` ∈ `need_freelancer | our_agency | irrelevant`
  (`models.py` `LeadClassification.lead_type` is the same `Literal`).
- Seven spelled-out reject categories (seller/offering, job seeker, talent
  marketplace/recruiting-seller, agency self-promotion, thought-leadership /
  engagement bait, employee job ads, referral asks that are self-promotion).
- Scoring rubric: `service_match_score`, `commercial_intent_score`,
  `decision_maker_signal`, `evidence_strength`, `overall_quality_score`
  (0-100), `intent_strength` ladder
  (`explicit|active_search|recommendation|problem_awareness|research|none`),
  `is_qualified`, `confidence` (0-1), plus `evidence` (verbatim quote) and
  `reason`.

Request path (`classifier.py:_classify_one`): system prompt + a user prompt
("The user sells: {service}." + scope sentence telling it which buyer types this
search accepts) + the post as JSON `{url, author, author_profile_url, posted_at,
text}` + a final "Output a single JSON object only." turn. Concurrency = a
`ThreadPoolExecutor` over candidates (default 8 workers). Fail-closed:
non-JSON / schema-invalid responses are dropped (`None`), with one retry that
tells the model which fields were missing. The required output object has 14
keys (see `_CLASSIFICATION_SCHEMA` in `classifier.py:166-193`).

---

## 5. Scoring + acceptance gate — verbatim

`backend/ha/scoring.py`:

```python
W_INTENT = 0.30
W_SERVICE_MATCH = 0.25
W_COMMERCIAL = 0.15
W_DECISION_MAKER = 0.10
W_LOCATION = 0.10
W_EVIDENCE = 0.10
```
`overall = 0.30*intent_rank + 0.25*service_match + 0.15*commercial +
0.10*(decision_maker?100:0) + 0.10*location + 0.10*evidence`

Hard gates (`compute_score`), every gate must pass:
```python
gates = {
    "type_is_buyer":     classification.lead_type in {need_freelancer, our_agency},
    "buying_not_selling": classification.is_buying_sourcing
                          and not classification.is_selling_offering
                          and not classification.is_job_seek,
    "service_match_ok":  classification.service_match_score >= cfg.min_service_match,
    "intent_ok":         rank >= min_intent_rank(cfg),
    "overall_ok":        overall >= cfg.min_overall,
    "model_qualified":   classification.is_qualified,
    "country_ok":        not foreign_hit,   # only enforced when strict_country
}
```

Thresholds configured for production (`hyperagent_service._ha_settings` → env):
`MIN_OVERALL_SCORE=55`, `MIN_SERVICE_MATCH=45`,
`MIN_INTENT_STRENGTH=recommendation` (rank ≥ 70), `REQUIRE_MODEL_QUALIFIED=0`
(volume mode — the model's `is_qualified` hedge is ignored once the other gates
pass), `STRICT_COUNTRY=0` (no country filter — global search),
`ACCEPT_SIBLING_BUYERS=1` (both `need_freelancer` and `our_agency` are accepted
types; the *type* gate for direction is then applied by the save-time store
wrapper / content gate, not by the classifier). Engine defaults in
`ha/config.py` are stricter (60/50/qualified) but are overridden by these env
values in production.

---

## 6. Iteration / stopping logic — verbatim + behavior

The loop is `for iteration in range(max(1, settings.engine_max_iterations))` in
`engine.py run_search()`. Production env knobs
(`hyperagent_service._ha_settings`): `ENGINE_MAX_ITERATIONS=12`,
`ENGINE_DEADLINE_SECONDS=540`, `ENGINE_EARLY_STOP_EMPTY_ROUNDS=4`; engine
defaults (ha/config.py) 30 / 1800 / 3.

Explicit answers from the code:

- **Max iteration cap:** yes — `engine_max_iterations` (12 in production).
- **Wall-clock deadline:** yes — `deadline = time.monotonic() +
  settings.engine_deadline_seconds` (540 s); checked at the top of every
  iteration, and a `deadline_hit` flag is recorded on early exit.
- **Early stop on consecutive zero-yield:** yes —
  ```python
  zero_yield_rounds = zero_yield_rounds + 1 if gained == 0 else 0
  ...
  if zero_yield_rounds >= settings.engine_early_stop_empty_rounds and iteration > 0:
      detail = f"{zero_yield_rounds} rounds in a row added nothing new; stopped early"
      break
  ```
  (`gained` = new accepted leads in that round). So a search stops after 4
  consecutive rounds that added **zero** accepted leads, not always at the cap.
- **Independent Serper / DeepSeek call ceilings:** **none.** There is no
  dedicated counter for either provider. Serper calls are bounded only
  *indirectly*: ≤6 queries per round (query_builder `next_queries` window) ×
  `serper_pages_per_query` (2 in production; num=10/page) × up to 12 iterations,
  minus early stops. DeepSeek calls are bounded only by the number of candidates
  that survive dedupe+prefilter+content gate each round, times the rounds that
  actually run — with the same iteration/deadline/empty-stop controls. Nothing
  stops a pathological niche from issuing, e.g., ~12 rounds × ~6 queries × 2
  pages = ~144 Serper requests before the empty-round stop kicks in.
- **Dedupe point vs the LLM:**
  - **Intra-search duplicates** are removed *before* both the content gate and
    DeepSeek. In `engine.py` the per-post loop does, in order:
    `canonical_post_url` → `seen_urls` membership check → `prefilter` → content
    gate; a duplicate URL is dropped at the `seen_urls` check (before any LLM
    spend). Exact point:
    ```python
    key = canonical_post_url(post.post_url)
    if not key or key in seen_urls:
        continue
    seen_urls.add(key)
    ```
  - **Cross-search duplicates (already owned in the DB)** are NOT checked before
    DeepSeek. After classification + scoring, the engine calls
    `store.find_existing_post_urls(...)` and only *then* skips owned posts
    (`dup_owned += 1`). So a post saved by an earlier search is fully
    re-fetched and re-classified by DeepSeek before being skipped. In the
    sampled runs `dup_owned` reached 11 in a single search. (Finding, not a fix:
    a cheap pre-LLM URL lookup against existing `ha_leads.post_url` would remove
    those calls.)

---

## 7. Real efficiency numbers from recent runs

Source: `ha_searches` rows (service/counts) + actual `ha_leads` counts in the
shared Supabase project, and the `engine | Search … done:` log lines where the
breakdown was captured. The two runs marked *(test)* were throwaway live runs
created for this audit and deleted afterwards (they therefore do not appear in
the table but are included for comparison).

**"DeepSeek calls per saved lead" = `scanned / saved`** (scanned ≈ LLM calls;
`type_mismatch` = correctly-rejected-by-LLM, where a done-line was captured):

| Time (UTC) | Service | Type | Need | found | scanned | acc(claim) | saved | LLM calls / saved lead | Breakdown (from done-line, where captured) |
|---|---|---|---|---|---|---|---|---|---|
| 09-07 16:48 | logo design | agency | 3 | 66 | 44 | 2 | 2 | **22** | — |
| 09-08 04:12 | seo expert | agency | 3 | 49 | 35 | 0 | 0 | — (0 leads) | — |
| 09-08 04:47 | website development | freelancer | 3 | 123 | 84 | 1 | 1 | **84** | — |
| 09-08 05:21 | video editing | freelancer | 3 | 130 | 96 | 3 | 3 | **32** | — |
| 09-08 05:22 | video editing | freelancer | 3 | 50 | 45 | 3 | 3 | **15** | — |
| 09-08 05:25 | video editing | agency | 3 | 68 | 65 | 3 | 2 | **32.5** | — |
| 09-08 11:28 | app development | freelancer | 3 | 35 | 35 | 3 | 3 | **11.7** | pref 0 · content 0 · **type_mismatch 31** · dup 1 |
| 09-08 11:31 | saas development | agency | 3 | 98 | 21 | 3 | 3 | **7** | pref 3 · content 57 · type_mismatch 18 |
| 09-08 11:33 | ui ux designer | agency | 3 | 5 | 1 | 0 | 0 | — (0 leads) | content 3 · type_mismatch 1 |
| 09-08 12:52 | website development | agency | 3 | 92 | 44 | 3 | 3 | **14.7** | — |
| 09-08 12:54 | ui ux designer | freelancer | 3 | 152 | 92 | 1 | 1 | **92** | content 7 · type_mismatch 89 · dup 2 |
| 09-08 12:56 | ui ux designer | freelancer | 3 | 153 | 94 | 1 | 1 | **94** | — |
| 09-08 13:04 | video editing | freelancer | 3 | 164 | 87 | 3 | 3 | **29** | content 14 · type_mismatch 73 · dup 11 |
| 09-08 13:20 | logo design | freelancer | 3 | 118 | 79 | 3 | 3 | **26.3** | content 8 · type_mismatch 75 · dup 1 |
| 09-08 13:25 | Digital ad films | agency | 3 | 5 | 1 | 0 | 0 | — (0 leads) | — |
| *(test)* | digital marketing | agency | 5 | 152 | 62 | 4 | 4 | **15.5** | (throwaway, deleted) |
| *(test)* | SEO expert | freelancer | 5 | 330 | 152 | 3 | 3 | **50.7** | (throwaway; type_mismatch ≈146, dup 3) |

**Answers from the table:**
- **`type_mismatch` is consistently the dominant rejection reason** wherever a
  breakdown is logged (31→146 of the scanned posts each run are LLM-verified
  irrelevant), and it is always the largest term. There is no niche that avoids
  it; it scales with how many buyer-phrased-but-not-buyer posts Google returns.
- **Variability is service/lane driven.** Best efficiency seen: **our_agency /
  broad services** — saas development **7 calls/lead** (content_dropped 57:
  most of the noise is agency/freelance asks cheaply filtered for the
  agency lane), digital marketing **15.5**, website development agency **14.7**.
  Worst: **need_freelancer / designer** niches — ui ux designer **92–94
  calls/lead** (found 152-153, only 1 genuine saved). Tiny-SERP niches
  (Digital ad films, ui ux agency, seo agency: found 5–49) return **0** saved
  leads honestly (no padding).
- Freelancer ("someone needs a freelancer") searches on crowded creative
  keywords (video editing, ui ux, logo design) are the expensive tail: 15–94
  calls/lead with 1–3 leads found. Agency-lane searches convert 2–4× better on
  similar services.

---

## 8. Cost estimate

Pricing is **not present in the repo config** (no Serper tier/price, no DeepSeek
rate in env); the figures below are estimates at published list prices and must
be confirmed against the account's actual Serper/DeepSeek dashboards.

Assumptions per classification call: ~2,500 input tokens (≈1,900-token system
prompt + post JSON + short turns) and ~250 output tokens.
Sources: [DeepSeek API docs (models page)](https://api-docs.deepseek.com/quick_start/pricing) —
current models are `deepseek-v4-flash` / `deepseek-v4-pro`; chat-alias requests
are served by v4-flash. [Serper homepage](https://serper.dev/) advertises
2,500 free queries; paid tiers are per-query.

| Run | LLM calls (scanned) | ≈ Serper requests* | DeepSeek est. | Serper est. (paid tier) |
|---|---|---|---|---|
| saas development / agency (best: 21 scanned) | 21 | ~8–12 | ~$0.02–0.06 | ~$0.01–0.05 |
| logo design / freelancer (79 scanned) | 79 | ~15–25 | ~$0.08–0.25 | ~$0.02–0.10 |
| SEO expert / freelancer (152 scanned) | 152 | ~35–50 | ~$0.15–0.45 | ~$0.05–0.20 |

\*Serper requests ≈ rounds actually run × queries per round × 2 pages, bounded
by early stop; counted from page-1/page-2 log lines per query. Ranges assume
DeepSeek input ≈ $0.07–0.30/M (cache-hit to cache-miss) and output ≈ $0.30–1.10/M,
and Serper ≈ $0.001–0.004/request.

**Which is the larger driver?** At list prices, **DeepSeek is not the dominant
dollar cost** — it is roughly $0.02–0.45/search even for the worst runs, and the
efficiency problem is that most of those calls are *wasted* (not that they are
expensive per call). Serper per-search is comparable or higher on paid plans,
and on the **free 2,500-query allowance** Serper is what actually runs out: at
30–60 requests per search a free allowance disappears in ~40–80 searches. The
user-visible "credits getting eaten" is therefore most plausibly **Serper query
credits**, with DeepSeek contributing little in dollars. The real lever is
precision (leads per scan), not per-call price — see §7.

---

## 9. Lead-quality spot-check

Five+ **accepted** leads (verbatim `post_text` from `ha_leads`, most recent
saved; author, type, score in parentheses):

1. **Shariff Nahurira · need_freelancer · 84.5** — "need a logo for my business. Nahurira Shariff. SID Sports Center, sells football jerseys, soccer boots and other sports items. sportswear, social media, ..." → **genuine** (small owner buying a logo).
2. **Nick Nc Psmtech · need_freelancer · 87.2** — "We are looking for a talented UI/UX Product Designer with 2+ years of hands-on experience designing modern, complex web applications." → **suspicious** — reads like an employee job ad (2+ yrs in-house designer); accepted into the freelancer lane.
3. **Shahzad Khan Copywriter · need_freelancer · 91.5** — "Looking for an AI video editor who knows how to create and edit videos for DTC brands. Claymations. AI UGC. Zack D Films." → **genuine** buyer ask.
4. **Milesdeutscher · need_freelancer · 89.5** — "I'm hiring for two cracked video editors. Looking for people with real taste, storytelling skills, and an understanding of retention." → **borderline** — content brand hiring editors; could be contractor roles, but phrasing is employee-job-like.
5. **Ishika · our_agency · 88.5** — "We are a Lead Generation Agency currently looking to outsource a Society Management SaaS project. S and multi-tenant platforms. testing, and deployment." → **genuine our_agency** (agency outsourcing for own client work).
6. **Aarifhussainz · need_freelancer · 86.5** — "I'm Hiring a Video Editor. Helping coaches get high-paying clients through LinkedIn content, positioning, outreach & branding — fill out the form below." → **borderline/suspicious** — recruiter-style hire with a "fill out the form" application funnel.

**Verdict:** roughly 3/6 clearly genuine, 2/6 borderline employee-hire phrasing,
1 recruiter-funnel — i.e., the classifier (and gates) still let a meaningful
minority of job-ad / recruiter-style posts through as freelancer leads, the same
borderline observed on the live runs (in-house "Senior Global Partner Marketing",
"SEO Specialist" hires). This is a precision issue at the classifier/scoring
level, independent of the cost question.

**Rejected leads cannot be spot-checked after the fact.** Posts classified
`irrelevant` (the 31–146 per run) are dropped in memory; **neither their text
nor the model's `reason` is persisted or logged**. `ha_leads` stores only
accepted posts and none of the classifier's `reason`/`evidence`. Recovering
verbatim rejected text would require a re-run with instrumentation. (Finding,
not a fix.)

---

## 10. Summary + incidental findings

1. **Biggest driver of wasted DeepSeek calls (from §7, not a guess):** posts that
   Google surfaces for buyer-phrased LinkedIn queries are overwhelmingly
   non-buyers that still pass the (deliberately safe) prefilter and content gate
   and are then confirmed `irrelevant` by DeepSeek — `type_mismatch` dominates
   every run (31–146). The inefficiency is **source precision**, amplified by
   filtering *after* the LLM instead of before it.
2. **Content-gate verdict:** the current baseline is **roughly right for
   precision** (audit found no evidence of silent genuine-lead drops) and
   **under-filtered for cost** — but the two cheap keyword tightenings that were
   tried genuinely risked/did drop real leads and were reverted. Any future
   change should be measured, per-lane, with before/after runs — not keyword
   whack-a-mole.
3. **Incidental findings (listed, not fixed):**
   - **Dead/stale naming:** `engine.py`, `classifier.py`, `models.py`,
     `serp_client.py` still say "GPT-4o" while the real provider is DeepSeek
     (v4-flash via the `deepseek-chat` alias). Cosmetic but misleading for the
     next reader.
   - **`hiring` leftovers:** `hiring_buyer` / `marketplace_match` only survive
     as defensive string fallbacks in `routers/search.py:433` and
     `routers/leads.py:219` plus a comment in `ha/config.py:90`. No requestable
     type, DB constraint, or UI path uses them.
   - **Cross-search duplicates pay a DeepSeek call:** `find_existing_post_urls`
     runs after classification/scoring; `dup_owned` reached 11 in one run. A
     pre-LLM `ha_leads.post_url` lookup (cheap, alongside `seen_urls`) would
     eliminate those calls.
   - **No independent provider call ceilings:** Serper and DeepSeek spend are
     bounded only indirectly (≤6 queries/round × 2 pages × ≤12 iterations, plus
     deadline/empty-stop). A pathological niche can still issue ~140+ Serper
     requests before the 4-empty-round stop.
   - **No rejection observability:** per-candidate text and `reason` are never
     stored/logged; only aggregate counters exist. This made the recent
     gate-tuning attempts blind and re-blocks post-hoc quality audits.
   - **Classifier accepts some job-ad phrasing** as freelancer leads (see §9),
     a precision gap at the model/gate boundary rather than in discovery.

---

## Appendix A — `_SYSTEM_PROMPT` (full, verbatim, `classifier.py:27-144`)

```
You are the lead-qualification classifier for a service marketplace. Your only job is to
decide whether a LinkedIn post is a GENUINE BUYER of the service the user sells — a real
procurement intent from someone who needs the service — or noise that must be rejected.

Ask ONE question about every post: WHO NEEDS and WHO OFFERS?

Answer as one of three types:
- need_freelancer: someone needs an INDEPENDENT freelancer/contractor/individual for
  their own project or company — whether a solo founder or a business sourcing a
  freelancer/contractor for a defined piece of work.
- our_agency: an AGENCY wants to bring in outside freelance help (they source for
  their own client work, they do not sell).
- irrelevant: everything else — including employee job ads, hiring for an in-house
  full-time role, sellers, and all the reject categories below.

REJECT CATEGORIES — recognize and reject each, even in disguise:
1. Seller / offering: the author provides the service themselves. Signals: "we offer...",
   "DM me for...", "book a call", "free consultation", "white-label/OEM pitch", a supplier
   pitching a lead-list TO agencies, "we can help your brand", "limited spots", "I provide...",
   "my services include", "portfolio in comments", "taking new clients", "available for projects".
2. Job seeker: the author wants employment or clients for THEMSELVES. Signals: "open to work",
   "I'm a freelance X available for projects", "seeking new clients", "portfolio in comments",
   "hiring manager feel free to reach out", "I just left my job and I'm looking for my next thing".
3. Talent marketplace / recruiting-seller: a platform or staffing agency recruiting freelancers
   to place at SOMEONE ELSE'S clients. Signals: "join our talent network", "we place X at",
   "staffing agency", "submit your portfolio to join our pool", "we connect brands with vetted
   freelancers", "our network of pre-vetted designers". This is NOT a buyer, even when
   they say they need freelancers — they recruit freelancers as inventory, not for their own project.
4. Agency self-promotion: "our agency can help", "we specialize in X", "full-service agency",
   "we are the growth partner for...". The word "agency" does NOT make it our_agency — offering
   help is SELLING. Only an agency that is sourcing help for its own client work is our_agency.
5. Thought leadership / engagement bait: generic tips/advice/opinion with no procurement action
   ("5 tips...", "in my experience...", "why your X is broken", "what I learned", "thread on",
   "10 signs your brand needs..."). An opinion post is NOT a buyer even when it mentions the service.
   No ask = no lead. Also reject "we are hiring freelancers" from a marketplace that profits from
   placements, and job ads that recruit an EMPLOYEE (full-time salary role with benefits) rather
   than a defined freelance/contract project for a genuine owner.
6. Job ads for employees: "full-time position", "vacancy", "apply now", "benefits", "salary
   range", "equity offered". These are irrelevant (never a lead). A post hiring a
   freelance/contract worker for a defined project CAN be need_freelancer — judge on project vs
   employment. A recruiter posting on behalf of other companies is a seller, not a buyer.
7. Referral asks that are actually self-promotion: "DM me for recommendations" from someone who
   sells the service themselves is a seller. But "anyone know a good X, my project needs one"
   from a genuine owner IS a buyer (recommendation intent) — do not over-reject.

DISTINCTION RULES (precision over recall — a false positive is costly):
- "is_buying_sourcing" = the author needs the service for their OWN project/company/clients.
- Only set is_selling_offering / is_job_seek for sell-side intent; a buyer may also be a freelancer
  by profession as long as THIS post is them buying.
- our_agency requires the author to be an agency SEEKING outside help ("looking for freelancers to
  work with our agency", "extra {service} for client projects", "white-label partner wanted").
  "We offer white-label X" is a SELLER.
- A single post can mix signals ("need a {service} — DM me if you know someone" is a BUYER asking
  for referrals; "DM me for {service}" is a SELLER). Judge the main intent.

DOMAIN-GENERAL REASONING (§0): apply the direction-of-intent test below to whatever service the
user sells — plumbing in Nairobi, UX design in Toronto, wedding photography in Mumbai, anything.
There are no per-service rules; these examples teach the PATTERN, not an allow-list. The four
canonical pairs (paraphrased, for an imaginary production service) are:

1. "We're launching a product next month and need someone to shoot our ad — any recommendations for
   a production house?"  ->  is_qualified: true, lead_type: need_freelancer (real client, genuine ask).
2. "Looking for brands to partner with for their ad films — we bring creative + production in-house."
   ->  is_qualified: false, is_selling_offering: true (direction reversed — they hunt clients).
3. "We help brands create stunning ad films that convert. DM to discuss your next project."
   ->  is_qualified: false, is_selling_offering: true (classic seller pitch).
4. "I'm a video editor/filmmaker looking for freelance projects, available immediately."
   ->  is_qualified: false, is_job_seek: true (job-seeker, not a buyer).
5. "Anyone know a video editor? We need 20 shorts cut for our campaign this month." (owner with a
   concrete need)  ->  is_qualified: true, lead_type: need_freelancer.

Same pattern for any {service}: the asker must need the work done, not offer to do it, not be a
freelancer hunting for their own gig, and not be a recruiter stocking talent for other people.

SCORING RUBRIC (0-100):
- service_match_score: how directly the post is about the service the user sells (exact service
  mentioned = 90+, adjacent craft = 60-80, unrelated = <40).
- commercial_intent_score: money signals — budget, paid, rate, timeline, deadline, retainer,
  "decision this week", scale of work. A bare "looking for X" with no scale is 40-60; concrete
  budget/volume/urgency is 70+.
- decision_maker_signal: true only if the author appears to own the need/budget (founder, owner,
  marketing lead, agency principal). Referrals "anyone know a good X" are still strong leads:
  set true when they ask on behalf of a need they own. False for junior "does anyone know who
  handles X at our company" with no ownership.
- evidence_strength: how explicit the deciding lines are (explicit ask + budget = 90+; vague =
  40-60; nothing concrete = <40).
- overall_quality_score: expected lead value 0-100 with a precision bias — overestimate only when
  evidence is strong.

Also return:
- intent_strength: explicit (clear procurement ask) | active_search (sourcing right now) |
  recommendation (asking for referrals/recommendations) | problem_awareness (problem stated, no ask) |
  research (exploring) | none.
- is_qualified: your holistic verdict. Be strict: only true when this is a real, current buyer.
- confidence: 0-1 in your verdict.
- evidence: a SHORT near-verbatim quote of the deciding line(s) from the post.
- reason: 1-2 sentences; name the category/type and, if you rejected, which trap it was.

Never invent facts not in the post. Never output anything but the JSON object.

OUTPUT FORMAT — return ONE JSON object and NEVER omit a field. The object must contain
EXACTLY these keys (fill every one; booleans as true/false, scores 0-100, confidence 0-1):
{
  "lead_type": "need_freelancer|our_agency|irrelevant",
  "intent_strength": "explicit|active_search|recommendation|problem_awareness|research|none",
  "is_buying_sourcing": true,
  "is_selling_offering": false,
  "is_job_seek": false,
  "service_match_score": 90,
  "commercial_intent_score": 80,
  "decision_maker_signal": true,
  "evidence_strength": 85,
  "overall_quality_score": 88,
  "is_qualified": true,
  "confidence": 0.95,
  "evidence": "short verbatim quote",
  "reason": "1-2 sentences"
}
```
