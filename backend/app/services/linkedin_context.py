"""Everything DeepSeek should know about a LinkedIn Studio user.

`user_context()` assembles the brand profile (filled in before connecting
LinkedIn), connected accounts, autopilot settings, the story bank, writing
samples and the user's recent posts into one USER DATA block that is sent
with every writing task, so the AI writes as this person, about their real
business, without repeating what they already posted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BRAND_FIELDS: list[tuple[str, str]] = [
    ("managed_for", "Posting on behalf of"),
    ("full_name", "Name"),
    ("headline", "Role / headline"),
    ("company", "Company"),
    ("website", "Website"),
    ("industry", "Industry"),
    ("location", "Location"),
    ("language", "Write posts in"),
    ("services", "What they sell / do"),
    ("offer", "Offer, proof & differentiator"),
    ("target_audience", "Target audience (who reads the posts)"),
    ("ideal_client", "Ideal client"),
    ("goals", "Goals on LinkedIn"),
    ("tone", "Preferred tone"),
    ("topics", "Content pillars / topics"),
    ("expertise", "Expertise & opinions"),
    ("cta_preference", "Preferred call to action"),
    ("avoid", "NEVER use / mention"),
    ("posting_frequency", "Posting frequency"),
    ("notes", "Other notes"),
]
MANAGED_FOR = {"self": "their own personal brand", "company": "their company",
               "client": "a client they manage"}


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if str(v).strip())
    return str(value or "").strip()


def brand_profile(supabase, user_id: str) -> dict[str, Any] | None:
    try:
        rows = supabase.table("linkedin_brand_profiles").select("*").eq("user_id", user_id) \
            .limit(1).execute().data or []
    except Exception:  # noqa: BLE001 - table missing before migration v22
        return None
    return rows[0] if rows else None


def profile_complete(profile: dict[str, Any] | None) -> bool:
    if not profile or not profile.get("authorized"):
        return False
    return all(_fmt(profile.get(k)) for k in ("full_name", "services", "target_audience"))


def user_context(supabase, user_id: str, *, recent_posts: int = 12) -> str:
    """The USER DATA block (plain text) for DeepSeek."""
    lines: list[str] = [f"Today: {datetime.now(timezone.utc).strftime('%A %d %B %Y')} (UTC)"]
    profile = brand_profile(supabase, user_id) or {}
    if profile:
        lines.append("\n## Brand profile (provided and authorized by the user)")
        for key, label in BRAND_FIELDS:
            val = profile.get(key)
            if key == "managed_for":
                val = MANAGED_FOR.get(str(val or "self"), val)
            text = _fmt(val)
            if text:
                lines.append(f"- {label}: {text}")
        if _fmt(profile.get("voice_profile")):
            lines.append("\n## Voice & Brand Profile (learned from the user's own posts - filled: yes; match it)\n"
                         + str(profile["voice_profile"])[:5000])
        if _fmt(profile.get("story_bank")):
            lines.append("\n## Story bank (true facts, numbers and stories the user shared - use them)\n"
                         + str(profile["story_bank"])[:6000])
        if _fmt(profile.get("writing_samples")):
            lines.append("\n## The user's own writing samples (match this voice)\n"
                         + str(profile["writing_samples"])[:5000])
    else:
        lines.append("\n(No brand profile yet - keep claims generic and never invent specifics.)")
    if not _fmt(profile.get("story_bank")):
        lines.append("\n(Story bank is empty - write around missing specifics; never invent numbers or events.)")

    try:
        accounts = supabase.table("linkedin_accounts").select("kind,name,status").eq("user_id", user_id) \
            .execute().data or []
    except Exception:  # noqa: BLE001
        accounts = []
    if accounts:
        lines.append("\n## Connected LinkedIn accounts\n" + "\n".join(
            f"- {a.get('name') or 'LinkedIn'} ({'company page' if a.get('kind') == 'organization' else 'personal profile'}, {a.get('status')})"
            for a in accounts))

    try:
        ap = (supabase.table("linkedin_autopilot").select("pillars,audience,voice_profile,enabled")
              .eq("user_id", user_id).limit(1).execute().data or [{}])[0]
    except Exception:  # noqa: BLE001
        ap = {}
    if ap.get("pillars"):
        lines.append("\n## Autopilot content pillars\n- " + "\n- ".join(ap["pillars"]))
    if ap.get("audience") and not profile.get("target_audience"):
        lines.append(f"- Audience: {ap['audience']}")
    if ap.get("voice_profile") and not profile.get("writing_samples"):
        lines.append("\n## Voice sample\n" + str(ap["voice_profile"])[:3000])

    try:
        posts = (supabase.table("linkedin_posts").select("status,commentary,published_at,scheduled_at")
                 .eq("user_id", user_id).in_("status", ["published", "scheduled", "draft"])
                 .order("created_at", desc=True).limit(recent_posts).execute().data or [])
    except Exception:  # noqa: BLE001
        posts = []
    if posts:
        lines.append("\n## Recent posts (do NOT repeat these topics or hooks; keep the voice consistent)")
        for p in posts:
            when = (p.get("published_at") or p.get("scheduled_at") or "")[:10]
            text = " ".join(str(p.get("commentary") or "").split())[:500]
            if text:
                lines.append(f"- [{p.get('status')} {when}] {text}")
    return "\n".join(lines)
