"""LinkedIn Studio API - AI writing, scheduling and publishing through
LinkedIn's official API. Pro and Agency plans only.

  GET    /api/linkedin/status                 accounts, usage, feature flags
  GET    /api/linkedin/connect?app=member|pages   -> LinkedIn authorize URL
  GET    /api/linkedin/callback               OAuth redirect target (signed state)
  DELETE /api/linkedin/accounts/{id}
  GET    /api/linkedin/brand  ·  PUT /api/linkedin/brand   brand profile (required before connect)
  PUT    /api/linkedin/brand/voice            edit the learned voice profile
  POST   /api/linkedin/ai/{draft,rewrite,humanize,audit,voice,carousel,repurpose,hook,plan,profile,
                          interview,interview/digest,comment,reply,replies,advocacy}
  POST   /api/linkedin/lint                   instant rule check (no AI)
  POST   /api/linkedin/carousel/render        edited slides -> PDF media
  POST   /api/linkedin/media                  upload image / PDF
  GET    /api/linkedin/media/url?path=        short-lived preview URL
  GET    /api/linkedin/posts                  queue / calendar
  POST   /api/linkedin/posts                  create (draft | schedule | publish_now)
  PATCH  /api/linkedin/posts/{id}
  POST   /api/linkedin/posts/{id}/schedule    approve + schedule
  POST   /api/linkedin/posts/{id}/publish-now
  POST   /api/linkedin/posts/{id}/cancel
  DELETE /api/linkedin/posts/{id}             (also removes it from LinkedIn)
  GET    /api/linkedin/autopilot  ·  PUT /api/linkedin/autopilot  ·  POST /api/linkedin/autopilot/run
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.database import get_supabase_admin
from app.middleware.auth_middleware import get_current_user
from app.services import carousel_pdf, linkedin_studio as studio, linkedin_writer as writer
from app.services import linkedin_api as li
from app.services.linkedin_context import brand_profile, profile_complete, user_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/linkedin", tags=["LinkedIn Studio"])

EDITABLE = ("draft", "scheduled", "failed", "needs_reconnect", "cancelled")


def _db():
    return get_supabase_admin()


async def require_studio(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Pro / Agency only (plans.linkedin_posts_monthly > 0)."""
    info = await asyncio.to_thread(studio.plan_info, _db(), current_user["id"])
    if not info["enabled"]:
        raise HTTPException(status_code=403, detail={
            "message": "LinkedIn Studio is available on the Pro and Agency plans.",
            "upgrade_url": "/pricing", "plan": info["plan_id"]})
    return {**current_user, "studio": info}


async def _ai_unit(user: dict[str, Any]) -> None:
    """Each AI generation counts as one AI call on the user's monthly quota."""
    from app.services.plans import get_monthly_limit, get_plan_row, quota_owner_id, resolve_effective_subscription
    from app.services.usage import consume_monthly_quota

    supabase = _db()
    eff = resolve_effective_subscription(supabase, user["id"])
    limit = get_monthly_limit(get_plan_row(supabase, eff["plan_id"]), "ai_calls_monthly", "ai_calls", 5)
    if await consume_monthly_quota(supabase, quota_owner_id(eff, user["id"]), "ai", limit) >= 0:
        raise HTTPException(status_code=429, detail=f"Monthly AI limit reached ({limit}). Upgrade for more.")


async def _refund_ai(user: dict[str, Any]) -> None:
    from app.services.plans import quota_owner_id, resolve_effective_subscription
    from app.services.usage import refund_monthly_quota

    supabase = _db()
    eff = resolve_effective_subscription(supabase, user["id"])
    await refund_monthly_quota(supabase, quota_owner_id(eff, user["id"]), "ai")


def _ctx(user_id: str) -> str:
    """USER DATA for DeepSeek: brand profile, story bank, voice, recent posts."""
    return user_context(_db(), user_id)


def _brand(user_id: str) -> dict[str, Any] | None:
    return brand_profile(_db(), user_id)


# ------------------------------------------------------------ accounts

