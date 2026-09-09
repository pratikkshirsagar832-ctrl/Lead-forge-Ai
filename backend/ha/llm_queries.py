"""LLM query expansion — niche-aware buyer phrasings for the search engine.

One optional DeepSeek call per search generates natural "buyer sentence"
variants for the user's service that deterministic templates cannot know
(e.g. niche vocabulary, how buyers of THIS service actually phrase asks).
Variants are merged at the head of the diversification pool by the engine.

Fail-closed: no key / timeout / invalid JSON / wrong shape -> None / [] and
the engine silently keeps the deterministic template pool. Expansion never
blocks or breaks a search, and its single call counts toward the per-search
DeepSeek ceiling (the classifier exposes `calls` and the engine reads it).
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_EXPANSION_PROMPT = """You write LinkedIn SEARCH QUERIES for finding people who NEED a service.

The user sells: "{service}".
Lead type: {lead_type_label}.

Write {count} short search phrases (3-7 words each) that a genuine BUYER of this
service would plausibly post on LinkedIn when they need it right now:
- natural first-person asks ("need", "looking for", "recommendations", "anyone know")
- use the service's real-world vocabulary and role nouns (how buyers say it)
- vary the intent: urgent asks, project asks, recommendation asks, referral asks
- FORBIDDEN: seller language ("I offer", "we provide", "hire me", "available for"),
  job-ad language ("apply now", "join our team"), generic marketing words,
  hashtags, quotes, or any phrasing where the author SELLS the service.

Return ONLY a JSON object: {{"queries": ["...", "..."]}}"""


def _extract_queries(payload: str | dict | None) -> list[str]:
    """Parse the model response into clean positive query strings."""
    data: object = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(data, dict):
        return []
    raw = data.get("queries")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        q = re.sub(r"\s+", " ", item).strip().strip('"').strip()
        if not (3 <= len(q) <= 80):
            continue
        low = q.lower()
        # Hard seller/keyword guards - a bad variant must never waste SERP calls.
        if any(bad in low for bad in (
            "i offer", "we offer", "we provide", "i provide", "hire me",
            "available for", "apply now", "join our team", "open to work",
            "portfolio", "my services", "dm me for",
        )):
            continue
        if q not in out:
            out.append(q)
    return out[:10]


def make_query_expander(classifier, lead_type: str, service_limit: int = 8):
    """Build the engine's `query_expander` callable from a GptClassifier.

    The classifier's OpenAI-compatible client is reused (same provider/model/
    retry config); the call is counted via the classifier's own `calls`
    counter so the per-search DeepSeek ceiling stays authoritative.
    `lead_type` is the requested buyer bucket ("need_freelancer" | "our_agency").
    Returns a callable (service_text) -> list[str] (possibly empty).
    """

    def expand(service: str) -> list[str]:
        client = getattr(classifier, "_client", None)
        if client is None:
            return []
        label = (
            "an agency seeking outside freelance help for its own client work"
            if lead_type == "our_agency"
            else "someone needing an independent freelancer/contractor for their own project"
        )
        prompt = _EXPANSION_PROMPT.format(
            service=(service or "").strip()[:200],
            lead_type_label=label,
            count=service_limit,
        )
        try:
            classifier.calls += 1
            resp = client.chat.completions.create(
                model=classifier.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed
            log.warning("Query expansion failed (using deterministic pool): %s", exc)
            return []
        queries = _extract_queries(getattr(resp.choices[0].message, "content", None))
        log.info("Query expansion produced %d niche phrasings", len(queries))
        return queries

    return expand
