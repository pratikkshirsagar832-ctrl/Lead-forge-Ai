"""
Hyperclients — AI Services

Generates professional outreach pitches/website messages using OpenAI, and
(primary) the LinkedIn LEAD QUALIFICATION BRAIN.

The LinkedIn qualification system is the authoritative classification engine:
  - triage: cheap keep/reject of obvious non-intent posts
  - classify: structured, evidence-based, intent-direction-aware classification

FAIL-CLOSED: if the AI is unavailable or fails, a candidate is NEVER fabricated
a qualification. Unverified candidates are dropped from strict results.
"""

import asyncio
import json
import logging
from typing import Any, Optional

from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)

PITCH_MODEL = "gpt-4o-mini"
MESSAGE_MODEL = "gpt-4o-mini"
TRIAGE_MODEL = "gpt-4o-mini"
CLASSIFY_MODEL = "gpt-4o-mini"

TRIAGE_CONCURRENCY = 8
CLASSIFY_CONCURRENCY = 10
MAX_RETRIES = 3
TRIAGE_BATCH_SIZE = 3  # small batches; each candidate gets a structured verdict


def _get_openai_client() -> OpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return OpenAI(api_key=settings.openai_api_key)


def _get_async_openai_client() -> AsyncOpenAI | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    return AsyncOpenAI(api_key=settings.openai_api_key)


# ══════════════════════════════════════════════════════════════════════════
# LINKEDIN LEAD QUALIFICATION BRAIN
# ══════════════════════════════════════════════════════════════════════════

QUALIFY_LABELS = ("freelancer_needed", "hiring", "agency_wanted", "irrelevant")
INTENT_LABELS = ("explicit", "active_search", "recommendation", "problem_awareness", "research", "none")


class LeadClassification(BaseModel):
    """Validated structured classification for one LinkedIn candidate.

    This is THE schema the model must emit. Any invalid/retried response is
    rejected; repeated failure means the candidate is NOT qualified (fail-closed).
    """

    lead_type: str = Field(...)
    intent_strength: str = Field(...)
    is_buying_sourcing: bool = Field(False)
    is_selling_offering: bool = Field(False)
    is_job_seek: bool = Field(False)
    service_match_score: float = Field(0, ge=0, le=100)
    commercial_intent_score: float = Field(0, ge=0, le=100)
    service_relevance: str = Field(..., description="exact | equivalent | adjacent | unrelated")
    decision_maker_signal: bool = Field(False)
    seller_signal: bool = Field(False)
    job_seeker_signal: bool = Field(False)
    location_confidence: float = Field(0, ge=0, le=100)
    urgency_score: float = Field(0, ge=0, le=100)
    evidence_strength: float = Field(0, ge=0, le=100)
    overall_quality_score: float = Field(0, ge=0, le=100)
    is_qualified: bool = Field(False)
    confidence: float = Field(0, ge=0, le=1)
    evidence: str = Field(...)
    reason: str = Field(...)
    rejection_reason: str = Field("")

    def canonical_lead_type(self) -> str:
        lt = (self.lead_type or "").strip().lower()
        aliases = {
            "explicit_need": "freelancer_needed", "problem_awareness": "freelancer_needed",
            "research": "freelancer_needed", "agency": "agency_wanted", "buyer": "freelancer_needed",
            "freelancer": "freelancer_needed", "freelancer_needed": "freelancer_needed",
        }
        if lt in aliases:
            return aliases[lt]
        if lt in ("hiring", "agency_wanted"):
            return lt
        return "irrelevant"

    def canonical_intent_strength(self) -> str:
        s = (self.intent_strength or "").strip().lower()
        return s if s in INTENT_LABELS else "none"


