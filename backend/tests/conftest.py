"""Shared fixtures + a fake AsyncOpenAI client that returns canned classifications.

This lets us exercise the qualification schema and hard gates deterministically
without a real OpenAI/Apify network round-trip.
"""

import sys
from pathlib import Path

import pytest

# Allow running `pytest` from the repo root or backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import linkedin_pipeline as lp  # noqa: E402


# ── Fake OpenAI async client ───────────────────────────────────────────────
class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoices:
    def __init__(self, content: str):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content: str):
        self.choices = [FakeChoices(content)]


class FakeChatCompletions:
    def __init__(self, responder):
        self.responder = responder

    async def create(self, **kwargs):
        return self.responder(kwargs)


class FakeCompletions:
    def __init__(self, responder):
        self.chat = FakeChatCompletions(responder)


class FakeOpenAI:
    """Minimal AsyncOpenAI stand-in returning pre-baked classifications."""

    def __init__(self, classifications_by_post):
        self.classifications_by_post = classifications_by_post
        self.calls = 0

    def completions(self, responder):
        self._responder = responder
        return FakeCompletions(responder)


# Pydantic schema model re-export for test convenience.
from app.services.ai_service import LeadClassification  # noqa: E402


def make_classification(
    lead_type="agency_wanted",
    intent_strength="explicit",
    service_match=90,
    commercial=85,
    service_relevance="exact",
    decision_maker=True,
    seller=False,
    job_seeker=False,
    location_conf=90,
    quality=88,
    is_qualified=True,
    reason="Explicitly seeking an external agency for web development.",
    evidence="'looking for a web development agency for our ecommerce'",
    rejection_reason="",
):
    return {
        "lead_type": lead_type,
        "intent_strength": intent_strength,
        "is_buying_sourcing": not (seller or job_seeker),
        "is_selling_offering": seller,
        "is_job_seek": job_seeker,
        "service_match_score": service_match,
        "commercial_intent_score": commercial,
        "service_relevance": service_relevance,
        "decision_maker_signal": decision_maker,
        "seller_signal": seller,
        "job_seeker_signal": job_seeker,
        "location_confidence": location_conf,
        "urgency_score": 80,
        "evidence_strength": 85,
        "overall_quality_score": quality,
        "is_qualified": is_qualified,
        "confidence": 0.9,
        "evidence": evidence,
        "reason": reason,
        "rejection_reason": rejection_reason,
    }


def candidate(**overrides):
    base = {
        "full_name": "Acme Corp",
        "headline": "Head of Marketing at Acme",
        "company": "Acme",
        "location": "New York, US",
        "country_code": "US",
        "linkedin_url": "https://www.linkedin.com/in/acme-corp",
        "post_url": "https://www.linkedin.com/feed/update/123",
        "post_text": "We are looking for a web development agency to redesign our ecommerce site.",
        "posted_at": "2026-08-01T00:00:00+00:00",
        "post_id": "123",
    }
    base.update(overrides)
    return base
