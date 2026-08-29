"""
Hyperclients — Deep Website Analyzer

Takes Scrapling-extracted site signals, sends to OpenAI,
and returns AI-assessed scores, issues, and recommendations.
This is the PRIMARY scoring engine — no rule-based scoring involved.
"""

import json
import logging
import re

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 5

SYSTEM_PROMPT = """You are a senior website quality auditor and SEO specialist. Your job is to analyze website data extracted from live pages and provide deep, actionable assessments.

For each website provided, evaluate these dimensions and return a JSON assessment:

## Evaluation Dimensions

### 1. CONTENT QUALITY (0-30 points)
- Is the content valuable, well-written, and original? Or thin/generic?
- Does it serve clear search intent?
- Is there a clear value proposition above the fold?
- How is the writing quality (grammar, tone, clarity)?
- Is the content fresh or outdated?
- Check visible_text_length, has_value_proposition, pages_crawled count

### 2. TECHNICAL SEO (0-25 points)
- Are title tags and meta descriptions well-optimized?
- Is there proper heading hierarchy (check headings data)?
- Are internal links well-structured (check internal_links vs external_links)?
- Is the page loading efficiently based on page_size_kb?
- Are canonical URLs, hreflang, and language tags handled correctly?
- Check has_viewport, has_favicon, is_https, sitemap_found, robots_txt_found

### 3. USER EXPERIENCE & DESIGN (0-20 points)
- Is the design modern and professional?
- Is navigation clear and intuitive? (check has_navigation, framework)
- Are CTAs visible and compelling? (check cta_text_found, cta_button_count, form_count)
- Is there a clear conversion path?
- Is the site mobile-friendly? (check has_viewport)
- Check has_custom_404, has_autoplay_media, has_aggressive_popup

### 4. TRUST & AUTHORITY SIGNALS (0-15 points)
- Is there a privacy policy, terms, about page?
- Are there testimonials, case studies, or social proof? (check has_testimonials)
- Is contact information visible? (check emails_count, phones_count, has_live_chat)
- Are there security signals (SSL, trust badges)? (check is_https)
- Check has_footer, has_cookie_consent, schema_types, business_info

### 5. AI & SOCIAL READINESS (0-10 points)
- Is the content structured for AI extraction (FAQ schema, clear answers)?
- Are Open Graph and Twitter Card tags properly set?
- Is analytics (GA4/GTM) present? (check has_analytics)
- Is there a sitemap and robots.txt allowing crawlers?
- Check social_platforms, social_count

## Output Format
Return a JSON array. For each website, include:
```json
{
  "url": "<website URL>",
  "content_quality_score": <0-30>,
  "technical_seo_score": <0-25>,
  "ux_score": <0-20>,
  "trust_score": <0-15>,
  "ai_readiness_score": <0-10>,
  "total_score": <0-100>,
  "content_quality_notes": "<brief note>",
  "technical_issues_found": ["<issue1>", "<issue2>"],
  "ux_issues_found": ["<issue1>"],
  "trust_issues_found": ["<issue1>"],
  "missing_features": ["<feature1>"],
  "recommended_category": "hot|warm|skip",
  "recommendation_reason": "<why this category>"
}
```

Scoring for recommended_category:
- hot (0-39): Serious issues, needs complete overhaul or has no real website
- warm (40-69): Has a site but significant room for improvement
- skip (70-100): Good website, low opportunity for web development services

Be strict but fair. A small local business site should be judged against reasonable expectations for its type, not against Fortune 500 standards.

IMPORTANT: Use the Scrapling-extracted signals to inform your assessment. If the site has HTTPS, proper meta tags, good content, structured data, etc., give appropriate credit."""  # noqa: E501


def _get_openai_client() -> OpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return OpenAI(api_key=settings.openai_api_key)


async def batch_deep_analyze(sites_data: list[dict]) -> list[dict]:
    """
    Take a batch of Scrapling extraction results and run deep analysis via OpenAI.
    Returns enhanced results with AI-assessed scores and findings.
    """
    if not sites_data:
        return []

    client = _get_openai_client()
    if not client:
        logger.warning("OpenAI API key not set — skipping deep analysis")
        return sites_data

    all_enhanced: list[dict] = []

    for i in range(0, len(sites_data), BATCH_SIZE):
        batch = sites_data[i : i + BATCH_SIZE]
        try:
            enhanced = await _call_openai_batch(client, batch)
            all_enhanced.extend(enhanced)
        except Exception as e:
            logger.error(f"Deep analysis batch {i // BATCH_SIZE} failed: {e}")
            all_enhanced.extend(batch)

    return all_enhanced


