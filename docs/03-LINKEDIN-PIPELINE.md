# 03 — LINKEDIN PIPELINE

This is the **core brain** of the application — `linkedin_pipeline.py` at 2,540 lines is the largest and most complex file.

---

## High-Level Flow

```
User: "website development" + "India" + "buyer"
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 1: QUERY GENERATION                          │
│  build_boolean_query() → 12 discovery phrases        │
│  build_boolean_query_variant() → 8 angle variations  │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 2: APIFY SEARCH (parallel lanes)             │
│  12 lanes × 4 queries × 15 posts = 720 raw records  │
│  + Job filler (hiring searches only)                 │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 3: PROCESS & FILTER                          │
│  process_items() → dedupe, country gate, build leads │
│  + Author dedupe (best post per author)              │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 4: AI QUALIFICATION (2 stages)               │
│  Triage: gpt-4o-mini (cheap, batches of 20)         │
│  Score: gpt-4o-mini (12 concurrent async)           │
│  Dimensions: intent, fit, urgency, engagement,       │
│              recency, decision-maker                  │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 5: TIERED ACCEPTANCE                         │
│  Tier 1: score ≥ 80 (strict)                        │
│  Tier 2: score ≥ 65 (medium)                        │
│  Tier 3: score ≥ 50 (relaxed)                       │
│  Country + type gates at each tier                   │
└─────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────┐
│  STAGE 6: SAVE TO DATABASE                          │
│  _save_leads_bulk() → bulk insert with deduplication │
│  post_type mapping: explicit_need→buyer, hiring→hiring│
└─────────────────────────────────────────────────────┘
```

---

## Stage 1: Query Generation

### `build_boolean_query(user_query: str) -> list[str]`

Generates **12 broad discovery phrases** from the user's niche:

```python
# Input: "website development"
# Output: [
#   "need website development",
#   "looking for website development",
#   "website development services required",
#   "hiring website developer",
#   "website development project",
#   "need a website developer",
#   "looking for website development company",
#   "website development help needed",
#   "seeking website development",
#   "website development freelance",
#   "need someone for website development",
#   "website development agency"
# ]
```

**Logic:** Combines role-based phrases ("need X", "looking for X") with buyer-intent phrases and seller-attracting phrases.

### `build_boolean_query_variant(user_query, iteration) -> list[str]`

For waves 2-8, generates **different angles**:

| Wave | Angle | Example |
|------|-------|---------|
| 0 | Broad discovery | "need website development" |
| 1 | Problem-focused | "website not converting" |
| 2 | Urgency | "website needs urgent redesign" |
| 3 | Broad match | "website development project" |
| 4 | Hiring | "hiring website developer" |
| 5 | Redesign | "website redesign needed" |
| 6 | Cost | "affordable website development" |
| 7 | Recommendation | "recommend website developer" |

---

## Stage 2: Apify Search

### Multi-Lane Parallel Execution

```python
# 12 lanes, each with 4 queries
lanes = [
    ["need website development", "looking for website developer", ...],
    ["website development help needed", "seeking website developer", ...],
    # ... 12 lanes total
]

# Fire all lanes in parallel
results = await asyncio.gather(*[
    asyncio.to_thread(run_lane_search, lane, 15, "month")
    for lane in lanes
])
```

### `run_lane_search()` — Single Apify Run

```python
def run_lane_search(queries, max_posts=15, posted_limit="month", buyer_mode=False):
    payload = {
        "searchQueries": queries[:4],  # Max 4 queries per run
        "maxPosts": min(max_posts, 15),
        "postedLimit": "month",
        "sortBy": "date",
        "profileScraperMode": "main",
    }
    
    if buyer_mode:
        # Boolean NOT operators to exclude seller language
        payload["searchQueries"] = [
            q + ' NOT "I offer" NOT "available for" NOT "my services"'
            for q in queries[:2]
        ]
        # Only decision-maker authors
        payload["authorKeywords"] = "Founder,CEO,Owner,Director,Manager"
    
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)
```

### Buyer Mode Filters

When `buyer_only = True` (buyer search without hiring):

1. **Boolean NOT operators** appended to queries:
   ```
   "need website development" NOT "I offer" NOT "available for" NOT "my services"
   ```

2. **`authorKeywords` filter**: Only authors with decision-maker headlines:
   ```
   Founder, CEO, Owner, Director, Manager, VP, Head, President
   ```

This filters out freelancer sellers who say "I offer website development" and only shows people who need the service.

### Job Filler (Hiring Searches Only)

```python
if lead_types is None or "hiring" in lead_types:
    # Only run job filler for hiring searches
    job_items = await run_job_search(search_queries, max_posts=10)
    items.extend(job_items)
```

**Job Search:** Uses `shahidirfan~linkedin-job-scraper` Apify actor to find real job postings, then filters by work type (Remote/Part-time/Contract).

---

## Stage 3: Process & Filter

### `process_items()` — Main Processing