@router.get("/status")
async def status(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    supabase = _db()
    settings = get_settings()
    info = await asyncio.to_thread(studio.plan_info, supabase, user["id"])
    accounts = await asyncio.to_thread(
        lambda: supabase.table("linkedin_accounts").select("*").eq("user_id", user["id"])
        .order("created_at").execute().data or [])
    brand = await asyncio.to_thread(_brand, user["id"])
    return {
        "plan": {k: info[k] for k in ("plan_id", "enabled", "limit", "used", "scheduled", "remaining")},
        "accounts": [studio.public_account(a) for a in accounts],
        "brand_complete": profile_complete(brand),
        "member_app_configured": bool(settings.linkedin_client_id and settings.linkedin_client_secret),
        "pages_enabled": bool(settings.linkedin_pages_enabled and settings.linkedin_pages_client_id),
    }


# ---------------------------------------------------------- brand profile

class BrandIn(BaseModel):
    managed_for: Literal["self", "company", "client"] = "self"
    full_name: str = Field(..., min_length=2, max_length=120)
    headline: str | None = Field(None, max_length=220)
    company: str | None = Field(None, max_length=160)
    website: str | None = Field(None, max_length=300)
    industry: str | None = Field(None, max_length=120)
    location: str | None = Field(None, max_length=120)
    language: str = Field("English", max_length=40)
    services: str = Field(..., min_length=3, max_length=1500)
    offer: str | None = Field(None, max_length=1500)
    target_audience: str = Field(..., min_length=3, max_length=800)
    ideal_client: str | None = Field(None, max_length=800)
    goals: list[str] = Field(default_factory=list, max_length=8)
    tone: list[str] = Field(default_factory=list, max_length=8)
    topics: list[str] = Field(default_factory=list, max_length=10)
    expertise: str | None = Field(None, max_length=2000)
    story_bank: str | None = Field(None, max_length=8000)
    writing_samples: str | None = Field(None, max_length=6000)
    cta_preference: str | None = Field(None, max_length=300)
    avoid: str | None = Field(None, max_length=800)
    posting_frequency: str | None = Field(None, max_length=60)
    notes: str | None = Field(None, max_length=2000)
    authorized: bool = False

    @field_validator("goals", "tone", "topics")
    @classmethod
    def _clean_list(cls, v: list[str]) -> list[str]:
        return [x.strip()[:120] for x in v if x and x.strip()]


@router.get("/brand")
async def get_brand(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    row = await asyncio.to_thread(_brand, user["id"])
    return {"profile": row, "complete": profile_complete(row)}


@router.put("/brand")
async def put_brand(body: BrandIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    if not body.authorized:
        raise HTTPException(status_code=400, detail=(
            "Please confirm you authorize Hyperclients to create, schedule and publish LinkedIn "
            "posts on this profile's behalf."))
    existing = await asyncio.to_thread(_brand, user["id"]) or {}
    now = datetime.now(timezone.utc).isoformat()
    row = {**body.model_dump(), "user_id": user["id"], "updated_at": now,
           "authorized_at": existing.get("authorized_at") or now}
    saved = (await asyncio.to_thread(lambda: _db().table("linkedin_brand_profiles")
                                     .upsert(row, on_conflict="user_id").execute())).data[0]
    return {"profile": saved, "complete": profile_complete(saved)}


@router.get("/connect")
async def connect(app: Literal["member", "pages"] = "member", user: dict = Depends(require_studio)) -> dict[str, str]:
    if not profile_complete(await asyncio.to_thread(_brand, user["id"])):
        raise HTTPException(status_code=409, detail="Complete your brand profile before connecting LinkedIn.")
    try:
        return {"url": li.authorize_url(user["id"], app)}
    except li.LinkedInError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/callback", include_in_schema=False)
async def callback(code: str | None = None, state: str | None = None, error: str | None = None,
                   error_description: str | None = None):
    settings = get_settings()
    dest = settings.frontend_url.rstrip("/") + "/dashboard/linkedin"

    def back(**params):
        return RedirectResponse(f"{dest}?{urlencode(params)}", status_code=302)

    if error:
        return back(error=(error_description or error)[:200])
    if not code or not state:
        return back(error="LinkedIn did not return an authorization code.")
    try:
        st = li.verify_state(state)
        app = st["a"]
        tokens = await asyncio.to_thread(li.exchange_code, app, code)
        if app == "pages":
            orgs = await asyncio.to_thread(li.admin_organizations, tokens.access_token)
            if not orgs:
                return back(error="Your LinkedIn account is not an admin of any company page.")
            await asyncio.to_thread(studio.save_connection, _db(), st["u"], "pages", tokens, orgs, "organization")
        else:
            profile = await asyncio.to_thread(li.member_profile, tokens.access_token)
            await asyncio.to_thread(studio.save_connection, _db(), st["u"], "member", tokens, [profile], "person")
    except li.LinkedInError as exc:
        logger.warning("LinkedIn OAuth callback failed: %s", exc)
        return back(error=str(exc)[:200])
    except Exception:  # noqa: BLE001
        logger.exception("LinkedIn OAuth callback crashed")
        return back(error="Could not connect LinkedIn. Please try again.")
    return back(connected="1")


@router.delete("/accounts/{account_id}")
async def disconnect(account_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    supabase = _db()

    def _run():
        supabase.table("linkedin_posts").update({"status": "needs_reconnect",
                                                 "error": "LinkedIn account was disconnected."}) \
            .eq("account_id", account_id).eq("user_id", user["id"]).eq("status", "scheduled").execute()
        return supabase.table("linkedin_accounts").delete().eq("id", account_id).eq("user_id", user["id"]).execute()

    resp = await asyncio.to_thread(_run)
    if not resp.data:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"disconnected": True}


# ------------------------------------------------------------------ AI

Goal = Literal["comments", "reposts", "likes", "saves", "leads", "engagement", "authority"]


class DraftIn(BaseModel):
    topic: str = Field(..., min_length=3, max_length=600)
    goal: Goal = "comments"
    tone: str = Field("", max_length=40)
    length: Literal["short", "medium", "long"] = "medium"
    formula: str = Field("", max_length=40)
    variants: int = Field(3, ge=1, le=3)


class RewriteIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=3000)
    instruction: str = Field(..., min_length=2, max_length=300)


class HumanizeIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=3000)
    tier: Literal["forensic", "strict", "aesthetic", "all"] = "all"


class PostTextIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=6000)


class AuditIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=3000)
    goal: Literal["", "comments", "reposts", "likes", "saves", "leads"] = ""
    scheduled_for: str = Field("", max_length=60)


class VoiceIn(BaseModel):
    samples: str = Field(..., min_length=200, max_length=12000)


class VoiceSaveIn(BaseModel):
    voice_profile: str = Field("", max_length=5000)


class CarouselIn(BaseModel):
    topic: str = Field(..., min_length=3, max_length=600)
    slides: int = Field(8, ge=4, le=12)


class RepurposeIn(BaseModel):
    source: str = Field(..., min_length=40, max_length=12000)
    source_type: Literal["article", "blog", "tweet", "thread", "newsletter", "video transcript", "notes"] = "article"
    goal: Literal["comments", "reposts", "likes", "saves", "leads"] = "comments"


class TopicsIn(BaseModel):
    hint: str = Field("", max_length=200)


class PlanIn(BaseModel):
    theme: str = Field("", max_length=400)
    days: int = Field(7, ge=3, le=14)
    edition: Literal["general", "founder"] = "general"
    posts_per_week: int = Field(4, ge=3, le=5)


class ProfileIn(BaseModel):
    headline: str = Field("", max_length=300)
    about: str = Field("", max_length=4000)
    extra: str = Field("", max_length=1500)
    goal: Literal["clients", "job", "authority"] = "clients"


class InterviewIn(BaseModel):
    topic: str = Field("", max_length=200)
    mode: Literal["", "bank", "post"] = ""


class QA(BaseModel):
    q: str = Field(..., max_length=300)
    a: str = Field("", max_length=1500)


class InterviewDigestIn(BaseModel):
    answers: list[QA] = Field(..., min_length=1, max_length=12)
    save_to_story_bank: bool = True
    mode: Literal["bank", "post"] = "bank"
    topic: str = Field("", max_length=200)


class CommentIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=5000)
    author: str = Field("", max_length=80)
    goal: Literal["visibility", "relationship", "authority"] = "visibility"
    mode: Literal["comment", "reshare"] = "comment"


class ReplyIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=4000)
    comment: str = Field(..., min_length=2, max_length=2000)
    commenter: str = Field("", max_length=80)


