"""LLM query expansion — niche-aware buyer phrasings for the search engine.

One optional DeepSeek call per search generates natural "buyer sentence"
variants for the user's service that deterministic templates cannot know
(e.g. niche vocabulary, how buyers of THIS service actually phrase asks).
Variants are merged at the head of the diversification pool by the engine.

The same call also returns the service vocabulary (role nouns, synonyms,
adjacent-but-different crafts) that the classifier uses for service match.

Fail-closed: no key / timeout / invalid JSON / wrong shape -> empty and
the engine silently keeps the deterministic template pool. Expansion never
blocks or breaks a search, and its single call counts toward the per-search
DeepSeek ceiling (the classifier exposes `calls` and the engine reads it).
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger(__name__)

_EXPANSION_PROMPT = """You write Google search phrases that find LinkedIn posts written by people who
NEED a service right now - and you map the service's vocabulary.

The user sells: "{service}".
(Their text may be a sentence, a sales pitch, a list of services, misspelled, or not in
English - work out what service they actually provide.)
We are looking for: {lead_type_label}.

0. "canonical_services": 1-3 short English names (1-4 words) of the service(s) the user
   sells, exactly as a BUYER would name them, most important first. E.g. "I help SaaS
   founders with conversion-focused landing pages" -> ["landing page design", "conversion
   rate optimization"]; "vidio editng for youtubers" -> ["video editing"].
1. "queries": {count} short phrases (3-8 words) copied from how a genuine BUYER writes
   such a post. Each phrase will be searched as an EXACT quoted phrase, so it must be a
   natural contiguous chunk of a real sentence, e.g. {examples}.
   - AT LEAST HALF must name the concrete TASK / deliverable the buyer needs done - real
     buyers describe the job, not the job title: "need a CA for GST filing", "need someone
     to file my ITR", "need a lawyer to draft our founders agreement", "need help with
     trademark registration", "need someone to fix our leaking pipe", "need someone to edit
     our podcast". Bare "looking for a <job title>" mostly matches JOB ADS and advice posts.
   - vary the intent: urgent asks, project asks, recommendation/referral asks
   - use the service's real-world role nouns and niche vocabulary (how buyers say it)
   - prefer phrasings that carry budget/timeline/scope signals ("for our launch",
     "this month", "budget ready", "for a project")
   - FORBIDDEN: seller language ("I offer", "we provide", "hire me", "available for",
     "DM me"), job-ad language ("apply now", "join our team", "years of experience"),
     hashtags, quotes, vague asks with no service noun, anything where the author SELLS.
{mode_rule}
2. "role_nouns": up to 5 nouns buyers use for the provider ({role_example}).
3. "synonyms": up to 8 terms/sub-services that COUNT as this exact service.
4. "not_this_service": up to 8 ADJACENT crafts a careless matcher would confuse with it
   but which are NOT this service (e.g. for video editing: videographer, motion designer,
   social media manager).

{avoid_block}Return ONLY a JSON object:
{{"canonical_services": ["..."], "queries": ["..."], "role_nouns": ["..."], "synonyms": ["..."],
 "not_this_service": ["..."]}}"""

_AVOID_BLOCK = """ALREADY SEARCHED (they are used up - write {count} NEW phrasings with DIFFERENT wording
and angles: other role nouns, niche sub-services, industries, deliverables, urgency, referral
asks; never repeat or trivially reword these):
{avoid}

