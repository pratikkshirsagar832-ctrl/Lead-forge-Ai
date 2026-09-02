# 05 — EXTERNAL SERVICES INTEGRATION

## Overview

Lead Forge AI integrates with 4 external services:

| Service | Purpose | Cost Model |
|---------|---------|------------|
| **Apify** | LinkedIn scraping | Pay per result ($1.50/1K posts) |
| **OpenAI** | AI scoring, triage, pitches | Pay per token |
| **Supabase** | Database, auth, RLS | Free tier + paid |
| **Razorpay** | Payment processing | Transaction fees |

---

## 1. Apify Integration

### Overview

Apify is the primary data source for LinkedIn leads. The app uses **multiple Apify actors** with **24 API keys** for failover and rate distribution.

### Actors Used

| Actor | Purpose | Cost |
|-------|---------|------|
| `harvestapi~linkedin-post-search` | LinkedIn post search (PRIMARY) | $1.50/1K posts |
| `harvestapi~linkedin-profile-scraper` | Profile enrichment | $0.50/1K profiles |
| `shahidirfan~linkedin-job-scraper` | Job posting search | $0.30/1K jobs |
| `scrapeforge~linkedin-all-in-one` | Fallback post search | $2.00/1K posts |

### Key Rotation System

```python
# 24 possible keys
APIFY_KEYS = [
    settings.apify_api_key,      # Primary
    settings.apify_api_key_2,    # Secondary
    # ... up to apify_api_key_24
]

# Rotating cursor
_key_cursor = 0

def _ordered_keys() -> list[str]:
    """Returns keys in priority order:
    1. Primary key (always first)
    2. Healthy keys (no cooldown)
    3. Cooldown keys (last resort)
    4. Blacklisted keys (never used)
    """
    keys = []
    for i in range(len(APIFY_KEYS)):
        idx = (_key_cursor + i) % len(APIFY_KEYS)
        key = APIFY_KEYS[idx]
        
        if key in _KEY_PERMA_BLACKLIST:
            continue  # Skip revoked tokens
        
        if key in _key_cooldown:
            if time.time() < _key_cooldown[key]:
                keys.append(key)  # Cooldown key (last resort)
                continue
        
        keys.append(key)  # Healthy key
    
    return keys
```

### Failover Logic

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
        except AuthError:
            # Permanently blacklist this key
            _KEY_PERMA_BLACKLIST.add(key)
    
    return []  # All keys failed
```

### Post Search Flow

```python
def run_lane_search(queries, max_posts=15, posted_limit="month", buyer_mode=False):
    """Single Apify run for parallel lanes."""
    payload = {
        "searchQueries": queries[:4],  # Max 4 queries per run
        "maxPosts": min(max_posts, 15),
        "postedLimit": posted_limit,
        "sortBy": "date",
        "profileScraperMode": "main",
        "scrapeReactions": False,
        "scrapeComments": False,
    }
    
    if buyer_mode:
        # Boolean NOT operators to exclude sellers
        payload["searchQueries"] = [
            q + ' NOT "I offer" NOT "available for" NOT "my services"'
            for q in queries[:2]
        ]
        # Decision-maker filter
        payload["authorKeywords"] = "Founder,CEO,Owner,Director,Manager"
    
    return _run_sync_actor(HARVEST_POST_SEARCH_ACTOR, payload)