class ThreadComment(BaseModel):
    name: str = Field("", max_length=80)
    text: str = Field(..., min_length=1, max_length=1500)
    is_reply: bool = False


class RepliesIn(BaseModel):
    post: str = Field(..., min_length=10, max_length=4000)
    comments: list[ThreadComment] = Field(..., min_length=1, max_length=100)


class AdvocacyIn(BaseModel):
    team_size: int = Field(..., ge=2, le=500)
    goals: str = Field(..., min_length=3, max_length=400)
    current_state: str = Field("", max_length=300)


class Slide(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    body: str = Field("", max_length=500)


class RenderIn(BaseModel):
    title: str = Field("Carousel", max_length=200)
    slides: list[Slide] = Field(..., min_length=2, max_length=15)


async def _run_ai(user: dict[str, Any], fn, *args, **kwargs):
    """One AI call on the plan's monthly quota; the user's full context is
    always attached (ctx=...) so DeepSeek knows who it writes for."""
    await _ai_unit(user)
    try:
        ctx = await asyncio.to_thread(_ctx, user["id"])
        return await asyncio.to_thread(fn, *args, ctx=ctx, **kwargs)
    except writer.WriterError as exc:
        await _refund_ai(user)
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/ai/draft")
async def ai_draft(body: DraftIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return {"variants": await _run_ai(user, writer.draft_post, body.topic, goal=body.goal, tone=body.tone,
                                      length=body.length, formula=body.formula, variants=body.variants)}


@router.post("/ai/rewrite")
async def ai_rewrite(body: RewriteIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return {"post": await _run_ai(user, writer.rewrite, body.post, body.instruction)}


@router.post("/ai/humanize")
async def ai_humanize(body: HumanizeIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.humanize, body.post, tier=body.tier)


@router.post("/ai/audit")
async def ai_audit(body: AuditIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.audit, body.post, goal=body.goal, scheduled_for=body.scheduled_for)


@router.post("/lint")
async def lint_post(body: PostTextIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    """Instant, free rule check (no AI call) for the live editor."""
    from app.services.linkedin_lint import lint

    return lint(body.post)


def _save_voice(user_id: str, text: str, samples: str | None = None) -> bool:
    if not _brand(user_id):
        return False
    now = datetime.now(timezone.utc).isoformat()
    row: dict[str, Any] = {"voice_profile": text, "voice_updated_at": now, "updated_at": now}
    if samples is not None:
        row["writing_samples"] = samples[:6000]
    _db().table("linkedin_brand_profiles").update(row).eq("user_id", user_id).execute()
    return True


@router.post("/ai/voice")
async def ai_voice(body: VoiceIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    """Learn the user's voice from their own posts and save it to the brand profile."""
    prof = await _run_ai(user, writer.build_voice_profile, body.samples)
    prof["saved"] = await asyncio.to_thread(_save_voice, user["id"], prof["text"], body.samples)
    return prof


@router.put("/brand/voice")
async def put_voice(body: VoiceSaveIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    if not await asyncio.to_thread(_save_voice, user["id"], body.voice_profile.strip()):
        raise HTTPException(status_code=409, detail="Complete your brand profile first.")
    return {"saved": True}


@router.post("/ai/carousel")
async def ai_carousel(body: CarouselIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    deck = await _run_ai(user, writer.carousel, body.topic, slides=body.slides)
    media = await _render_and_store(user, deck["title"], deck["slides"])
    return {**deck, "media": media}


@router.post("/ai/repurpose")
async def ai_repurpose(body: RepurposeIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.repurpose, body.source, source_type=body.source_type, goal=body.goal)


@router.post("/ai/hook")
async def ai_hook(body: PostTextIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.extract_hook, body.post)


@router.post("/ai/topics")
async def ai_topics(body: TopicsIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    """Topic ideas for the composer, from the user's brand profile + story bank."""
    return {"topics": await _run_ai(user, writer.suggest_topics, hint=body.hint)}


@router.post("/ai/plan")
async def ai_plan(body: PlanIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.content_plan, body.theme, days=body.days, edition=body.edition,
                         posts_per_week=body.posts_per_week)


@router.post("/ai/profile")
async def ai_profile(body: ProfileIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.optimize_profile, body.headline, body.about, extra=body.extra, goal=body.goal)


@router.post("/ai/interview")
async def ai_interview(body: InterviewIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.interview_questions, body.topic, mode=body.mode)


@router.post("/ai/interview/digest")
async def ai_interview_digest(body: InterviewDigestIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    result = await _run_ai(user, writer.interview_digest, [a.model_dump() for a in body.answers],
                           mode=body.mode, topic=body.topic)
    if body.save_to_story_bank and result["entries"]:
        def _append():
            brand = _brand(user["id"])
            if not brand:
                return False
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            add = "\n".join(f"- [{stamp}] ({e.get('section') or 'Notes'}) {e['title']}: {e['detail']}"
                            for e in result["entries"])
            bank = ((brand.get("story_bank") or "").rstrip() + "\n" + add).strip()[-8000:]
            _db().table("linkedin_brand_profiles").update(
                {"story_bank": bank, "updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("user_id", user["id"]).execute()
            return True
        result["saved_to_story_bank"] = await asyncio.to_thread(_append)
    return result


@router.post("/ai/comment")
async def ai_comment(body: CommentIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.draft_comment, body.post, author=body.author, goal=body.goal, mode=body.mode)


@router.post("/ai/reply")
async def ai_reply(body: ReplyIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.draft_reply, body.post, body.comment, commenter=body.commenter)


@router.post("/ai/replies")
async def ai_replies(body: RepliesIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    """Whole-thread sweep: filter low-value comments, draft a reply to every one worth answering."""
    return await _run_ai(user, writer.draft_replies, body.post, [c.model_dump() for c in body.comments])


@router.post("/ai/advocacy")
async def ai_advocacy(body: AdvocacyIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return await _run_ai(user, writer.advocacy_plan, body.team_size, body.goals, current_state=body.current_state)


async def _render_and_store(user: dict[str, Any], title: str, slides: list[dict[str, Any]]) -> dict[str, Any]:
    brand = await asyncio.to_thread(_brand, user["id"]) or {}
    author = brand.get("full_name") or user.get("name") or ""
    pdf = await asyncio.to_thread(carousel_pdf.render_carousel, slides, author=author,
                                  handle=brand.get("company") or "")
    item = await asyncio.to_thread(studio.store_media, _db(), user["id"], pdf, "application/pdf", f"{title}.pdf")
    item["title"] = title[:200]
    return item


@router.post("/carousel/render")
async def render_carousel(body: RenderIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    return {"media": await _render_and_store(user, body.title, [s.model_dump() for s in body.slides])}


# ---------------------------------------------------------------- media

@router.post("/media")
async def upload_media(file: UploadFile = File(...), user: dict = Depends(require_studio)) -> dict[str, Any]:
    data = await file.read(studio.MAX_DOC_BYTES + 1)
    try:
        return await asyncio.to_thread(studio.store_media, _db(), user["id"], data,
                                       file.content_type or "", file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/media/url")
async def media_url(path: str = Query(...), user: dict = Depends(require_studio)) -> dict[str, str]:
    if not path.startswith(f"{user['id']}/") or ".." in path:
        raise HTTPException(status_code=404, detail="Not found")
    signed = await asyncio.to_thread(
        lambda: _db().storage.from_(studio.BUCKET).create_signed_url(path, 600))
    url = signed.get("signedURL") or signed.get("signedUrl") if isinstance(signed, dict) else None
    if not url:
        raise HTTPException(status_code=404, detail="Not found")
    return {"url": url}


# ---------------------------------------------------------------- posts

class MediaItem(BaseModel):
    type: Literal["image", "document"]
    storage_path: str
    title: str = ""
    alt: str = ""


class PostIn(BaseModel):
    account_id: str | None = None
    commentary: str = Field("", max_length=3000)
    media: list[MediaItem] = Field(default_factory=list, max_length=20)
    visibility: Literal["PUBLIC", "CONNECTIONS"] = "PUBLIC"
    scheduled_at: datetime | None = None
    action: Literal["draft", "schedule", "publish_now"] = "draft"
    source: Literal["manual", "ai"] = "manual"

    @field_validator("commentary")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()


class PostPatch(BaseModel):
    account_id: str | None = None
    commentary: str | None = Field(None, max_length=3000)
    media: list[MediaItem] | None = Field(None, max_length=20)
    visibility: Literal["PUBLIC", "CONNECTIONS"] | None = None
    scheduled_at: datetime | None = None


class ScheduleIn(BaseModel):
    scheduled_at: datetime


def _own_account(user_id: str, account_id: str | None) -> dict[str, Any]:
    if not account_id:
        raise HTTPException(status_code=400, detail="Choose which LinkedIn profile or page to post as.")
    rows = _db().table("linkedin_accounts").select("*").eq("id", account_id).eq("user_id", user_id) \
        .limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=400, detail="LinkedIn account not found - connect it first.")
    if rows[0].get("status") != "active":
        raise HTTPException(status_code=400, detail="That LinkedIn account needs to be reconnected.")
    return rows[0]


def _check_schedule_time(at: datetime) -> datetime:
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if at < now + timedelta(minutes=2):
        raise HTTPException(status_code=400, detail="Schedule at least 2 minutes in the future (or use Post now).")
    if at > now + timedelta(days=90):
        raise HTTPException(status_code=400, detail="You can schedule up to 90 days ahead.")
    return at


def _ready_to_publish(post: dict[str, Any]) -> None:
    if not (post.get("commentary") or "").strip() and not post.get("media"):
        raise HTTPException(status_code=400, detail="Write something or add media before publishing.")
    if any(m.get("type") == "document" for m in post.get("media") or []) and not (post.get("commentary") or "").strip():
        raise HTTPException(status_code=400, detail="Add a caption for the document post.")


def _load_post(user_id: str, post_id: str) -> dict[str, Any]:
    rows = _db().table("linkedin_posts").select("*").eq("id", post_id).eq("user_id", user_id) \
        .limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Post not found")
    return rows[0]


def _need_quota(user: dict[str, Any]) -> None:
    info = studio.plan_info(_db(), user["id"])
    if info["remaining"] <= 0:
        raise HTTPException(status_code=429, detail=(
            f"Monthly LinkedIn post limit reached ({info['limit']}, including scheduled posts)."))


async def _publish_now(user: dict[str, Any], post_id: str) -> dict[str, Any]:
    supabase = _db()

    def _claim():
        return supabase.table("linkedin_posts").update({
            "status": "publishing", "attempts": 1, "next_attempt_at": None, "error": None,
            "scheduled_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("id", post_id).eq("user_id", user["id"]).in_("status", list(EDITABLE)).execute().data or []

    claimed = await asyncio.to_thread(_claim)
    if not claimed:
        raise HTTPException(status_code=409, detail="This post is already publishing or published.")
    await asyncio.to_thread(studio.publish, supabase, claimed[0])
    return await asyncio.to_thread(_load_post, user["id"], post_id)


@router.get("/posts")
async def list_posts(
    status: str | None = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    def _q():
        q = _db().table("linkedin_posts").select("*").eq("user_id", user["id"])
        if status:
            q = q.in_("status", [s for s in status.split(",") if s])
        if start:
            q = q.gte("scheduled_at", start.isoformat())
        if end:
            q = q.lt("scheduled_at", end.isoformat())
        return q.order("scheduled_at", desc=False, nullsfirst=True).limit(limit).execute().data or []

    return {"posts": await asyncio.to_thread(_q)}


@router.post("/posts", status_code=201)
async def create_post(body: PostIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    uid = user["id"]
    try:
        media = studio.validate_media(uid, [m.model_dump() for m in body.media])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    row: dict[str, Any] = {"user_id": uid, "commentary": body.commentary, "media": media,
                           "visibility": body.visibility, "source": body.source, "status": "draft"}
    if body.account_id:
        row["account_id"] = (await asyncio.to_thread(_own_account, uid, body.account_id))["id"]
    if body.scheduled_at:
        row["scheduled_at"] = (body.scheduled_at if body.scheduled_at.tzinfo
                               else body.scheduled_at.replace(tzinfo=timezone.utc)).isoformat()
    if body.action != "draft":
        _ready_to_publish(row)
        await asyncio.to_thread(_own_account, uid, body.account_id)
        await asyncio.to_thread(_need_quota, user)
    if body.action == "schedule":
        if not body.scheduled_at:
            raise HTTPException(status_code=400, detail="Pick a date and time to schedule.")
        row["scheduled_at"] = _check_schedule_time(body.scheduled_at).isoformat()
        row["status"] = "scheduled"
    saved = (await asyncio.to_thread(lambda: _db().table("linkedin_posts").insert(row).execute())).data[0]
    if body.action == "publish_now":
        return await _publish_now(user, saved["id"])
    return saved


@router.patch("/posts/{post_id}")
async def update_post(post_id: str, body: PostPatch, user: dict = Depends(require_studio)) -> dict[str, Any]:
    uid = user["id"]
    post = await asyncio.to_thread(_load_post, uid, post_id)
    if post["status"] not in EDITABLE:
        raise HTTPException(status_code=409, detail=f"A {post['status']} post can't be edited.")
    fields: dict[str, Any] = {}
    if body.commentary is not None:
        fields["commentary"] = body.commentary.strip()
    if body.media is not None:
        try:
            fields["media"] = studio.validate_media(uid, [m.model_dump() for m in body.media])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    if body.visibility is not None:
        fields["visibility"] = body.visibility
    if body.account_id is not None:
        fields["account_id"] = (await asyncio.to_thread(_own_account, uid, body.account_id))["id"]
    if body.scheduled_at is not None:
        at = _check_schedule_time(body.scheduled_at) if post["status"] == "scheduled" else body.scheduled_at
        fields["scheduled_at"] = (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).isoformat()
    if not fields:
        return post
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    return (await asyncio.to_thread(lambda: _db().table("linkedin_posts").update(fields)
                                    .eq("id", post_id).eq("user_id", uid).execute())).data[0]


@router.post("/posts/{post_id}/schedule")
async def schedule_post(post_id: str, body: ScheduleIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    """Approve a draft (or re-schedule) for a time."""
    uid = user["id"]
    post = await asyncio.to_thread(_load_post, uid, post_id)
    if post["status"] not in EDITABLE:
        raise HTTPException(status_code=409, detail=f"A {post['status']} post can't be scheduled.")
    _ready_to_publish(post)
    await asyncio.to_thread(_own_account, uid, post.get("account_id"))
    if post["status"] != "scheduled":
        await asyncio.to_thread(_need_quota, user)
    at = _check_schedule_time(body.scheduled_at)
    return (await asyncio.to_thread(lambda: _db().table("linkedin_posts").update({
        "status": "scheduled", "scheduled_at": at.isoformat(), "attempts": 0, "error": None,
        "next_attempt_at": None, "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", post_id).eq("user_id", uid).execute())).data[0]


@router.post("/posts/{post_id}/publish-now")
async def publish_now(post_id: str, user: dict = Depends(require_studio)) -> dict[str, Any]:
    uid = user["id"]
    post = await asyncio.to_thread(_load_post, uid, post_id)
    _ready_to_publish(post)
    await asyncio.to_thread(_own_account, uid, post.get("account_id"))
    if post["status"] != "scheduled":
        await asyncio.to_thread(_need_quota, user)
    return await _publish_now(user, post_id)


@router.post("/posts/{post_id}/cancel")
async def cancel_post(post_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = user["id"]
    rows = await asyncio.to_thread(lambda: _db().table("linkedin_posts").update({
        "status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", post_id).eq("user_id", uid).in_("status", ["scheduled", "failed", "needs_reconnect", "draft"])
        .execute().data or [])
    if not rows:
        raise HTTPException(status_code=409, detail="Only unpublished posts can be cancelled.")
    return rows[0]


@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    uid = user["id"]
    post = await asyncio.to_thread(_load_post, uid, post_id)
    if post["status"] == "publishing":
        raise HTTPException(status_code=409, detail="The post is being published right now - try again in a moment.")
    removed_from_linkedin = False
    if post["status"] == "published" and post.get("linkedin_post_urn"):
        try:
            await asyncio.to_thread(studio.delete_published, _db(), post)
            removed_from_linkedin = True
        except li.LinkedInError as exc:
            raise HTTPException(status_code=502, detail=f"Could not delete it on LinkedIn: {exc}")
    await asyncio.to_thread(lambda: _db().table("linkedin_posts").delete().eq("id", post_id).eq("user_id", uid).execute())
    return {"deleted": True, "removed_from_linkedin": removed_from_linkedin}


# ------------------------------------------------------------ autopilot

class SlotIn(BaseModel):
    dow: int = Field(..., ge=0, le=6)          # 0 = Monday
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class AutopilotIn(BaseModel):
    enabled: bool = False
    auto_approve: bool = False
    consent: bool = False                     # required to turn auto_approve on
    account_id: str | None = None
    timezone: str = Field("Asia/Kolkata", max_length=64)
    slots: list[SlotIn] = Field(default_factory=list, max_length=21)
    pillars: list[str] = Field(default_factory=list, max_length=10)
    audience: str | None = Field(None, max_length=300)
    voice_profile: str | None = Field(None, max_length=3000)
    lookahead_days: int = Field(7, ge=1, le=14)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError("Unknown timezone")
        return v

    @field_validator("pillars")
    @classmethod
    def _pillars(cls, v: list[str]) -> list[str]:
        return [p.strip()[:120] for p in v if p.strip()]


@router.get("/autopilot")
async def get_autopilot(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = await asyncio.to_thread(lambda: _db().table("linkedin_autopilot").select("*")
                                   .eq("user_id", user["id"]).limit(1).execute().data or [])
    return rows[0] if rows else {"enabled": False, "auto_approve": False, "slots": [], "pillars": [],
                                 "timezone": "Asia/Kolkata", "lookahead_days": 7}


@router.put("/autopilot")
async def put_autopilot(body: AutopilotIn, user: dict = Depends(require_studio)) -> dict[str, Any]:
    uid = user["id"]
    if body.enabled:
        await asyncio.to_thread(_own_account, uid, body.account_id)
        if not body.slots:
            raise HTTPException(status_code=400, detail="Add at least one posting day and time.")
        brand_topics = ((await asyncio.to_thread(_brand, uid)) or {}).get("topics") or []
        if not body.pillars and not brand_topics:
            raise HTTPException(status_code=400, detail="Add at least one content topic (pillar).")
        if not body.pillars:
            body.pillars = list(brand_topics)
    existing = (await asyncio.to_thread(lambda: _db().table("linkedin_autopilot").select("consent_at")
                                        .eq("user_id", uid).limit(1).execute().data or [])) or [{}]
    consent_at = existing[0].get("consent_at")
    if body.auto_approve and not (body.consent or consent_at):
        raise HTTPException(status_code=400, detail=(
            "Posting without approval needs your explicit consent: AI-written posts will be "
            "published on your LinkedIn automatically at your scheduled times."))
    if body.auto_approve and body.consent and not consent_at:
        consent_at = datetime.now(timezone.utc).isoformat()
    row = {
        "user_id": uid, "enabled": body.enabled, "auto_approve": body.auto_approve,
        "consent_at": consent_at, "account_id": body.account_id, "timezone": body.timezone,
        "slots": [s.model_dump() for s in body.slots], "pillars": body.pillars,
        "audience": body.audience, "voice_profile": body.voice_profile,
        "lookahead_days": body.lookahead_days, "last_planned_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return (await asyncio.to_thread(lambda: _db().table("linkedin_autopilot")
                                    .upsert(row, on_conflict="user_id").execute())).data[0]


@router.post("/autopilot/run")
async def run_autopilot_now(user: dict = Depends(require_studio)) -> dict[str, Any]:
    from app.services.linkedin_scheduler import plan_autopilot

    rows = await asyncio.to_thread(lambda: _db().table("linkedin_autopilot").select("*")
                                   .eq("user_id", user["id"]).limit(1).execute().data or [])
    if not rows or not rows[0].get("enabled"):
        raise HTTPException(status_code=400, detail="Turn autopilot on first.")
    await _ai_unit(user)
    try:
        created = await asyncio.to_thread(plan_autopilot, _db(), rows[0])
    except writer.WriterError as exc:
        await _refund_ai(user)
        raise HTTPException(status_code=502, detail=str(exc))
    await asyncio.to_thread(lambda: _db().table("linkedin_autopilot").update(
        {"last_planned_at": datetime.now(timezone.utc).isoformat()}).eq("user_id", user["id"]).execute())
    return {"created": created}
