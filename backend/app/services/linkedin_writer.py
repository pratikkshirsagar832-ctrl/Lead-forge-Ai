"""LinkedIn post writing with DeepSeek (drafts, rewrites, humanize, carousels).

Writing rules are adapted from the MIT-licensed "linkedin-skills" project by
Sergey Bulaev (https://github.com/sergebulaev/linkedin-skills): hook
formulas, voice rules and the humanizer pre-publish checklist. MIT license,
Copyright (c) 2026 Sergey Bulaev.

Every call returns validated JSON; anything malformed raises WriterError
(fail-closed - the UI shows a retry, nothing half-generated is saved).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

MAX_CHARS = 3000


class WriterError(RuntimeError):
    pass


VOICE_RULES = """WRITING RULES (non-negotiable):
- Hook first: lines 1-2 must stop the scroll and fit before LinkedIn's "...see more" cut
  (~210 characters). Prefer a specific number or a concrete moment in line 1.
  Never open with a question, never with "In today's fast-paced world".
- Short paragraphs (1-2 sentences) separated by blank lines. 120-300 words unless asked.
- Concrete over abstract: at least one specific number WITH a referent, one named thing
  (tool, city, company, date) or one first-hand detail. Never invent facts about the
  author - if a detail is unknown, write around it instead of making it up.
- One sharp idea per post. One opinion someone could disagree with.
- End with a specific, genuine question or a clean landing line - never "What do you
  think?", never "Comment YES", never "Like if you agree" (LinkedIn suppresses bait).
