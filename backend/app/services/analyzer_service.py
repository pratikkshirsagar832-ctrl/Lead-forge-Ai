"""
Hyperclients — Website Analyzer Service

Orchestrates Scrapling extraction + OpenAI deep analysis.
Flow:
  1. enhanced_analyzer.analyze_website(url) — multi-page crawl + signal extraction (NO scoring)
  2. batch_deep_analyze([data]) — AI quality assessment (PRIMARY scoring engine)
  3. Merge results and return
"""

import logging
from typing import Any

from app.services.enhanced_analyzer import analyze_website as enhanced_analyze
from app.services.deep_analyzer import batch_deep_analyze

logger = logging.getLogger(__name__)


async def analyze_website(url: str) -> dict[str, Any]:
    result = await enhanced_analyze(url)

    if "error" in result.get("raw_analysis", {}):
        return result

    try:
        enriched = await batch_deep_analyze([result])
        if enriched and len(enriched) > 0:
            result = enriched[0]
            ai_res = result.get("ai_analysis", {})
            result["ai_notes"] = {
                "content_quality": ai_res.get("content_quality_notes", ""),
                "technical_issues": ai_res.get("technical_issues_found", []),
                "ux_issues": ai_res.get("ux_issues_found", []),
                "trust_issues": ai_res.get("trust_issues_found", []),
                "recommendation": ai_res.get("recommendation_reason", ""),
            }
    except Exception as e:
        logger.warning(f"AI deep analysis failed for {url}: {e}")

    return result
