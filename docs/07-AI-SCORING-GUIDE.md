# 07 — AI SCORING & QUALIFICATION GUIDE

## Complete AI Pipeline Deep Dive

Lead Forge AI uses a **two-stage AI pipeline** to qualify and score leads. This document explains every detail of how leads are evaluated.

---

## Pipeline Overview

```
Raw LinkedIn/Maps Posts (50-200)
            ↓
┌─────────────────────────────────────────┐
│  STAGE 1: TRIAGE (Cheap Filter)        │
│  Model: gpt-4o-mini                     │
│  Cost: ~$0.001 per batch                │
│  Purpose: Quick binary classification   │
│  Output: is_lead + lead_type            │
└─────────────────────────────────────────┘
            ↓
Filtered Candidates (10-50)
            ↓
┌─────────────────────────────────────────┐
│  STAGE 2: DEEP SCORING (Precision)     │
│  Model: gpt-4o-mini                     │
│  Cost: ~$0.002 per lead                 │
│  Purpose: 6-dimension scoring           │
│  Output: 0-100 score + detailed breakdown│
└─────────────────────────────────────────┘
            ↓
Scored Leads (5-30)
            ↓
┌─────────────────────────────────────────┐
│  STAGE 3: TIERED ACCEPTANCE             │
│  Purpose: Select best leads             │
│  Output: Final accepted leads           │
└─────────────────────────────────────────┘
```

---

## Stage 1: Triage

### Purpose
Quickly filter out obvious non-leads (sellers, content posts, irrelevant) before expensive deep scoring.

### Implementation

```python
async def triage_candidates_async(candidates: list[dict]) -> list[dict]:
    """Stage 1: Cheap binary classification."""
    
    # Split into batches of 20
    batches = [candidates[i:i+20] for i in range(0, len(candidates), 20)]
    
    async def triage_batch(batch):
        # Build prompt with all posts
        posts_text = "\n\n".join([
            f"POST {i+1}:\n"
            f"Content: {post['post_text'][:500]}\n"
            f"Author: {post['headline']}\n"
            f"Company: {post['company']}\n"
            f"Location: {post['location']}"
            for i, post in enumerate(batch)
        ])
        
        prompt = f"""
You are a lead qualification expert. Analyze these LinkedIn posts and determine 
which ones represent genuine BUYING INTENT or HIRING signals for freelancers/agency services.

POSTS TO ANALYZE:
{posts_text}

For EACH post, classify it as:

**LEAD TYPES (is_lead = true):**
- "explicit_need": "We need X", "Looking for someone to do X", "Hiring a freelancer for X"
- "problem_awareness": "Our website isn't converting", "We're struggling with X"
- "research": "Anyone know a good X?", "Recommendations for X?"
- "hiring": Job posting, "We're hiring X", "Join our team as X"

**NON-LEAD TYPES (is_lead = false):**
- "seller": "I offer X services", "Available for hire as X", "Check my portfolio"
- "irrelevant": Tips, opinions, articles, celebrations, general posts
- "job_seeker": "Looking for work", "Open to opportunities", "Seeking X role"

Return a JSON object with this structure:
{{
    "results": [
        {{
            "post_index": 1,
            "is_lead": true/false,
            "lead_type": "explicit_need|problem_awareness|research|hiring|seller|irrelevant|job_seeker",
            "confidence": 0.0-1.0,
            "reason": "Brief explanation"
        }},
        ...
    ]
}}

Be CONSERVATIVE - only mark as lead if there's CLEAR buying intent or hiring signal.
"I'm a freelance X" = SELLER (reject).
"Looking for a freelance X" from company = BUYER (accept).
"""
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1  # Low temperature for consistent results
        )
        
        return json.loads(response.choices[0].message.content)
    
    # Run batches with concurrency limit (5 at a time)
    semaphore = asyncio.Semaphore(5)
    
    async def triage_with_limit(batch):
        async with semaphore:
            return await triage_batch(batch)
    
    results = await asyncio.gather(*[
        triage_with_limit(batch) for batch in batches
    ])
    
    # Flatten and filter
    all_results = []
    for batch_result in results:
        all_results.extend(batch_result.get("results", []))
    
    # Only keep leads
    leads = []
    for candidate, result in zip(candidates, all_results):
        if result.get("is_lead", False):
            candidate["triage_result"] = result
            leads.append(candidate)
    
    return leads
```