```python
def process_items(items, lead_types, req_country_codes, country_mode):
    best_by_author = {}  # Dedupe: best post per author
    skipped = 0
    
    for item in items:
        author = item.get("author") or {}
        author_url = author.get("linkedinUrl") or ""
        content = item.get("content") or ""
        
        # Skip empty/short content
        if not author_url or len(content) < 20:
            skipped += 1
            continue
        
        # Country filter (user-driven)
        country_code, location_text = _get_author_location(author)
        if not _country_match(country_code, location_text, req_country_codes):
            skipped += 1
            continue
        
        # Build lead object
        lead = {
            "full_name": author.get("name"),
            "headline": author.get("info"),
            "post_text": content,
            "post_url": item.get("linkedinUrl"),
            "country_code": country_code,
            "location": location_text,
            # ... more fields
        }
        
        # Dedupe by author (keep best post)
        key = author_url
        if key not in best_by_author or lead["engagement_score"] > best_by_author[key]["engagement_score"]:
            best_by_author[key] = lead
    
    return list(best_by_author.values()), skipped
```

### Country Filtering

**`_country_match(country_code, loc_signal, req_country_codes)`:**

```python
def _country_match(country_code, loc_signal, req_country_codes):
    # No countries requested → allow all
    if not req_country_codes:
        return True
    
    # Check country code
    if country_code and country_code in req_country_codes:
        return True
    
    # Fallback: location text or headline
    loc_lower = loc_signal.lower()
    for code in req_country_codes:
        country_name = COUNTRY_CODE_TO_NAME.get(code, "").lower()
        if country_name in loc_lower:
            return True
    
    return False
```

---

## Stage 4: AI Qualification

### Two-Stage Pipeline

```
Raw Candidates (50-200)
        ↓
┌───────────────────────────────────┐
│  STAGE 1: TRIAGE                  │
│  - gpt-4o-mini                    │
│  - Batches of 20 posts            │
│  - ~500 tokens per batch          │
│  - Binary: is_lead? (yes/no)      │
│  - Cost: ~$0.001 per batch        │
└───────────────────────────────────┘
        ↓
Filtered Candidates (10-50)
        ↓
┌───────────────────────────────────┐
│  STAGE 2: DEEP SCORING            │
│  - gpt-4o-mini                    │
│  - 12 concurrent async calls      │
│  - Score 0-100 across 6 dimensions│
│  - Cost: ~$0.002 per lead         │
└───────────────────────────────────┘
        ↓
Scored Leads (5-30)
```

### Triage Prompt

```python
TRIAGE_PROMPT = """
You are a lead qualification expert. Analyze this LinkedIn post and determine 
if it represents a genuine BUYING INTENT or HIRING signal.

POST: {post_text}
AUTHOR: {headline}
COMPANY: {company}

CLASSIFY AS:
- "is_lead": true/false
- "lead_type": "explicit_need" | "problem_awareness" | "research" | "hiring" | "job_seeker" | "seller" | "irrelevant"
- "reason": brief explanation

RULES:
- Hiring remote/contract talent = HIGH VALUE lead (80+ if decision-maker)
- "looking for a freelance X" from company = buyer
- "I'm a freelance X available" = seller (reject)
- Full-time on-site = never a lead
- Content/tips/opinions = never a lead
- NON-ENGLISH posts = reject
"""
```

### Deep Scoring Dimensions

Each lead scored 0-100 across **6 dimensions**:

| Dimension | Weight | Description |
|-----------|--------|-------------|
| **Intent** | 30% | How clear is the buying/hiring signal? |
| **Fit** | 20% | Does this match the user's niche? |
| **Urgency** | 15% | How urgently do they need help? |
| **Engagement** | 10% | Post reactions/comments |
| **Recency** | 10% | How recent is the post? |
| **Decision-Maker** | 15% | Is the author a decision-maker? |

**Final Score** = Weighted average → mapped to `ai_confidence_score`

### Scoring Example

```json
{
  "intent": 85,
  "fit": 90,
  "urgency": 70,
  "engagement": 60,
  "recency": 80,
  "decision_maker": 95,
  "final_score": 82,
  "lead_type": "explicit_need",
  "is_lead": true
}
```

---

## Stage 5: Tiered Acceptance

```python
# Tier 1: Strict (score ≥ 80)
if lead["ai_score"] >= 80:
    if _country_ok(lead) and _type_ok(lead):
        accept(lead)

# Tier 2: Medium (score ≥ 65)
elif lead["ai_score"] >= 65:
    if _country_ok(lead) and _type_ok(lead):
        accept(lead)

# Tier 3: Relaxed (score ≥ 50)
elif lead["ai_score"] >= 50:
    if _country_ok(lead) and _type_ok(lead):
        accept(lead)
```

### Country Gate (`_country_ok`)

```python
def _country_ok(lead, mode, req_country_codes):
    # mode="any" → always OK (last resort)
    if mode == "any":
        return True
    
    # User requested specific countries → must match
    loc_signal = lead.get("location") or lead.get("headline") or ""
    return _country_match(lead.get("country_code"), loc_signal, req_country_codes)
```

