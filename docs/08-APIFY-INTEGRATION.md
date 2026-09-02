# 08 — APIFY INTEGRATION GUIDE

## Complete Apify Setup & Usage

---

## Overview

Apify is the primary data source for LinkedIn leads. Lead Forge AI uses:
- **24 API keys** for failover and rate distribution
- **3 different actors** for different data types
- **Boolean operators** for better search results

---

## Actors Used

### 1. LinkedIn Post Search (PRIMARY)

**Actor:** `harvestapi~linkedin-post-search`
**Cost:** $1.50 per 1,000 posts
**Purpose:** Find LinkedIn posts matching search queries

**Payload:**
```json
{
    "searchQueries": [
        "need website development",
        "looking for website developer",
        "website development services required",
        "hiring website developer"
    ],
    "maxPosts": 15,
    "postedLimit": "month",
    "sortBy": "date",
    "profileScraperMode": "main",
    "scrapeReactions": false,
    "postNestedReactions": false,
    "scrapeComments": false,
    "postNestedComments": false
}
```

**Response:**
```json
{
    "id": "post-id-123",
    "linkedinUrl": "https://linkedin.com/posts/user-123_abc456",
    "content": "Looking for a website developer...",
    "postedAt": "2025-01-15T10:30:00Z",
    "author": {
        "name": "John Smith",
        "linkedinUrl": "https://linkedin.com/in/johnsmith",
        "info": "CEO at Acme Corp",
        "location": {
            "countryCode": "US",
            "city": "New York"
        }
    },
    "engagement": {
        "likeCount": 45,
        "commentCount": 12,
        "repostCount": 3
    }
}
```

---

### 2. LinkedIn Profile Scraper

**Actor:** `harvestapi~linkedin-profile-scraper`
**Cost:** $0.50 per 1,000 profiles
**Purpose:** Enrich profiles with detailed info

**Payload:**
```json
{
    "profileUrls": [
        "https://linkedin.com/in/johnsmith",
        "https://linkedin.com/in/janedoe"
    ]
}
```

**Response:**
```json
{
    "url": "https://linkedin.com/in/johnsmith",
    "fullName": "John Smith",
    "headline": "CEO at Acme Corp",
    "location": "New York, NY",
    "company": "Acme Corp",
    "email": "john@acme.com",
    "phone": "+1-555-0123"
}
```

---

### 3. LinkedIn Job Scraper

**Actor:** `shahidirfan~linkedin-job-scraper`
**Cost:** $0.30 per 1,000 jobs
**Purpose:** Find job postings for hiring searches

**Payload:**
```json
{
    "searchQueries": [
        "website developer jobs",
        "web design jobs"
    ],
    "maxJobs": 10,
    "postedLimit": "month"
}
```

**Response:**
```json
{
    "id": "job-123",
    "title": "Website Developer",
    "company": "Acme Corp",
    "location": "Remote",
    "url": "https://linkedin.com/jobs/view/123456789",
    "postedAt": "2025-01-15T10:30:00Z",
    "workType": "Remote"
}
```

---

## Key Rotation System

### 24 API Keys

```python
# Config from .env
APIFY_KEYS = [
    settings.apify_api_key,      # Primary
    settings.apify_api_key_2,    # Secondary
    # ... up to apify_api_key_24
]

# Filter out empty keys
APIFY_KEYS = [k for k in APIFY_KEYS if k]
```

### Rotation Logic

```python
_key_cursor = 0  # Global rotation cursor
_key_cooldown = {}  # key -> cooldown_until_timestamp
_KEY_PERMA_BLACKLIST = set()  # Revoked keys

def _ordered_keys() -> list[str]:
    """Returns keys in priority order:
    1. Primary key (always first)
    2. Healthy keys (no cooldown)
    3. Cooldown keys (last resort)
    4. Blacklisted keys (never used)
    """
    global _key_cursor
    keys = []
    
    for i in range(len(APIFY_KEYS)):
        idx = (_key_cursor + i) % len(APIFY_KEYS)
        key = APIFY_KEYS[idx]
        
        # Skip blacklisted keys
        if key in _KEY_PERMA_BLACKLIST:
            continue
        
        # Check cooldown
        if key in _key_cooldown:
            if time.time() < _key_cooldown[key]:
                keys.append(key)  # Cooldown key (last resort)
                continue
        
        keys.append(key)  # Healthy key
    
    return keys
```