### Triage Prompt Breakdown

The prompt instructs the AI to:

1. **Read each post carefully** — understand the context
2. **Classify by lead type** — 4 lead types + 3 non-lead types
3. **Apply strict rules** — "I'm a freelance X" = seller (reject)
4. **Return structured JSON** — consistent format for parsing

### Example Triage Results

```json
{
    "results": [
        {
            "post_index": 1,
            "is_lead": true,
            "lead_type": "explicit_need",
            "confidence": 0.92,
            "reason": "Company clearly states they need a website developer for a project"
        },
        {
            "post_index": 2,
            "is_lead": false,
            "lead_type": "seller",
            "confidence": 0.88,
            "reason": "Author is offering web design services, not seeking them"
        },
        {
            "post_index": 3,
            "is_lead": true,
            "lead_type": "hiring",
            "confidence": 0.95,
            "reason": "Job posting for full-time developer - high value lead"
        }
    ]
}
```

---

## Stage 2: Deep Scoring

### Purpose
Score each lead across 6 dimensions to determine quality and priority.

### The 6 Dimensions

| Dimension | Weight | Description | Scoring Guide |
|-----------|--------|-------------|---------------|
| **Intent** | 30% | How clear is the buying/hiring signal? | 100 = "We need X immediately"; 50 = "Considering X"; 0 = No signal |
| **Fit** | 20% | Does this match the target niche? | 100 = Perfect niche match; 50 = Related; 0 = Unrelated |
| **Urgency** | 15% | How urgently do they need help? | 100 = "URGENT"; 50 = "This quarter"; 0 = "Sometime this year" |
| **Engagement** | 10% | Post reactions/comments | 100 = 100+ reactions; 50 = 20 reactions; 0 = 0 reactions |
| **Recency** | 10% | How recent is the post? | 100 = Today; 50 = This week; 0 = This month |
| **Decision-Maker** | 15% | Is the author a decision-maker? | 100 = CEO/Founder; 50 = Manager; 0 = Employee |

### Implementation