- 0-3 relevant hashtags at the very end, or none. No emoji walls (max 2 emoji).
- Plain text only: no markdown (**bold**, #headers), no links unless given.

BANNED (these read as AI and lose reach):
- Words: leverage, utilize, facilitate, streamline, robust, seamless, delve, navigate,
  unlock, harness, foster, cultivate, elevate, empower, landscape, ecosystem, paradigm,
  realm, tapestry, journey, game-changer, deep dive, crucial, notably, fundamentally,
  essentially, ultimately, holistic, multifaceted, nuanced.
- Patterns: "It's not just X, it's Y" / "not X, but Y" framing; "Here's what/how/the thing";
  "The result?" / "The catch?" reveals; "Stop X, start Y"; "Let me be honest" / "honestly?";
  staccato stacks ("Short. Punchy. Done."); one-word paragraphs; stacked rule-of-three
  lists; hedging stacks ("might potentially"); "Let that sink in"; "at the end of the day".
- Punctuation: at most 1-2 em dashes per post; no en dashes between clauses; straight quotes.
"""

HOOK_STYLES = """HOOK STYLES to vary between (pick what fits the goal):
- Odd-precision number: "$4,730 in overages taught me more than any course."
- Time-anchor story: "Three weeks ago a client fired us on a Friday call."
- Contrarian with receipts: a claim most of the audience believes, then evidence against it.
- Year-over-year pivot: what worked last year vs what works now, with one hard number.
- Named gratitude: specific credit to a real person/company for a specific lesson.
- Explain-simply: a complex idea in plain words with one concrete example.
- Curiosity gap (honest): promise a specific payoff and deliver it in the body."""

SYSTEM = ("You are a senior LinkedIn ghostwriter. You write posts that sound like a real "
          "professional wrote them on their phone - specific, warm, direct - and that "
          "perform well in LinkedIn's 2026 feed.\n\n" + VOICE_RULES + "\n" + HOOK_STYLES +
          "\n\nAlways answer with ONE JSON object exactly in the requested shape.")


def _client():
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise WriterError("AI writing is not configured (DEEPSEEK_API_KEY missing).")
    from openai import OpenAI

    return OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, timeout=90)


def _ask(prompt: str, temperature: float = 0.8) -> dict[str, Any]:
    settings = get_settings()
    try:
        resp = _client().chat.completions.create(
            model=settings.deepseek_model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "")
    except WriterError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider / JSON failures -> fail closed
        logger.warning("DeepSeek writer call failed: %s", exc)
        raise WriterError("The AI writer is unavailable right now. Please try again.") from exc
    if not isinstance(data, dict):
        raise WriterError("The AI writer returned an unexpected answer. Please try again.")
    return data


def clean_post(text: str) -> str:
    """Normalise model output into LinkedIn-ready plain text."""
    t = (text or "").replace("\r\n", "\n")
    t = t.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)              # no markdown bold
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)         # no markdown headers
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) > MAX_CHARS:
        cut = t[:MAX_CHARS]
        t = cut[: cut.rfind("\n") if cut.rfind("\n") > MAX_CHARS * 0.8 else MAX_CHARS].rstrip()
    return t


def _context(audience: str | None, voice_profile: str | None, service: str | None) -> str:
    parts = []
    if service:
        parts.append(f"The author's business/service: {service}")
    if audience:
        parts.append(f"Target readers: {audience}")
    if voice_profile:
        parts.append("The author's own writing sample - match its tone, vocabulary and rhythm:\n"
                     f'"""{voice_profile[:2500]}"""')
    return "\n".join(parts)


def draft_post(topic: str, *, goal: str = "engagement", tone: str = "conversational",
               audience: str | None = None, voice_profile: str | None = None,
               service: str | None = None, variants: int = 3) -> list[dict[str, str]]:
    """2-3 distinct post variants: [{"hook_style", "post"}]."""
    variants = max(1, min(int(variants), 3))
    data = _ask(f"""Write {variants} DIFFERENT LinkedIn post variants about:
"{topic[:600]}"

Goal: {goal} (engagement = comments/discussion, authority = saves/credibility, leads = inbound DMs
without being salesy). Tone: {tone}.
{_context(audience, voice_profile, service)}

Each variant must use a different hook style. Return:
{{"variants": [{{"hook_style": "...", "post": "full post text"}}]}}""")
    out = []
    for v in data.get("variants") or []:
        if isinstance(v, dict) and isinstance(v.get("post"), str) and len(v["post"].strip()) >= 40:
            out.append({"hook_style": str(v.get("hook_style") or "")[:60], "post": clean_post(v["post"])})
    if not out:
        raise WriterError("The AI writer returned no usable draft. Please try again.")
    return out[:variants]


def rewrite(post: str, instruction: str, voice_profile: str | None = None) -> str:
    data = _ask(f"""Rewrite this LinkedIn post following the instruction, keeping every fact
and the author's meaning. Instruction: "{instruction[:300]}"
{_context(None, voice_profile, None)}

POST:
\"\"\"{post[:MAX_CHARS]}\"\"\"

Return: {{"post": "rewritten post"}}""", temperature=0.6)
    text = data.get("post")
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise WriterError("The AI writer returned no usable rewrite. Please try again.")
    return clean_post(text)


def humanize(post: str) -> dict[str, Any]:
    """Remove AI tells with proportional edits (a clean draft gets 2-3 touches)."""
    data = _ask(f"""Edit this LinkedIn post so it reads human-written. Apply the WRITING RULES and
BANNED list. Edits must be proportional: fix real problems only, keep the author's facts,
tone, structure and any natural em dash. Never add confessions, hedges or invented numbers.

POST:
\"\"\"{post[:MAX_CHARS]}\"\"\"

Return: {{"post": "edited post", "changes": ["short description of each change"]}}""", temperature=0.4)
    text = data.get("post")
    if not isinstance(text, str) or len(text.strip()) < 20:
        raise WriterError("The AI writer returned no usable edit. Please try again.")
    changes = [str(c)[:160] for c in (data.get("changes") or []) if isinstance(c, str)][:10]
    return {"post": clean_post(text), "changes": changes}


def carousel(topic: str, *, slides: int = 8, audience: str | None = None,
             service: str | None = None) -> dict[str, Any]:
    """Carousel (PDF document post): {"title", "slides": [{"title","body"}], "caption"}."""
    slides = max(4, min(int(slides), 12))
    data = _ask(f"""Create a LinkedIn carousel (PDF document post) about:
"{topic[:600]}"
{_context(audience, None, service)}

{slides} slides. Slide 1 = a strong hook title (max 8 words) + a one-line promise.
Middle slides = one concrete idea each: a short title (max 7 words) and a body of 1-3 short
sentences (max 220 characters) with a specific example or number.
Last slide = a takeaway + a soft call to action (follow / save / DM), no bait.
Also write the caption post that accompanies the carousel (60-150 words, same rules).

Return: {{"title": "document title", "slides": [{{"title": "...", "body": "..."}}], "caption": "..."}}""",
                temperature=0.7)
    raw = data.get("slides")
    if not isinstance(raw, list):
        raise WriterError("The AI writer returned no slides. Please try again.")
    out = []
    for s in raw:
        if isinstance(s, dict) and str(s.get("title") or "").strip():
            out.append({"title": clean_post(str(s["title"]))[:90], "body": clean_post(str(s.get("body") or ""))[:400]})
    if len(out) < 3:
        raise WriterError("The AI writer returned too few slides. Please try again.")
    return {
        "title": clean_post(str(data.get("title") or out[0]["title"]))[:120],
        "slides": out[:12],
        "caption": clean_post(str(data.get("caption") or "")),
    }


def plan_posts(pillars: list[str], count: int, *, audience: str | None = None,
               voice_profile: str | None = None, avoid: list[str] | None = None) -> list[dict[str, str]]:
    """Autopilot: `count` ready-to-publish posts spread across the content pillars."""
    count = max(1, min(int(count), 10))
    pillar_text = "\n".join(f"- {p}" for p in pillars[:10]) or "- the author's expertise"
    avoid_text = "\n".join(f"- {a[:120]}" for a in (avoid or [])[:15])
    data = _ask(f"""Plan and write {count} LinkedIn posts for the coming days, rotating across these
content pillars:
{pillar_text}
{_context(audience, voice_profile, None)}
{"Do NOT repeat these recent topics:" + chr(10) + avoid_text if avoid_text else ""}

Vary hook styles and formats (story, lesson, contrarian take, how-to, behind the scenes).
Return: {{"posts": [{{"pillar": "...", "topic": "one-line topic", "post": "full post text"}}]}}""")
    out = []
    for p in data.get("posts") or []:
        if isinstance(p, dict) and isinstance(p.get("post"), str) and len(p["post"].strip()) >= 40:
            out.append({"pillar": str(p.get("pillar") or "")[:80], "topic": str(p.get("topic") or "")[:200],
                        "post": clean_post(p["post"])})
    if not out:
        raise WriterError("Autopilot could not generate posts right now.")
    return out[:count]