"""

_MODE = {
    "need_agency": dict(
        label="a CLIENT/business owner who wants to hire an AGENCY, studio, firm or outside "
              "team for their own work (NOT an agency pitching itself, NOT hiring an employee)",
        examples='"looking for a {service} agency", "need an agency to handle our", '
                 '"can anyone recommend a good agency for"',
        rule="   - EVERY phrase must seek an agency/studio/firm/outside team; never a single "
             "freelancer, never an employee.\n",
        role_example='"agency", "studio", "production house"',
    ),
    "our_agency": dict(
        label="an agency seeking outside freelance help for its own client work",
        examples='"looking for freelance {service} help for client projects"',
        rule="   - every phrase is an agency sourcing freelancers for its client work.\n",
        role_example='"freelance editor", "contractor"',
    ),
    "need_freelancer": dict(
        label="someone (founder, creator, business) who wants to hire an independent "
              "FREELANCER/contractor for their own project (NOT an agency, NOT an employee)",
        examples='"looking for a freelance <role>", "need someone to help with our", '
                 '"anyone know a good <role>"',
        rule="   - EVERY phrase must seek an individual freelancer/contractor/person; never an "
             "agency or firm, never a full-time employee.\n",
        role_example='e.g. for video editing: "video editor", "reels editor", "youtube editor"',
    ),
}


class Expansion(list):
    """Expanded buyer query phrasings (the list itself) plus the service
    vocabulary the classifier uses to judge service match. A plain list
    subclass, so every caller that only wants the queries keeps working."""

    def __init__(self, queries=(), *, role_nouns=(), synonyms=(), not_this_service=(),
                 canonical_services=()):
        super().__init__(queries)
        self.canonical_services: list[str] = list(canonical_services)
        self.role_nouns: list[str] = list(role_nouns)
        self.synonyms: list[str] = list(synonyms)
        self.not_this_service: list[str] = list(not_this_service)


def _terms(raw: object, limit: int) -> list[str]:
    """Clean a short vocabulary list (terms, not sentences)."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        t = re.sub(r"\s+", " ", item).strip().strip('"').strip()
        if 2 <= len(t) <= 40 and t.lower() not in (o.lower() for o in out):
            out.append(t)
    return out[:limit]


def parse_expansion(payload: str | dict | None) -> Expansion:
    """Parse the model response into an Expansion (empty on any failure)."""
    data: object = payload
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return Expansion()
    if not isinstance(data, dict):
        return Expansion()
    role_nouns = _terms(data.get("role_nouns"), 5)
    taken = {r.lower() for r in role_nouns}
    return Expansion(
        _extract_queries(data),
        role_nouns=role_nouns,
        synonyms=[t for t in _terms(data.get("synonyms"), 8) if t.lower() not in taken],
        not_this_service=_terms(data.get("not_this_service"), 8),
        canonical_services=_terms(data.get("canonical_services"), 3),
    )


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
    return out[:16]


def make_query_expander(classifier, lead_type: str, service_limit: int = 12):
    """Build the engine's `query_expander` callable from a GptClassifier.

    The classifier's OpenAI-compatible client is reused (same provider/model/
    retry config); the call is counted via the classifier's own `calls`
    counter so the per-search DeepSeek ceiling stays authoritative.
    `lead_type` is the requested buyer bucket (need_freelancer | need_agency |
    our_agency) - each gets its OWN direction wording, so an agency search
    never receives freelancer phrasings.
    Returns a callable (service_text) -> Expansion (possibly empty).
    """
    mode = _MODE.get(lead_type, _MODE["need_freelancer"])

    def expand(service: str, avoid: list[str] | None = None) -> Expansion:
        """`avoid` (optional): phrasings already searched - asks for a fresh,
        DIFFERENT batch (the engine's refill when its query pool runs dry)."""
        client = getattr(classifier, "_client", None)
        if client is None:
            return Expansion()
        avoid_block = ""
        if avoid:
            listed = "\n".join(f"- {a}" for a in list(dict.fromkeys(avoid))[:60])
            avoid_block = _AVOID_BLOCK.format(count=service_limit, avoid=listed)
        prompt = _EXPANSION_PROMPT.format(
            service=(service or "").strip()[:200],
            lead_type_label=mode["label"],
            count=service_limit,
            examples=mode["examples"].replace("{service}", (service or "").strip()[:60]),
            mode_rule=mode["rule"],
            role_example=mode["role_example"],
            avoid_block=avoid_block,
        )
        try:
            classifier.calls += 1
            resp = client.chat.completions.create(
                model=classifier.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6 if avoid else 0.3,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 - fail-closed
            log.warning("Query expansion failed (using deterministic pool): %s", exc)
            return Expansion()
        out = parse_expansion(getattr(resp.choices[0].message, "content", None))
        log.info("Query expansion produced %d phrasings, %d synonyms, %d exclusions",
                 len(out), len(out.synonyms), len(out.not_this_service))
        return out

    return expand