```python
async def qualify_leads_with_ai_async(leads: list[dict]) -> list[dict]:
    """Stage 2: Deep 6-dimension scoring."""
    
    async def score_one(lead: dict) -> dict:
        prompt = f"""
You are an expert lead qualification analyst. Score this LinkedIn post across 
6 dimensions to determine if it's a high-quality lead for freelancers/agencies.

POST DETAILS:
- Content: {lead.get('post_text', '')[:1000]}
- Author: {lead.get('full_name', '?')}
- Headline: {lead.get('headline', '?')}
- Company: {lead.get('company', '?')}
- Location: {lead.get('location', '?')}
- Reactions: {lead.get('engagement_score', 0)}
- Comments: {lead.get('comment_count', 0)}

SCORING DIMENSIONS (0-100 each):

1. INTENT (30% weight) - How clear is the buying/hiring signal?
   - 100: "We need to hire a website developer immediately"
   - 80: "Looking for a freelancer to help with our website"
   - 60: "Considering a website redesign"
   - 40: "Our website could use some improvements"
   - 20: "Anyone know a good web developer?"
   - 0: No buying signal at all

2. FIT (20% weight) - How well does this match the target niche?
   - 100: Exact niche match (e.g., "need website development" for web dev)
   - 80: Very related (e.g., "need landing page" for web dev)
   - 60: Somewhat related (e.g., "need digital marketing" for web dev)
   - 40: Loosely related (e.g., "need business consulting")
   - 0: Completely unrelated

3. URGENCY (15% weight) - How urgently do they need help?
   - 100: "URGENT", "ASAP", "immediately"
   - 80: "This week", "by end of month"
   - 60: "This quarter", "soon"
   - 40: "This year", "planning for next quarter"
   - 20: "Eventually", "no rush"
   - 0: No urgency mentioned

4. ENGAGEMENT (10% weight) - How much engagement does the post have?
   - 100: 100+ reactions, 50+ comments
   - 80: 50+ reactions, 20+ comments
   - 60: 20+ reactions, 10+ comments
   - 40: 10+ reactions, 5+ comments
   - 20: 5+ reactions, 1+ comments
   - 0: 0 reactions, 0 comments

5. RECENCY (10% weight) - How recent is the post?
   - 100: Posted today
   - 80: Posted in last 3 days
   - 60: Posted this week
   - 40: Posted in last 2 weeks
   - 20: Posted this month
   - 0: Posted more than a month ago

6. DECISION-MAKER (15% weight) - Is the author a decision-maker?
   - 100: CEO, Founder, Owner, Co-founder
   - 80: VP, Director, Head of Department
   - 60: Manager, Team Lead
   - 40: Senior Employee
   - 20: Employee
   - 0: Intern, Student, Unknown

CALCULATE FINAL SCORE:
final_score = (intent × 0.30) + (fit × 0.20) + (urgency × 0.15) + 
              (engagement × 0.10) + (recency × 0.10) + (decision_maker × 0.15)

LEAD TYPE CLASSIFICATION:
- "explicit_need": Clear "we need X" statement
- "problem_awareness": Describes a problem they're facing
- "research": Asking for recommendations
- "hiring": Job posting or "we're hiring"
- "seller": Offering services (REJECT)
- "irrelevant": Not a lead (REJECT)

Return JSON:
{{
    "intent": 0-100,
    "fit": 0-100,
    "urgency": 0-100,
    "engagement": 0-100,
    "recency": 0-100,
    "decision_maker": 0-100,
    "final_score": 0-100,
    "lead_type": "explicit_need|problem_awareness|research|hiring|seller|irrelevant",
    "is_lead": true/false,
    "reasoning": "Brief explanation of scoring"
}}
"""
        
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2  # Low temperature for consistency
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Validate and clamp scores
        for key in ["intent", "fit", "urgency", "engagement", "recency", "decision_maker"]:
            result[key] = max(0, min(100, result.get(key, 0)))
        
        # Recalculate final score to ensure consistency
        result["final_score"] = (
            result["intent"] * 0.30 +
            result["fit"] * 0.20 +
            result["urgency"] * 0.15 +
            result["engagement"] * 0.10 +
            result["recency"] * 0.10 +
            result["decision_maker"] * 0.15
        )
        
        # Merge with lead data
        lead.update({
            "ai_score": result["final_score"],
            "ai_intent": result["intent"],
            "ai_fit": result["fit"],
            "ai_urgency": result["urgency"],
            "ai_engagement": result["engagement"],
            "ai_recency": result["recency"],
            "ai_decision_maker": result["decision_maker"],
            "lead_type": result["lead_type"],
            "is_lead": result["is_lead"],
            "ai_reasoning": result.get("reasoning", "")
        })
        
        return lead
    
    # Run with concurrency limit (12 at a time)
    semaphore = asyncio.Semaphore(12)
    
    async def score_with_limit(lead):
        async with semaphore:
            return await score_one(lead)
    
    results = await asyncio.gather(*[
        score_with_limit(lead) for lead in leads
    ])
    
    return [r for r in results if r is not None]
```

### Scoring Example

**Input Post:**
```
"We're looking for a freelance web developer to help redesign our corporate website. 
Our current site isn't converting well and we need someone experienced with React 
and modern design. Budget is flexible for the right candidate. Please DM if interested."
```

**Author:** "Marketing Director at TechCorp"