async def _call_openai_batch(client: OpenAI, batch: list[dict]) -> list[dict]:
    """Send a batch of site data to OpenAI and parse the response."""
    sites_json = []
    for site in batch:
        raw = site.get("raw_analysis", {})
        sites_json.append({
            "url": raw.get("final_url", site.get("url", "")),
            "title": raw.get("title", ""),
            "meta_description": raw.get("meta_description", ""),
            "framework": raw.get("framework", "unknown"),
            "language": raw.get("language", ""),
            "page_size_kb": raw.get("page_size_kb", 0),
            "visible_text_length": raw.get("visible_text_length", 0),
            "has_viewport": raw.get("has_viewport", False),
            "is_https": raw.get("is_https", False),
            "headings": raw.get("headings", {}),
            "internal_links": raw.get("internal_links", 0),
            "external_links": raw.get("external_links", 0),
            "total_images": raw.get("total_images", 0),
            "images_without_alt": raw.get("images_without_alt", 0),
            "social_platforms": raw.get("social_platforms", []),
            "social_count": raw.get("social_count", 0),
            "has_structured_data": raw.get("has_structured_data", False),
            "schema_types": raw.get("schema_types", []),
            "has_analytics": raw.get("has_analytics", False),
            "has_cookie_consent": raw.get("has_cookie_consent", False),
            "form_count": raw.get("form_count", 0),
            "cta_button_count": raw.get("cta_button_count", 0),
            "has_navigation": raw.get("has_navigation", False),
            "has_footer": raw.get("has_footer", False),
            "has_favicon": raw.get("has_favicon", False),
            "sitemap_found": raw.get("sitemap_found", False),
            "robots_ai_bots_blocked": raw.get("robots_ai_bots_blocked", []),
            "has_testimonials": raw.get("has_testimonials", False),
            "has_live_chat": raw.get("has_live_chat", False),
            "has_pricing_page": raw.get("has_pricing_page", False),
            "cta_text_found": raw.get("cta_text_found", False),
            "has_value_proposition": raw.get("has_value_proposition", False),
            "has_custom_404": raw.get("has_custom_404", None),
            "has_autoplay_media": raw.get("has_autoplay_media", False),
            "has_aggressive_popup": raw.get("has_aggressive_popup", False),
            "has_aria_attributes": raw.get("has_aria_attributes", False),
            "page_count": raw.get("page_count", 0),
            "emails_count": raw.get("emails_count", 0),
            "phones_count": raw.get("phones_count", 0),
            "business_info": raw.get("business_info", {}),
            "scrapling_issues": site.get("issues", []),
        })

    user_prompt = (
        "Analyze these websites for quality and opportunity assessment.\n"
        "Score each site independently based on the extracted signals.\n"
        f"Return a JSON array with {len(sites_json)} entries, one per site in the same order.\n\n"
        f"WEBSITES DATA:\n{json.dumps(sites_json, indent=2)}"
    )

    import asyncio
    loop = asyncio.get_event_loop()

    resp = await loop.run_in_executor(
        None,
        lambda: client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=4096,
        ),
    )

    text = resp.choices[0].message.content if resp.choices and resp.choices[0].message.content else "[]"
    json_str = _extract_json(text)
    ai_results: list[dict] = json.loads(json_str)

    if isinstance(ai_results, dict):
        ai_results = [ai_results]

    merged = []
    for site, ai_result in zip(batch, ai_results):
        enhanced = dict(site)
        enhanced["ai_analysis"] = ai_result
        enhanced["ai_score"] = ai_result.get("total_score", 50)

        ai_score = ai_result.get("total_score", 50)
        enhanced["overall_score"] = max(0, min(100, ai_score))

        ai_cat = ai_result.get("recommended_category", "")
        if ai_cat in ("hot", "warm", "skip"):
            enhanced["category"] = ai_cat
        else:
            enhanced["category"] = _categorize(enhanced["overall_score"])

        all_issues = list(site.get("issues", []))
        for key in ("technical_issues_found", "ux_issues_found", "trust_issues_found", "missing_features"):
            for issue in ai_result.get(key, []):
                if issue and issue not in all_issues:
                    all_issues.append(issue)
        enhanced["issues"] = all_issues

        merged.append(enhanced)

    return merged


def _extract_json(text: str) -> str:
    """Extract JSON array from text that may contain markdown code blocks."""
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '[':
            if start == -1:
                start = i
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0 and start != -1:
                return text[start:i+1]
    return text


def _categorize(score: int) -> str:
    if score <= 39:
        return "hot"
    elif score <= 69:
        return "warm"
    return "skip"