### Failover on Error

```python
def _run_sync_actor(actor_id, payload, max_retries=3):
    """Run actor with automatic key failover."""
    keys = _ordered_keys()
    
    for key in keys[:max_retries]:
        try:
            result = _run_with_key(actor_id, payload, key)
            return result
            
        except RateLimitError:
            # Put key on cooldown (600 seconds)
            _key_cooldown[key] = time.time() + 600
            logger.warning(f"Key {key[:10]}... rate limited, cooldown 600s")
            
        except AuthError:
            # Permanently blacklist this key
            _KEY_PERMA_BLACKLIST.add(key)
            logger.error(f"Key {key[:10]}... auth failed, blacklisted")
    
    return []  # All keys failed
```

### Cooldown Management

```python
KEY_COOLDOWN_SECONDS = 600  # 10 minutes

def _cleanup_cooldowns():
    """Remove expired cooldowns."""
    now = time.time()
    expired = [k for k, v in _key_cooldown.items() if v < now]
    for k in expired:
        del _key_cooldown[k]
```

---

## Buyer Mode

When searching for genuine buyers (not hiring), use buyer mode:

```python
def run_lane_search(queries, max_posts=15, posted_limit="month", buyer_mode=False):
    payload = {
        "searchQueries": queries[:4],
        "maxPosts": min(max_posts, 15),
        "postedLimit": posted_limit,
        "sortBy": "date",
        "profileScraperMode": "main",
    }
    
    if buyer_mode:
        # Boolean NOT operators to exclude seller language
        payload["searchQueries"] = [
            q + ' NOT "I offer" NOT "available for" NOT "my services"'
            for q in queries[:2]
        ]
        
        # Decision-maker filter
        payload["authorKeywords"] = "Founder,CEO,Owner,Director,Manager"
    
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)
```

### Boolean Operators

LinkedIn supports these boolean operators:
- `AND` — Both terms must appear
- `OR` — Either term can appear
- `NOT` — Exclude posts containing this term

**Examples:**
```
"need website development" NOT "I offer"
"looking for developer" NOT "freelancer" NOT "available"
"hiring web designer" OR "need web designer"
```

### authorKeywords Filter

Only return posts from authors whose headline contains:
```
Founder, CEO, Owner, Director, Manager, VP, Head, President
```

This filters out freelancer sellers who typically have:
- "Freelance Web Developer"
- "Available for hire"
- "Check my portfolio"

---

## Multi-Lane Parallel Execution

### Lane Structure

```python
# 12 lanes, each with 4 queries
lanes = [
    ["need website development", "looking for website developer", ...],  # Lane 0
    ["website development help needed", "seeking website developer", ...],  # Lane 1
    ["website development project", "website development services", ...],  # Lane 2
    # ... 12 lanes total
]

# Fire all lanes in parallel
results = await asyncio.gather(*[
    asyncio.to_thread(run_lane_search, lane, 15, "month")
    for lane in lanes
])
```

### Deduplication

```python
def dedupe_post_items(items: list[dict]) -> list[dict]:
    """Dedupe raw post items by post id / url across lanes."""
    seen: set[str] = set()
    unique: list[dict] = []
    
    for item in items:
        pid = item.get("postId") or item.get("id") or item.get("url") or item.get("linkedinUrl")
        
        if not pid or pid in seen:
            continue
        
        seen.add(pid)
        unique.append(item)
    
    return unique
```

---

## Query Generation

### Broad Discovery (Wave 1)