**AI Output:**
```json
{
    "intent": 92,
    "fit": 95,
    "urgency": 75,
    "engagement": 45,
    "recency": 80,
    "decision_maker": 85,
    "final_score": 84.2,
    "lead_type": "explicit_need",
    "is_lead": true,
    "reasoning": "Clear hiring signal from Marketing Director. Company needs website redesign with specific tech requirements. Good engagement indicates genuine interest."
}
```

---

## Stage 3: Tiered Acceptance

### Purpose
Select the best leads based on score thresholds and user filters.

### Tier System

```python
# Tier 1: Strict (score ≥ 80)
# Tier 2: Medium (score ≥ 65)
# Tier 3: Relaxed (score ≥ 50)

def tier_filter(scored_leads, lead_types, country_mode, req_country_codes):
    """Apply tiered acceptance with country and type gates."""
    
    accepted = []
    last_scored_candidates = []  # Track for relaxation
    
    for lead in scored_leads:
        score = lead.get("ai_score", 0)
        lead_type = lead.get("lead_type", "")
        
        # Type gate: only accept allowed types
        if lead_types and lead_type not in lead_types:
            continue
        
        # Country gate
        if not _country_ok(lead, country_mode, req_country_codes):
            continue
        
        # Track all scored candidates
        last_scored_candidates.append(lead)
        
        # Tier 1: Strict
        if score >= 80:
            accepted.append(lead)
            continue
        
        # Tier 2: Medium
        if score >= 65:
            accepted.append(lead)
            continue
        
        # Tier 3: Relaxed
        if score >= 50:
            accepted.append(lead)
            continue
    
    return accepted, last_scored_candidates
```

### Final Relaxation Pass

After all waves, if still under requested count:

```python
# Relaxation: score ≥ 50, any country, any type
final_relaxation = [
    l for l in last_scored_candidates
    if l["ai_score"] >= 50
    and _country_ok(l, country_mode, req_country_codes)
    and _type_ok(l, allowed_types_set)
]
```

---

## Lead Categories

### Hot Leads (Score ≥ 85)

- High intent + good fit + decision-maker
- Immediate outreach recommended
- Displayed with 🔥 badge

### Warm Leads (Score 50-84)

- Moderate intent or fit
- Worth following up
- Displayed with 🟡 badge

### Rejected (Score < 50)

- Not qualified
- Not saved to database

---

## Cost Analysis

### Per Search (10 leads requested)

| Stage | API Calls | Tokens | Cost |
|-------|-----------|--------|------|
| Triage | 3 batches | ~6,000 | $0.001 |
| Deep Scoring | 12 calls | ~12,000 | $0.002 |
| Pitch Generation | 10 calls | ~5,000 | $0.001 |
| **Total** | **25 calls** | **~23,000** | **$0.004** |

### Monthly Estimates (100 searches/month)

| Usage | API Calls | Tokens | Cost |
|-------|-----------|--------|------|
| 100 searches | 2,500 | 2.3M | $0.40 |
| 500 searches | 12,500 | 11.5M | $2.00 |

---

## Prompt Engineering Details

### Temperature Settings

| Stage | Temperature | Why |
|-------|-------------|-----|
| Triage | 0.1 | Consistent binary decisions |
| Deep Scoring | 0.2 | Consistent scoring |
| Pitch Generation | 0.7 | Creative but grounded |

### Response Format

All AI calls use `response_format={"type": "json_object"}` for:
- Consistent parsing
- No markdown/text artifacts
- Reliable JSON extraction

### Error Handling

```python
try:
    response = await openai_client.chat.completions.create(...)
    result = json.loads(response.choices[0].message.content)
except json.JSONDecodeError:
    # Fallback: try to extract JSON from text
    result = extract_json_from_text(response.choices[0].message.content)
except openai.RateLimitError:
    # Wait and retry
    await asyncio.sleep(2)
    return await score_one(lead)  # Recursive retry
```