### Type Gate (`_type_ok`)

```python
def _type_ok(lead, allowed_types):
    if not allowed_types:
        return True
    return lead.get("lead_type") in allowed_types
```

---

## Stage 6: Save to Database

### `_save_leads_bulk()`

```python
async def _save_leads_bulk(supabase, search_id, user_id, leads, lead_types):
    remaining = await _get_remaining_leads(supabase, user_id)
    
    rows = []
    for lead in leads[:remaining]:
        ai_score = lead.get("ai_score", 0)
        
        # Post type mapping
        ai_type = lead.get("lead_type")
        if ai_type in ("explicit_need", "problem_awareness", "research", "agency"):
            post_type = "buyer"
        elif ai_type == "hiring":
            post_type = "hiring"
        elif ai_type == "job_seeker":
            post_type = "job_seeker"
        else:
            post_type = "buyer"
        
        # Lead category
        lead_category = "hot" if ai_score >= 85 else "warm"
        
        rows.append({
            "search_id": search_id,
            "user_id": user_id,
            "full_name": lead["full_name"],
            "headline": lead["headline"],
            "post_text": lead["post_text"],
            "post_url": lead["post_url"],
            "linkedin_url": lead.get("linkedin_url"),
            "ai_confidence_score": ai_score,
            "lead_type": ai_type,
            "post_type": post_type,
            "lead_category": lead_category,
            # ... more fields
        })
    
    # Bulk insert
    supabase.table("leads").insert(rows).execute()
```

### Deduplication

Before insert, check for existing leads with same `linkedin_url`:

```python
existing_urls = set()
result = supabase.table("leads") \
    .select("linkedin_url") \
    .eq("search_id", search_id) \
    .execute()
existing_urls = {r["linkedin_url"] for r in result.data}

new_rows = [r for r in rows if r["linkedin_url"] not in existing_urls]
```

---

## Wave System

### `run_linkedin_pipeline_fast()` — Guaranteed Count Pipeline

```python
async def run_linkedin_pipeline_fast(...):
    MAX_WAVES = 4
    WAVE_DEADLINE_SECONDS = 480  # 8 minutes total
    
    wave = 0
    while len(leads) < requested_count and wave < MAX_WAVES:
        wave += 1
        
        # Generate queries for this wave
        if wave == 1:
            queries = build_boolean_query(niche)
        else:
            queries = build_boolean_query_variant(niche, wave - 1)
        
        # Fire parallel lanes
        items = await _run_wave_async(lanes)
        
        # Process & score
        candidates = process_items(items, lead_types, ...)
        scored = await qualify_leads_with_ai_async(candidates, ...)
        
        # Tiered acceptance
        accepted = tier_filter(scored, ...)
        
        leads.extend(accepted)
        
        # Dynamic budget expansion (50% growth if not met)
        if len(leads) < requested_count and wave == MAX_WAVES:
            fetch_per_lane = int(fetch_per_lane * 1.5)
```

### Final Relaxation Pass

After all waves, if still under count:

```python
# Relaxation: score ≥ 50, any country, any type
final_relaxation = [l for l in last_scored_candidates
                    if l["ai_score"] >= 50
                    and _country_ok(l, country_mode, req_country_codes)
                    and _type_ok(l, allowed_types_set)]
```

---

## Key Constants

```python
MAX_RESULTS_CAP = 50           # Maximum leads per search
AI_QUALIFY_CONCURRENCY = 5     # Sync thread workers
AI_ASYNC_CONCURRENCY = 12      # Async concurrent AI calls
MAX_WAVES = 4                  # Max search waves
WAVE_DEADLINE_SECONDS = 480    # Total time limit (8 min)
DEEP_SCORE_CAP = 40            # Max leads for deep scoring
TIER_ACCEPTED_CAP = 60         # Max leads accepted total
```

---

## Location Helpers

### `COUNTRY_NAME_TO_CODE`

```python
COUNTRY_NAME_TO_CODE = {
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "india": "IN",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    # ... 40+ countries
}
```

### `CITY_COUNTRY_HINTS`

```python
CITY_COUNTRY_HINTS = {
    "new york": "US",
    "san francisco": "US",
    "london": "GB",
    "mumbai": "IN",
    "berlin": "DE",
    "toronto": "CA",
    "sydney": "AU",
    # ... 50+ cities
}
```

### `_parse_location_request(location: str) -> set[str]`

Parses user's location input into country codes:

```python
# Input: "India, United States"
# Output: {"IN", "US"}

# Input: "Europe"
# Output: {"GB", "DE", "FR", "ES", "IT", "NL", ...}  # All EU countries
```

---

## AI Prompts Summary

### Triage Prompt
- Binary classification (is_lead: yes/no)
- Classifies lead_type
- Rejects sellers, irrelevant, non-English

### Deep Scoring Prompt
- 6-dimension scoring (0-100)
- Requires JSON output
- Includes LEAD_TYPE CLASSIFICATION guide

### Pitch Generation Prompt
- Personalized outreach message
- References specific post content
- Professional tone