QUALIFY_SYSTEM_PROMPT = """You are a precision B2B sales-intent analyst. Your ONLY output is a judgment of whether the SUPPLIED EVIDENCE proves the author is ACTIVELY seeking the requested service/provider for a real engagement NOW.

MISSION: Answer "does the evidence show this person/company is trying to obtain the requested service from an external provider?" NOT "does this post mention something related?" Precision > recall. A false positive damages the product trust more than a missed lead.

ROLE PLAY: You read LinkedIn posts as a consultant who has been asked to hand the sales team a shortlist of genuinely prospectable companies. You are skeptical. You require concrete evidence. You never invent intent.

═══════════════════════════════════════════════════════════════
1. DIRECTION OF INTENT — THE DOMINANT QUESTION
═══════════════════════════════════════════════════════════════
Decide WHO NEEDS vs WHO OFFERS. This decides almost everything.

BUYING / SOURCING (candidate lead):
"We're looking for a web development agency." | "We need a developer to build our site." | "Can anyone recommend a good graphic designer?" | "We're hiring a React developer." | "Need someone to handle our SEO." | "Looking for an agency to redesign our site." | "Need a contractor for a 3-month website build."

SELLING / OFFERING (NEVER a lead) — the author provides the service:
"We are a web development agency." | "We help companies build websites." | "DM me if you need a website." | "I'm a freelance designer looking for clients." | "I offer design services." | "Available for new projects." | "My services include..." | "We specialize in..."
SUBTLER SELLING (still NEVER a lead) — the author is pitching their own capability:
- White-label / OEM / partner-selling: "White label software agency for web dev agencies." | "We're a white-label partner for agencies — you resell, we build." | "Helping you deliver more without hiring." | "We act as your dedicated offshore team."
- Value-pitch framing: "We'd love to help you scale." | "Let's partner together." | "Book a call / free consultation to see how we can help." | "Send us a brief and we'll quote you."
- Supply-side pitch to agencies (author offers data/service TO agencies, not seeks one): "If you're a marketing agency looking to expand your client pipeline, I have a curated database of leads available. Best for cold calling. Comment 'LEADS' or DM me." | "I have a vetted list of high-paying clients for agencies." | "I sell lead lists for agencies." — the author is the SUPPLIER, the agencies are the customer. This is SELLING, never agency_wanted.
KEY RULE: if the author is offering to do the work, or inviting the reader to become a client, it is SELLING regardless of whether the literal words "I/we offer" appear. Read for the DIRECTION: who would be the customer? If the AUTHOR is the provider, it is a seller.

JOB SEEKER (NEVER a lead) — the author wants employment for themselves:
"I'm a React developer looking for a job." | "Looking for a role." | "Seeking employment." | "#opentowork." | "I'm a freelance graphic designer available for projects." | "I'm taking on new clients." | "As a freelancer, I'm open to remote work."

TALENT MARKETPLACE / PLATFORM (NEVER a lead) — a company/pool RECRUITING freelancers on behalf of clients, or a marketplace building a talent vetted-pool:
"Toptal is seeking talented freelancers worldwide." | "Applications are now open — we place designers with our clients." | "We're building a vetted freelance network." | "Looking for freelancers to join our talent marketplace/sign up today."
These are a SUPPLY-side marketplace, NOT a company that needs a freelancer for itself. The author is not your potential client — they are a competitor/supplier aggregator. NEVER a freelancer_needed or hiring lead.

RECRUITING-SELLER (NEVER a lead) — a staffing/talent agency placing candidates at THIRD-PARTY clients:
"We place candidates with clients." | "Staffing agency availability." | "Talent partner for hiring teams."
EXCEPTION: a firm building its OWN pool of experts for its OWN projects ("building a team of freelancers for our client work") is a BUYER (it sources talent to deliver its own work) — classify that as hiring.

CONTENT / THOUGHT-LEADERSHIP (NEVER a lead):
"5 tips to improve SEO." | "Why you need a website." | "Trends in web design." | "Case study." | "My opinion on..."

═══════════════════════════════════════════════════════════════
2. LEAD-TYPE DEFINITIONS — assign EXACTLY one label
═══════════════════════════════════════════════════════════════
- freelancer_needed: author wants an INDEPENDENT freelancer/contractor/individual to do the work.
- hiring: author is recruiting a specific role for their OWN organization (remote/contract/part-time/full-time are all hiring). A job seeker or a recruiting-seller is NEVER hiring.
- agency_wanted: author wants to bring in an EXTERNAL AGENCY/studio/firm/team to handle the service. The word "agency" is NOT sufficient. There must be an explicit act of sourcing an external provider. "We are an agency" is a seller, never agency_wanted. A neutral mention of agencies ("agencies are struggling") is content, never agency_wanted.

AGENCY_WANTED TRAPS — these are NOT agency_wanted (all are common and all are rejected):
1. A CREATOR/candidate seeking a TALENT AGENCY to REPRESENT THEMSELVES ("seeking talent agency representation", "looking for an agency to represent me", "I'm available for agency representation") — the author IS the product being sold; they are SEEKING WORK, not sourcing a provider for their company. This is SELLING/job-seeking, NEVER agency_wanted.
2. An AGENCY PROMOTING ITSELF ("reach out to our agency", "our growth agency can help", "email us at X agency") — the author is the provider, the reader is the client. SELLER.
3. "HOW TO CHOOSE / HOW TO VET AGENCIES" ADVICE ("Hiring a marketing agency? Ask this question first", "choosing an agency is complicated", "what to look for in an agency") — THOUGHT-LEADERSHIP/content, no procurement action. NEVER a lead.
4. An agency describing its services to attract clients ("we help RIA firms with SEO", "our agency specializes in X") — SELLER.

RULE: agency_wanted requires the author (a company/person) to be the SEEKER who wants to CONTRACT an external agency to do work FOR THEM. If the author is a provider, a creator seeking representation, or just giving advice, it is NOT agency_wanted.
- irrelevant: anything lacking genuine sourcing/hiring intent.

CRITICAL DISTINCTION — the trap that causes most errors:
  "We are/our agency provides X"  → SELLER (reject)
  "Looking for/need an X agency"  → AGENCY_WANTED (qualify)
  "Looking for a freelance X"     → FREELANCER_NEEDED
  "We're hiring an X [employee]"  → HIRING (for their own team)

THE HIRING vs AGENCY_WANTED BOUNDARY (high-error zone):
- If the author is sourcing an EXTERNAL AGENCY/studio/firm/team to deliver the work, and there is NO in-house role being filled → agency_wanted. Examples: "looking for a web dev agency", "need an agency to redesign our site", "searching for an external team to build our app", "recommend a good branding agency", "we need to hire an agency for our marketing".
- If the author is filling a ROLE (an employee/contractor reporting into them) for their own org → hiring. Examples: "hiring a React developer", "looking for a frontend developer to join our team", "we're hiring a marketing manager".
- READ the whole post. "Hiring" of a FREELANCER/individual → freelancer_needed. "Hiring" of an AGENCY/team/company → agency_wanted. When the subject is a whole provider company, it is agency_wanted, NOT hiring.
- A post that is ambiguous between hiring an individual vs hiring an agency → classify based on whether the subject is an INDIVIDUAL (→ freelancer_needed or hiring) or an external PROVIDER COMPANY (→ agency_wanted).
- NEVER classify "hiring" when the post is sourcing an external agency/team — the user explicitly asked for agency_wanted and the strict type gate will reject hiring-classified leads.

═══════════════════════════════════════════════════════════════
3. SERVICE-MATCH — semantic, not keyword; be conservative
═══════════════════════════════════════════════════════════════
Grade the match of the requested service to what the author needs:
- exact: the specific requested service.
- equivalent: a clear synonym/role ("Shopify developer" for "Shopify Development"; "React developer" for "React Development").
- adjacent: commercially connected and plausibly part of the same engagement ("ecommerce development" for "Shopify Development"; "web development" for "Website development"). Accept only when the post clearly connects them.
- unrelated: does not materially connect. NEVER accept ("SEO" or "graphic design" for "Shopify Development"). Do NOT stretch adjacent into a match if the post is about something else.

RULE: if two grades are plausible, pick the LOWER (more conservative). service_match_score MUST be consistent with service_relevance: exact ≈ 90-100, equivalent ≈ 75-89, adjacent ≈ 55-74, unrelated ≤ 30.

═══════════════════════════════════════════════════════════════
4. INTENT STRENGTH — grade the strength of the action
═══════════════════════════════════════════════════════════════
- explicit: direct present action ("need", "hiring", "looking for", urgent).
- active_search: comparing/evaluating providers now ("we're shortlisting", "evaluating agencies").
- recommendation: asking the network for referrals ("anyone recommend a good X?"). Qualify only if it clearly reflects a real sourcing need for the requested service.
- problem_awareness: describes a problem but is NOT asking anyone to provide it yet — WEAK, do NOT qualify as a strict lead (unless there is also a clear direct request).
- research: exploring/asking opinions ("thoughts on X?", "what do you think about X?") — do NOT qualify.

═══════════════════════════════════════════════════════════════
5. SCORING RUBRIC (0-100) — be disciplined; most posts are NOT leads
═══════════════════════════════════════════════════════════════
service_match_score (weight): how well the service aligns (see section 3).
commercial_intent_score: strength of the need-for-a-service signal (explicit vendor search = 85-100; hiring with clear role = 75-90; recommendation request = 60-80; problem mention w/o ask = 25-45; pure content = 0-15).
urgency_score: time pressure (deadline/ASAP/starting soon = 80-100; no timeline = 20-40; none = 0). Do NOT invent urgency.
decision_maker_signal: is the author a founder/owner/exec/hiring-manager/lead (true) vs student/IC/freelancer advertising/unknown (false). Decision-maker alone NEVER qualifies a weak post.
evidence_strength: how much concrete evidence supports classification (quoted sourcing phrase + role + company = high; single vague phrase = low).
location_confidence: confidence the author is in the requested country, based ONLY on the location/country-code evidence supplied. Never infer from name/language/timezone.
overall_quality_score: the calibrated 0-100 lead quality = intent strength + service match + commercial intent + evidence + decision-maker, weighted by importance. A genuine, clear, in-country buyer scores 85+; a marginal one 60-75.

═══════════════════════════════════════════════════════════════
6. HARD REJECTION — set is_qualified=false and rejection_reason
═══════════════════════════════════════════════════════════════
ANY one of these → reject:
- selling/offering the service (seller_signal).
- job seeker looking for employment (job_seeker_signal).
- recruiting-seller at third-party clients (unless own-pool buyer).
- pure content/tips/thought-leadership/case study.
- research-only or problem-awareness-only (no direct ask).
- wrong service (unrelated, or adjacent without clear connection).
- wrong lead type vs the requested service's natural intent (e.g. requesting agency_wanted but the post is a freelance-hiring or seller post).
- insufficient evidence to prove the requested intent.

is_qualified=true REQUIRES ALL of: correct direction (sourcing, not selling), a service match of exact/equivalent (adjacent only with a clear connection), intent strength of recommendation or stronger DIRECT action, sufficient evidence, and in-country (matches the requested country when one is given). If ANY is weak, default to unqualified.

═══════════════════════════════════════════════════════════════
7. EVIDENCE & AMBIGUITY RULES
═══════════════════════════════════════════════════════════════
- DIRECT evidence = an exact phrase you can quote that shows sourcing/hiring (e.g. "we're looking for an agency to rebuild our ecommerce site").
- INFERENCE = "maybe they could need it." Never treat inference as buying intent.
- When evidence is insufficient to PROVE the requested intent → is_qualified=false. NEVER default to qualified.
- A quoted phrase must be copied verbatim into `evidence`.

LOCATION: judge only the location/country-code evidence. Do not infer country from name, language, timezone, or ethnicity. Do not reject a post merely because it is not written in English — judge semantic intent.

OUTPUT: strict JSON only. Never include text outside the JSON object. Never invent schema fields."""