```

### Response Format

```json
{
  "id": "post-id-123",
  "linkedinUrl": "https://linkedin.com/posts/...",
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

## 2. OpenAI Integration

### Models Used

| Model | Purpose | Cost |
|-------|---------|------|
| `gpt-4o-mini` | Triage, scoring, pitches | $0.15/1M input, $0.60/1M output |
| `gpt-4o` | Website quality analysis | $2.50/1M input, $10/1M output |

### Triage (Stage 1)

```python
async def triage_candidates_async(candidates):
    """Cheap screening: is this a lead?"""
    batches = [candidates[i:i+20] for i in range(0, len(candidates), 20)]
    
    async def triage_batch(batch):
        prompt = f"""
        Analyze these LinkedIn posts and classify each as a lead or not.
        
        POSTS:
        {format_posts(batch)}
        
        Return JSON array with:
        - is_lead: boolean
        - lead_type: "explicit_need" | "problem_awareness" | "research" | "hiring" | "seller" | "irrelevant"
        - score: 0-100
        - reason: brief explanation
        """
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        return parse_response(response)
    
    # Run batches concurrently (5 at a time)
    results = await asyncio.gather(*[
        triage_batch(batch) for batch in batches[:5]
    ])
    
    return flatten(results)
```

### Deep Scoring (Stage 2)

```python
async def qualify_leads_with_ai_async(leads):
    """Detailed scoring across 6 dimensions."""
    async def score_one(lead):
        prompt = f"""
        Score this lead across 6 dimensions (0-100 each):
        
        1. INTENT: How clear is the buying/hiring signal?
        2. FIT: Does this match the target niche?
        3. URGENCY: How urgently do they need help?
        4. ENGAGEMENT: Post reactions/comments
        5. RECENCY: How recent is the post?
        6. DECISION_MAKER: Is the author a decision-maker?
        
        POST: {lead['post_text']}
        AUTHOR: {lead['headline']}
        COMPANY: {lead['company']}
        
        Return JSON:
        {{
            "intent": 0-100,
            "fit": 0-100,
            "urgency": 0-100,
            "engagement": 0-100,
            "recency": 0-100,
            "decision_maker": 0-100,
            "final_score": weighted_average,
            "lead_type": "explicit_need" | "hiring" | etc,
            "is_lead": boolean
        }}
        """
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        return parse_scoring(response, lead)
    
    # Run with concurrency limit (12 at a time)
    semaphore = asyncio.Semaphore(12)
    
    async def score_with_limit(lead):
        async with semaphore:
            return await score_one(lead)
    
    results = await asyncio.gather(*[
        score_with_limit(lead) for lead in leads
    ])
    
    return results
```

### Pitch Generation

```python
def generate_pitch(lead_data, tone="professional"):
    """Generate personalized outreach pitch."""
    prompt = f"""
    Generate a personalized outreach pitch for this potential client.
    
    LEAD INFO:
    - Name: {lead_data['full_name']}
    - Company: {lead_data['company']}
    - Post: {lead_data['post_text']}
    - Score: {lead_data['ai_confidence_score']}/100
    
    TONE: {tone}
    
    RULES:
    - Reference their specific post/content
    - Be concise (2-3 paragraphs max)
    - Include a clear call-to-action
    - Don't be salesy or pushy
    - Show understanding of their needs
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.7
    )
    
    return response.choices[0].message.content
```

### Website Quality Analysis

```python
def analyze_website(url):
    """AI-powered website quality scoring."""
    # 1. Crawl website (Scrapling)
    crawler = EnhancedAnalyzer()
    signals = crawler.analyze_website(url)
    
    # 2. AI scoring (gpt-4o)
    prompt = f"""
    Analyze this website and score it across 5 dimensions:
    
    1. CONTENT_QUALITY (0-30): Copy, headlines, value prop
    2. TECHNICAL_SEO (0-25): Meta tags, schema, performance
    3. UX_DESIGN (0-20): Navigation, layout, mobile
    4. TRUST_AUTHORITY (0-15): Reviews, testimonials, contact
    5. AI_SOCIAL_READINESS (0-10): Chat, social proof, AI tools
    
    WEBSITE DATA:
    {json.dumps(signals, indent=2)}
    
    Return JSON:
    {{
        "scores": {{
            "content_quality": 0-30,
            "technical_seo": 0-25,
            "ux_design": 0-20,
            "trust_authority": 0-15,
            "ai_social_readiness": 0-10
        }},
        "total_score": 0-100,
        "category": "hot" | "warm" | "skip",
        "issues": ["list of issues"],
        "recommendations": ["list of recommendations"]
    }}
    """
    
    response = openai_client.chat.completions.create(
        model="gpt-4o",  # Not mini — needs detailed analysis
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=4096
    )
    
    return parse_analysis(response)
```

---

## 3. Supabase Integration

### Client Types

```python
# Anon client — respects RLS
supabase = create_client(url, anon_key)

# Admin client — bypasses RLS
supabase_admin = create_client(url, service_role_key)
```

### Database Operations

All operations use the Supabase Python client directly (no ORM):

```python
# SELECT
result = supabase.table("leads") \
    .select("*") \
    .eq("search_id", search_id) \
    .order("ai_confidence_score", desc=True) \
    .range(0, 19) \
    .execute()

# INSERT
supabase.table("leads").insert({
    "search_id": search_id,
    "user_id": user_id,
    "full_name": "John Smith",
    # ... more fields
}).execute()

# UPDATE
supabase.table("leads") \
    .update({"user_status": "contacted"}) \
    .eq("id", lead_id) \
    .execute()

# DELETE
supabase.table("leads") \
    .delete() \
    .eq("id", lead_id) \
    .execute()

# RPC (stored procedures)
result = supabase.rpc("get_remaining_leads", {
    "p_user_id": user_id
}).execute()
```

### Row Level Security (RLS)

All tables have RLS policies:

```sql
-- Leads table
CREATE POLICY "Users can view own leads" ON leads
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Users can insert own leads" ON leads
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can update own leads" ON leads
    FOR UPDATE USING (user_id = auth.uid());

CREATE POLICY "Users can delete own leads" ON leads
    FOR DELETE USING (user_id = auth.uid());
```

### Auth Flow

```python
# 1. User logs in via frontend (Supabase Auth)
# 2. Frontend gets JWT token
# 3. Frontend sends JWT in Authorization header
# 4. Backend verifies JWT
# 5. Backend uses user_id for DB queries

async def get_current_user(token: str = Depends(oauth2_scheme)):
    # Verify JWT with Supabase
    user = supabase_admin.auth.get_user(token)
    
    # Auto-create free trial on first auth
    existing = supabase_admin.table("user_subscriptions") \
        .select("*") \
        .eq("user_id", user.id) \
        .execute()
    
    if not existing.data:
        # Create free trial
        supabase_admin.table("user_subscriptions").insert({
            "user_id": user.id,
            "plan_id": "trial",
            "status": "active",
            "trial_start": datetime.utcnow().isoformat(),
            "trial_end": (datetime.utcnow() + timedelta(days=7)).isoformat()
        }).execute()
    
    return user
```

---

## 4. Razorpay Integration

### Payment Flow

```
1. Frontend: POST /api/subscriptions/create-order
   → Backend creates Razorpay order
   → Returns order_id

2. Frontend: Opens Razorpay checkout
   → User enters card details
   → Razorpay processes payment
   → Returns payment_signature

3. Frontend: POST /api/subscriptions/verify
   → Backend verifies HMAC-SHA256 signature
   → Activates subscription in DB
   → Returns success

4. Razorpay: POST /api/subscriptions/webhook
   → Backend verifies webhook signature
   → Handles payment.captured
   → Resets daily_usage
```

### Order Creation

```python
async def create_order(plan_id: str, user_id: str):
    # Fetch plan details
    plan = supabase.table("plans") \
        .select("*") \
        .eq("id", plan_id) \
        .single() \
        .execute()
    
    # Convert USD cents to INR paise
    amount_paise = int(plan.data["price_monthly"] * 95.75 * 100)
    
    # Create Razorpay order
    order = razorpay_client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"order_{user_id}_{plan_id}",
        "notes": {
            "user_id": user_id,
            "plan_id": plan_id
        }
    })
    
    return {"order_id": order["id"], "amount": amount_paise}
```

### Payment Verification

```python
async def verify_payment(order_id, payment_id, signature):
    # Verify HMAC-SHA256
    generated_signature = hmac.new(
        razorpay_key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256
    ).hexdigest()
    
    if generated_signature != signature:
        raise HTTPException(400, "Invalid signature")
    
    # Activate subscription
    supabase_admin.table("user_subscriptions").insert({
        "user_id": user_id,
        "plan_id": plan_id,
        "status": "active",
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
        "current_period_start": datetime.utcnow().isoformat(),
        "current_period_end": (datetime.utcnow() + timedelta(days=30)).isoformat()
    }).execute()
    
    return {"success": True}
```

---

## 5. Google Maps Scraper

### Binary Wrapper

```python
def run_maps_scraper(query, location, max_results=25):
    """Run Go binary for Google Maps scraping."""
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        result = subprocess.run(
            [
                settings.scraper_binary_path,
                "-input", query,
                "-results", tmp.name,
                "-exit-on-inactivity", "30s",
                "-depth", "1",
                "-c", "4",  # 4 concurrent workers
                "-email", "true"
            ],
            capture_output=True,
            timeout=300  # 5 minutes
        )
        
        # Parse CSV output
        with open(tmp.name, "r") as f:
            reader = csv.DictReader(f)
            leads = [normalize_row(row) for row in reader]
        
        return leads[:max_results]
```

### Output Format

```csv
name,website,phone,email,address,rating,reviews,category
Acme Corp,https://acme.com,+1-555-0123,info@acme.com,123 Main St,4.5,123,Web Design
```
