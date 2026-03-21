"""
LeadForge AI — AI Pitch Service

Generates professional outreach pitches using DeepSeek API.
On-demand only — not called automatically during search pipeline.
"""

import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


async def generate_pitch(
    lead: dict[str, Any],
    analysis: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Generate an outreach pitch for a specific lead.

    Args:
        lead: Lead data dict (business name, category, website, etc.)
        analysis: Optional website analysis data for richer context

    Returns:
        {
            "pitch": str,
            "confidence_score": float,
            "estimated_deal_value": float,
        }
    """
    settings = get_settings()

    if not settings.deepseek_api_key:
        return {
            "pitch": "AI pitch generation is not configured. Please set DEEPSEEK_API_KEY.",
            "confidence_score": 0.0,
            "estimated_deal_value": 0.0,
        }

    prompt = _build_prompt(lead, analysis)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": DEEPSEEK_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a professional sales copywriter helping freelance web developers "
                                "and digital marketing agencies write outreach messages. "
                                "Write concise, professional, and personalized outreach pitches. "
                                "Do NOT sound robotic or generic. Use the business details provided. "
                                "Keep it under 200 words. Include a clear value proposition and call to action."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500,
                },
            )
            response.raise_for_status()
            data = response.json()

        pitch_text = data["choices"][0]["message"]["content"].strip()
        confidence = _calculate_confidence(lead, analysis)
        deal_value = _estimate_deal_value(lead, analysis)

        return {
            "pitch": pitch_text,
            "confidence_score": confidence,
            "estimated_deal_value": deal_value,
        }

    except httpx.TimeoutException:
        logger.error("DeepSeek API timeout")
        return {
            "pitch": "Pitch generation timed out. Please try again.",
            "confidence_score": 0.0,
            "estimated_deal_value": 0.0,
        }
    except Exception as e:
        logger.error(f"Pitch generation failed: {e}")
        return {
            "pitch": f"Pitch generation failed: {str(e)}",
            "confidence_score": 0.0,
            "estimated_deal_value": 0.0,
        }


def _build_prompt(lead: dict, analysis: Optional[dict] = None) -> str:
    """Build the prompt for the AI model."""
    parts = [
        f"Write a professional outreach pitch for this business:\n",
        f"Business Name: {lead.get('business_name', 'Unknown')}",
        f"Category: {lead.get('category', 'N/A')}",
    ]

    if lead.get("full_address"):
        parts.append(f"Location: {lead['full_address']}")

    if lead.get("website_url"):
        parts.append(f"Website: {lead['website_url']}")
    else:
        parts.append("Website: No website found")

    if lead.get("rating"):
        parts.append(f"Google Rating: {lead['rating']} ({lead.get('total_reviews', 0)} reviews)")

    if lead.get("phone"):
        parts.append(f"Phone: {lead['phone']}")

    # Add website analysis context if available
    if analysis:
        issues = analysis.get("issues", [])
        score = analysis.get("overall_score", None)
        if score is not None:
            parts.append(f"\nWebsite Health Score: {score}/100")
        if issues:
            parts.append("Website Issues Found:")
            for issue in issues[:5]:
                parts.append(f"  - {issue}")

    parts.append(
        "\nWrite a concise, professional pitch that:"
        "\n- Acknowledges their business specifically"
        "\n- Mentions specific website issues or opportunities if available"
        "\n- Offers a clear value proposition (web development, redesign, or digital marketing)"
        "\n- Has a friendly but professional call to action"
        "\n- Is suitable for email or LinkedIn outreach"
    )

    return "\n".join(parts)


def _calculate_confidence(lead: dict, analysis: Optional[dict] = None) -> float:
    """
    Calculate a confidence score (0.0-1.0) based on available data.
    Higher score = more likely to convert.
    """
    score = 0.5  # Base

    # No website = likely needs one
    if not lead.get("website_url"):
        score += 0.2

    # Has analysis with issues
    if analysis:
        issue_count = len(analysis.get("issues", []))
        if issue_count > 3:
            score += 0.15
        elif issue_count > 1:
            score += 0.1

        web_score = analysis.get("overall_score", 50)
        if web_score < 30:
            score += 0.15
        elif web_score < 50:
            score += 0.1

    # Has reviews but low rating
    reviews = lead.get("total_reviews", 0)
    rating = lead.get("rating", 0)
    if reviews > 10 and rating and rating < 4.0:
        score += 0.05

    # Has phone = contactable
    if lead.get("phone"):
        score += 0.05

    return min(1.0, round(score, 2))


def _estimate_deal_value(lead: dict, analysis: Optional[dict] = None) -> float:
    """
    Estimate potential deal value based on business signals.
    Returns a rough USD value.
    """
    base_value = 500.0

    # No website = full build opportunity
    if not lead.get("website_url"):
        base_value = 2000.0
    elif analysis:
        issue_count = len(analysis.get("issues", []))
        if issue_count > 4:
            base_value = 1500.0
        elif issue_count > 2:
            base_value = 1000.0

    # Good reviews suggest established business
    reviews = lead.get("total_reviews", 0)
    if reviews > 100:
        base_value *= 1.5
    elif reviews > 50:
        base_value *= 1.3
    elif reviews > 20:
        base_value *= 1.1

    return round(base_value, 2)