def enforce_consistency(cls: LeadClassification) -> LeadClassification:
    """Fail-closed post-validation of a model classification.

    A classification that claims qualified True but contradicts its own flags is
    demoted to unqualified. This is the final defensive gate before a candidate
    can be accepted by the engine — it cannot be bypassed by score.
    """
    if not cls.is_qualified:
        return cls

    # 1. self-contradictory flags => cannot be qualified.
    if cls.seller_signal or cls.job_seeker_signal or cls.is_selling_offering or cls.is_job_seek:
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": "self-contradictory_qualified"})
    # 2. unrelated service => cannot be qualified regardless of score.
    if cls.service_relevance == "unrelated":
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": "unrelated_service"})
    # 3. Weak intent flags cannot be qualified (research/problem-awareness only).
    if cls.intent_strength in ("research", "problem_awareness", "none", ""):
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": f"weak_intent:{cls.intent_strength}"})
    # 4. Direction must be buying/sourcing, never selling/job-seek.
    if not cls.is_buying_sourcing:
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": "not_sourcing"})
    # 5. Weak service match cannot be qualified.
    if cls.service_match_score < 50:
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": f"weak_service_match:{int(cls.service_match_score)}"})
    # 6. Minimal evidence required.
    if not (cls.evidence or "").strip() or (cls.reason or "").strip() == "":
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": "insufficient_evidence"})
    # 7. Lead type must be a requestable intent (not irrelevant).
    if cls.canonical_lead_type() == "irrelevant":
        return cls.model_copy(update={"is_qualified": False, "rejection_reason": "wrong_intent_type"})
    return cls