```python
def build_boolean_query(user_query: str) -> list[str]:
    """Generate 12 broad discovery phrases."""
    
    phrases = [
        f"need {user_query}",
        f"looking for {user_query}",
        f"{user_query} services required",
        f"hiring {user_query}",
        f"{user_query} project",
        f"need a {user_query}",
        f"looking for {user_query} company",
        f"{user_query} help needed",
        f"seeking {user_query}",
        f"{user_query} freelance",
        f"need someone for {user_query}",
        f"{user_query} agency"
    ]
    
    return phrases
```

### Variant Queries (Waves 2-8)

```python
def build_boolean_query_variant(user_query, iteration):
    """Different query angles for subsequent waves."""
    
    variants = {
        0: [f"need {user_query}", f"looking for {user_query}"],
        1: [f"website not converting", f"website needs redesign"],
        2: [f"{user_query} urgent", f"{user_query} ASAP"],
        3: [f"{user_query} project", f"{user_query} services"],
        4: [f"hiring {user_query}", f"freelance {user_query}"],
        5: [f"{user_query} redesign", f"{user_query} revamp"],
        6: [f"affordable {user_query}", f"{user_query} cost"],
        7: [f"recommend {user_query}", f"best {user_query}"]
    }
    
    return variants.get(iteration, variants[0])
```

---

## Health Check

```python
def check_apify_keys_health():
    """Validate all Apify keys."""
    results = {}
    
    for i, key in enumerate(APIFY_KEYS):
        try:
            # Test with minimal request
            response = httpx.get(
                "https://api.apify.com/v2/acts",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10
            )
            
            if response.status_code == 200:
                results[f"key_{i+1}"] = "healthy"
            elif response.status_code == 401:
                results[f"key_{i+1}"] = "invalid"
            elif response.status_code == 429:
                results[f"key_{i+1}"] = "rate_limited"
            else:
                results[f"key_{i+1}"] = f"error_{response.status_code}"
                
        except Exception as e:
            results[f"key_{i+1}"] = f"exception: {str(e)}"
    
    return results
```

---

## Cost Optimization

### 1. Limit Posts Per Lane

```python
# Bad: 50 posts per lane × 12 lanes = 600 posts = $0.90
payload["maxPosts"] = 50

# Good: 15 posts per lane × 12 lanes = 180 posts = $0.27
payload["maxPosts"] = 15
```

### 2. Use Posted Limit

```python
# Only get posts from last month (not all time)
payload["postedLimit"] = "month"
```

### 3. Skip Reactions/Comments

```python
# Don't scrape reactions (saves API credits)
payload["scrapeReactions"] = False
payload["scrapeComments"] = False
```

### 4. Buyer Mode Reduces Waste

```python
# Boolean NOT filters out seller posts early
payload["searchQueries"] = [
    q + ' NOT "I offer" NOT "available for"'
    for q in queries
]
```

### 5. Parallel Lanes (Not Sequential)

```python
# Bad: Sequential (slow, same key reused)
for lane in lanes:
    result = run_lane_search(lane)

# Good: Parallel (fast, different keys)
results = await asyncio.gather(*[
    run_lane_search(lane) for lane in lanes
])
```

---

## Error Handling

### Rate Limit (429)

```python
except RateLimitError:
    # Put key on cooldown
    _key_cooldown[key] = time.time() + 600
    
    # Try next key
    continue
```

### Auth Error (401)

```python
except AuthError:
    # Permanently blacklist
    _KEY_PERMA_BLACKLIST.add(key)
    
    # Try next key
    continue
```

### Timeout

```python
except httpx.TimeoutException:
    # Log and continue
    logger.warning(f"Timeout for key {key[:10]}...")
    continue
```

---

## Monitoring

### Key Health Dashboard

```python
@app.get("/api/apify/health")
async def apify_health():
    """Check all Apify keys."""
    health = check_apify_keys_health()
    
    healthy = sum(1 for v in health.values() if v == "healthy")
    total = len(health)
    
    return {
        "status": "healthy" if healthy == total else "degraded",
        "healthy_keys": healthy,
        "total_keys": total,
        "details": health
    }
```

### Usage Tracking

```python
# Track API calls per key
_api_calls = defaultdict(int)

def _run_with_key(actor_id, payload, key):
    _api_calls[key] += 1
    # ... actual API call
```