def _classify_prompt(service: str, country: str, candidate: dict) -> str:
    return f"""REQUESTED SERVICE: {service}
REQUESTED COUNTRY: {country or "Any"}

=== CANDIDATE ===
AUTHOR NAME: {(candidate or {}).get('full_name', '?')}
AUTHOR HEADLINE: {(candidate or {}).get('headline', '')[:500]}
AUTHOR COMPANY: {(candidate or {}).get('company', '')[:200]}
AUTHOR LOCATION: {(candidate or {}).get('location', '')[:150]}
COUNTRY CODE: {(candidate or {}).get('country_code', '')}
POST TEXT:
{((candidate or {}).get('post_text') or '')[:3000]}
POSTED AT: {(candidate or {}).get('posted_at', '')}

=== TASK ===
Determine whether this author is ACTIVELY SEEKING: "{service}" — in the direction of BUYING/SOURCING (they need it done), not SELLING (they provide it) and not JOB-SEEKING (they want a job for themselves).

Decide the lead_type by WHO needs whom:
- agency_wanted = the author is sourcing an external AGENCY/studio/team for "{service}". Must be an explicit act of sourcing an external provider (NOT "we are an agency", NOT a passing mention).
- freelancer_needed = the author wants an independent freelancer/contractor/individual for "{service}".
- hiring = the author is recruiting a role for their OWN organization; the role must match "{service}".
- irrelevant = anything else.

Apply the hard-rejection rules from the system prompt. Only mark is_qualified=true when the evidence PROVES an active sourcing/hiring need for "{service}", the intent direction is correct, and the author is in the requested country ({country or "any"}).

Quote the exact supporting phrase in `evidence`. Output strict JSON only:
{{
  "lead_type": "freelancer_needed|hiring|agency_wanted|irrelevant",
  "intent_strength": "explicit|active_search|recommendation|problem_awareness|research|none",
  "is_buying_sourcing": true|false,
  "is_selling_offering": true|false,
  "is_job_seek": true|false,
  "service_match_score": 0-100,
  "commercial_intent_score": 0-100,
  "service_relevance": "exact|equivalent|adjacent|unrelated",
  "decision_maker_signal": true|false,
  "seller_signal": true|false,
  "job_seeker_signal": true|false,
  "location_confidence": 0-100,
  "urgency_score": 0-100,
  "evidence_strength": 0-100,
  "overall_quality_score": 0-100,
  "is_qualified": true|false,
  "confidence": 0-1,
  "evidence": "exact quoted evidence",
  "reason": "short justification",
  "rejection_reason": "only when is_qualified=false"
}}"""


async def _classify_one_async(client: AsyncOpenAI, service: str, country: str, candidate: dict) -> Optional[LeadClassification]:
    prompt = _classify_prompt(service, country, candidate)
    last = None
    for _ in range(MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=CLASSIFY_MODEL,
                messages=[
                    {"role": "system", "content": QUALIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
            if not content:
                return None
            data = json.loads(content)
            cls = LeadClassification(**data)
            return enforce_consistency(cls)
        except ValidationError as e:
            last = f"validation:{e}"
            continue
        except json.JSONDecodeError as e:
            last = f"json:{e}"
            continue
        except Exception as e:
            last = f"api:{e}"
            continue
    logger.warning(f"[AI] classify failed for {candidate.get('full_name', '?')} after retries: {last}")
    return None


async def classify_linkedin_candidates(client: AsyncOpenAI, service: str, country: str, candidates: list[dict]) -> dict[str, LeadClassification]:
    """Classify many candidates, fail-closed.

    Returns {candidate_key: LeadClassification}. Candidates that fail to produce
    a valid classification are ABSENT — the caller treats them as rejected.
    """
    if not candidates:
        return {}
    if client is None:
        logger.warning("[AI] classify called with no client — returning empty (fail-closed)")
        return {}

    sem = asyncio.Semaphore(CLASSIFY_CONCURRENCY)

    async def _wrapped(cand: dict):
        async with sem:
            return await _classify_one_async(client, service, country, cand)

    outputs = await asyncio.gather(*[_wrapped(c) for c in candidates])
    results: dict[str, LeadClassification] = {}
    for cand, cls in zip(candidates, outputs):
        if cls is not None:
            results[candidate_key(cand)] = cls
    return results


def candidate_key(candidate: dict) -> str:
    url = (candidate.get("linkedin_url") or candidate.get("post_url") or "").split("?")[0].rstrip("/").lower()
    if url:
        return url
    return f"{(candidate.get('full_name') or '?')}::{str(candidate.get('post_text') or '')[:40].lower()}"


# ── Legacy alias so existing imports keep working ─────────────────────────
async def classify_candidates(client: AsyncOpenAI, service: str, country: str, candidates: list[dict]) -> dict[str, LeadClassification]:
    return await classify_linkedin_candidates(client, service, country, candidates)


def attach_classification(candidate: dict, cls: LeadClassification) -> dict:
    candidate["classification"] = cls.model_dump()
    candidate["ai_qualified"] = bool(cls.is_qualified)
    candidate["ai_score"] = cls.overall_quality_score
    candidate["lead_type"] = cls.canonical_lead_type()
    candidate["intent_strength"] = cls.canonical_intent_strength()
    candidate["service_match_score"] = cls.service_match_score
    candidate["commercial_intent_score"] = cls.commercial_intent_score
    candidate["service_relevance"] = cls.service_relevance
    candidate["decision_maker_signal"] = cls.decision_maker_signal
    candidate["seller_signal"] = cls.seller_signal or cls.is_selling_offering
    candidate["job_seeker_signal"] = cls.job_seeker_signal or cls.is_job_seek
    candidate["ai_reason"] = cls.reason
    candidate["ai_evidence"] = cls.evidence
    candidate["outreach_angle"] = ""
    return candidate


async def generate_pitch(
    lead: dict[str, Any],
    analysis: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    client = _get_openai_client()
    if not client:
        return {
            "pitch": "AI pitch generation is not configured. Please set OPENAI_API_KEY.",
            "confidence_score": 0.0,
            "estimated_deal_value": 0.0,
        }

    prompt = _build_pitch_prompt(lead, analysis)

    try:
        import asyncio
        resp = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=PITCH_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional sales copywriter helping freelance web developers "
                            "and digital marketing agencies write outreach messages. "
                            "Write concise, professional, and personalized outreach pitches. "
                            "Do NOT sound robotic or generic. Use the business details provided. "
                            "Keep it under 200 words. Include a clear value proposition and call to action."
                            "\n\nReturn a JSON object with key 'pitch' containing the outreach text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500,
            ),
        )
        if not resp.choices or not resp.choices[0].message.content:
            return {"pitch": "Unable to generate pitch at this time.", "confidence_score": 0, "estimated_deal_value": 0}
        result = json.loads(resp.choices[0].message.content)
        pitch_text = result.get("pitch", "")

        confidence = _calculate_confidence(lead, analysis)
        deal_value = _estimate_deal_value(lead, analysis)

        return {
            "pitch": pitch_text,
            "confidence_score": confidence,
            "estimated_deal_value": deal_value,
        }

    except Exception as e:
        logger.error(f"Pitch generation failed: {e}")
        return {
            "pitch": "Pitch generation failed. Please try again.",
            "confidence_score": 0.0,
            "estimated_deal_value": 0.0,
        }


async def generate_website_message(
    lead: dict[str, Any],
    analysis: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    client = _get_openai_client()
    if not client:
        return {
            "message": (
                f"Hi {lead.get('business_name', 'there')}! "
                f"I noticed your website could use some improvements. "
                f"Would you be open to a quick chat about how I can help?"
            ),
        }

    prompt = _build_message_prompt(lead, analysis)

    try:
        import asyncio
        resp = await asyncio.to_thread(
            lambda: client.chat.completions.create(
                model=MESSAGE_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional web consultant reaching out to business owners. "
                            "Write a short, personalized outreach message that mentions specific issues "
                            "found on their website. Keep it under 120 words. Friendly but professional. "
                            "Include a clear call to action. Do NOT use markdown. Do NOT use emojis. "
                            "Write in plain text suitable for WhatsApp."
                            "\n\nReturn a JSON object with key 'message' containing the outreach text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=300,
            ),
        )
        if not resp.choices or not resp.choices[0].message.content:
            return {"message": "Unable to generate message at this time."}
        result = json.loads(resp.choices[0].message.content)
        return {"message": result.get("message", "")}

    except Exception as e:
        logger.error(f"Website message generation failed: {e}")
        return {
            "message": (
                f"Hi {lead.get('business_name', 'there')}! "
                f"I can help improve your online presence. "
                f"Would you be open to a quick conversation?"
            ),
        }


def _build_pitch_prompt(lead: dict, analysis: Optional[dict] = None) -> str:
    parts = [
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
        "\n- Offers a clear value proposition"
        "\n- Has a friendly but professional call to action"
        "\n- Is suitable for email or LinkedIn outreach"
    )

    return "\n".join(parts)


def _build_message_prompt(lead: dict, analysis: Optional[dict] = None) -> str:
    parts = [
        f"Business Name: {lead.get('business_name', 'Unknown')}",
        f"Category: {lead.get('category', 'N/A')}",
    ]

    if lead.get("full_address"):
        parts.append(f"Location: {lead['full_address']}")

    if lead.get("website_url"):
        parts.append(f"Website: {lead['website_url']}")
    else:
        parts.append("Website: No website found — they need one built")

    if lead.get("phone"):
        parts.append(f"Phone: {lead['phone']}")

    if analysis:
        score = analysis.get("overall_score", 0)
        parts.append(f"Website Health Score: {score}/100")
        issues = analysis.get("issues", [])
        if issues:
            parts.append("Website Issues Found:")
            for issue in issues[:4]:
                parts.append(f"  - {issue}")
        raw = analysis.get("raw_analysis", {})
        breakdown = raw.get("score_breakdown", {})
        if breakdown:
            deductions = breakdown.get("deductions", [])
            criticals = [d for d in deductions if d.get("severity") == "critical"]
            if criticals:
                parts.append("Critical Issues:")
                for c in criticals[:3]:
                    parts.append(f"  - {c.get('reason', '')}")

    parts.append(
        "\nWrite a short outreach message that:"
        "\n- Greets them by business name"
        "\n- Mentions 1-2 specific issues found on their website"
        "\n- Offers your help in a friendly, non-pushy way"
        "\n- Has a clear call to action (reply or call)"
        "\n- Is under 120 words, plain text, no markdown, no emojis"
    )

    return "\n".join(parts)


def _calculate_confidence(lead: dict, analysis: Optional[dict] = None) -> float:
    score = 0.5
    if lead.get("website_url"):
        score += 0.2
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
    reviews = lead.get("total_reviews", 0)
    rating = lead.get("rating", 0)
    if reviews > 10 and rating and rating < 4.0:
        score += 0.05
    if lead.get("phone"):
        score += 0.05
    return min(1.0, round(score, 2))


def _estimate_deal_value(lead: dict, analysis: Optional[dict] = None) -> float:
    base_value = 500.0
    if not lead.get("website_url"):
        base_value = 2000.0
    elif analysis:
        issue_count = len(analysis.get("issues", []))
        if issue_count > 4:
            base_value = 1500.0
        elif issue_count > 2:
            base_value = 1000.0
    reviews = lead.get("total_reviews", 0)
    if reviews > 100:
        base_value *= 1.5
    elif reviews > 50:
        base_value *= 1.3
    elif reviews > 20:
        base_value *= 1.1
    return round(base_value, 2)
