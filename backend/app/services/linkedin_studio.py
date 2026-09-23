"""LinkedIn Studio core: accounts, plan gate/quota, media storage, publishing.

Synchronous (blocking Supabase + HTTP) - call from worker threads or via
asyncio.to_thread. The API router and the background scheduler share these
functions, so "Post now" and scheduled posts follow exactly the same path.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.services import linkedin_api as li
from app.services import token_crypto

logger = logging.getLogger(__name__)

BUCKET = "linkedin-media"
PLAN_DEFAULT_LIMITS = {"pro": 60, "agency": 200}
MAX_ATTEMPTS = 3
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}
DOC_TYPES = {"application/pdf": "pdf"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_DOC_BYTES = 100 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ------------------------------------------------------------ plan + quota

def plan_info(supabase, user_id: str) -> dict[str, Any]:
    """{plan_id, quota_user, limit, used, scheduled, remaining} for this month."""
    from app.services.plans import quota_owner_id, resolve_effective_subscription

    eff = resolve_effective_subscription(supabase, user_id)
    plan_id = eff.get("plan_id") or "free"
    quota_user = quota_owner_id(eff, user_id)
    active = eff.get("status") in ("active", "trial")
    limit = 0
    try:
        row = (supabase.table("plans").select("linkedin_posts_monthly").eq("id", plan_id)
               .limit(1).execute().data or [{}])[0]
        limit = int(row.get("linkedin_posts_monthly") or 0)
    except Exception:  # noqa: BLE001 - column missing before v21
        limit = PLAN_DEFAULT_LIMITS.get(plan_id, 0)
    if not active:
        limit = 0
    month = _now().replace(day=1).date().isoformat()
    used = 0
    try:
        u = (supabase.table("monthly_usage").select("linkedin_posts_used").eq("user_id", quota_user)
             .eq("usage_month", month).limit(1).execute().data or [{}])[0]
        used = int(u.get("linkedin_posts_used") or 0)
    except Exception:  # noqa: BLE001
        used = 0
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    scheduled = (supabase.table("linkedin_posts").select("id", count="exact").eq("user_id", user_id)
                 .in_("status", ["scheduled", "publishing"])
                 .gte("scheduled_at", _iso(month_start)).lt("scheduled_at", _iso(month_end))
                 .execute().count or 0)
    return {"plan_id": plan_id, "quota_user": quota_user, "limit": limit, "used": used,
            "scheduled": int(scheduled), "remaining": max(0, limit - used - int(scheduled)),
            "enabled": limit > 0}


def consume_post_quota(supabase, quota_user: str, limit: int) -> bool:
    try:
        r = supabase.rpc("consume_linkedin_post_quota", {"p_user_id": quota_user, "p_limit": limit}).execute()
        return r.data == -1 or r.data is None
    except Exception as exc:  # noqa: BLE001 - never block a published post on accounting
        logger.warning("LinkedIn post quota consume failed for %s: %s", quota_user[:8], exc)
        return True


# ---------------------------------------------------------------- accounts

def save_connection(supabase, user_id: str, app: str, tokens: li.TokenSet,
                    identities: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Upsert connected identities (a person, or each administered page)."""
    now = _now()
    saved = []
    for ident in identities:
        row = {
            "user_id": user_id, "kind": kind, "urn": ident["urn"], "name": ident.get("name"),
            "avatar_url": ident.get("avatar_url"), "app": app,
            "access_token_enc": token_crypto.encrypt(tokens.access_token),
            "refresh_token_enc": token_crypto.encrypt(tokens.refresh_token),
            "expires_at": _iso(now + timedelta(seconds=tokens.expires_in)) if tokens.expires_in else None,
            "refresh_expires_at": (_iso(now + timedelta(seconds=tokens.refresh_expires_in))
                                   if tokens.refresh_expires_in else None),
            "scopes": tokens.scope, "status": "active", "updated_at": _iso(now),
        }
        resp = supabase.table("linkedin_accounts").upsert(row, on_conflict="user_id,urn").execute()
        saved.extend(resp.data or [row])
    # Posts waiting on a reconnect can go again now.
    urns = [i["urn"] for i in identities]
    acc_ids = [a["id"] for a in (supabase.table("linkedin_accounts").select("id,urn").eq("user_id", user_id)
                                 .execute().data or []) if a["urn"] in urns]
    for aid in acc_ids:
        supabase.table("linkedin_posts").update({"status": "scheduled", "error": None, "attempts": 0,
                                                 "next_attempt_at": None}) \
            .eq("account_id", aid).eq("status", "needs_reconnect").execute()
    return saved


def public_account(row: dict[str, Any]) -> dict[str, Any]:
    exp = _parse(row.get("expires_at"))
    days_left = None
    if exp:
        days_left = max(0, (exp - _now()).days)
    status = row.get("status") or "active"
    if status == "active" and exp and exp <= _now() and not row.get("refresh_token_enc"):
        status = "expired"
    return {
        "id": row["id"], "kind": row.get("kind"), "name": row.get("name"), "avatar_url": row.get("avatar_url"),
        "urn": row.get("urn"), "app": row.get("app"), "status": status, "expires_at": row.get("expires_at"),
        "days_left": days_left,
        "needs_reconnect_soon": bool(days_left is not None and days_left <= 7 and not row.get("refresh_token_enc")),
    }


def account_token(supabase, account: dict[str, Any]) -> str:
    """A usable access token (refreshing Pages tokens when possible)."""
    if account.get("status") != "active":
        raise li.LinkedInError("auth", "LinkedIn account is disconnected - please reconnect.")
    exp = _parse(account.get("expires_at"))
    refresh_enc = account.get("refresh_token_enc")
    if exp and exp - _now() < timedelta(days=3) and refresh_enc:
        try:
            tokens = li.refresh(account.get("app") or "pages", token_crypto.decrypt(refresh_enc))
            now = _now()
            supabase.table("linkedin_accounts").update({
                "access_token_enc": token_crypto.encrypt(tokens.access_token),
                "refresh_token_enc": token_crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else refresh_enc,
                "expires_at": _iso(now + timedelta(seconds=tokens.expires_in)),
                "updated_at": _iso(now),
            }).eq("id", account["id"]).execute()
            return tokens.access_token
        except li.LinkedInError as exc:
            logger.warning("LinkedIn token refresh failed for account %s: %s", account["id"], exc)
    if exp and exp <= _now():
        mark_account_expired(supabase, account["id"])
        raise li.LinkedInError("auth", "LinkedIn connection expired - please reconnect.")
    return token_crypto.decrypt(account["access_token_enc"])


def mark_account_expired(supabase, account_id: str) -> None:
    supabase.table("linkedin_accounts").update({"status": "expired", "updated_at": _iso(_now())}) \
        .eq("id", account_id).execute()


# ------------------------------------------------------------------ media

def store_media(supabase, user_id: str, data: bytes, content_type: str, filename: str) -> dict[str, Any]:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in IMAGE_TYPES:
        kind, ext, cap = "image", IMAGE_TYPES[ctype], MAX_IMAGE_BYTES
    elif ctype in DOC_TYPES:
        kind, ext, cap = "document", DOC_TYPES[ctype], MAX_DOC_BYTES
    else:
        raise ValueError("Only JPG, PNG, GIF images or PDF documents are supported.")
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > cap:
        raise ValueError(f"File too large (max {cap // (1024 * 1024)} MB for {kind}s).")
    if kind == "document" and not data.startswith(b"%PDF"):
        raise ValueError("The file is not a valid PDF.")
    path = f"{user_id}/{uuid.uuid4().hex}.{ext}"
    supabase.storage.from_(BUCKET).upload(path, data, {"content-type": ctype, "upsert": "false"})
    title = (filename or "").rsplit(".", 1)[0][:200] or ("Document" if kind == "document" else "")
    return {"type": kind, "storage_path": path, "title": title, "alt": "", "size": len(data)}


def _load_media(supabase, path: str) -> bytes:
    return supabase.storage.from_(BUCKET).download(path)


def validate_media(user_id: str, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise a post's media list: only this user's files, valid mix."""
    clean = []
    for m in media or []:
        path = str(m.get("storage_path") or "")
        if not path.startswith(f"{user_id}/") or ".." in path:
            raise ValueError("Invalid media reference.")
        if m.get("type") not in ("image", "document"):
            raise ValueError("Invalid media type.")
        clean.append({"type": m["type"], "storage_path": path, "title": str(m.get("title") or "")[:200],
                      "alt": str(m.get("alt") or "")[:500], "urn": m.get("urn")})
    docs = [m for m in clean if m["type"] == "document"]
    imgs = [m for m in clean if m["type"] == "image"]
    if docs and imgs:
        raise ValueError("A post can have images OR one document, not both.")
    if len(docs) > 1:
        raise ValueError("A post can have only one document.")
    if len(imgs) > 20:
        raise ValueError("A post can have at most 20 images.")
    return clean


# -------------------------------------------------------------- publishing

def _update(supabase, post_id: str, **fields) -> None:
    fields["updated_at"] = _iso(_now())
    supabase.table("linkedin_posts").update(fields).eq("id", post_id).execute()


def publish(supabase, post: dict[str, Any]) -> dict[str, Any]:
    """Publish one post that is already claimed ('publishing'). Always leaves
    the row in a final or retryable state; returns the updated fields."""
    settings = get_settings()
    pid = post["id"]
    attempts = int(post.get("attempts") or 1)

    def fail(status: str, message: str, retry: bool = False) -> dict[str, Any]:
        if retry and attempts < MAX_ATTEMPTS:
            nxt = _now() + timedelta(minutes=2 ** attempts * 2)
            fields = {"status": "scheduled", "error": message[:500], "next_attempt_at": _iso(nxt)}
        else:
            fields = {"status": status, "error": message[:500]}
        _update(supabase, pid, **fields)
        return fields

    acc_rows = (supabase.table("linkedin_accounts").select("*").eq("id", post.get("account_id") or "")
                .limit(1).execute().data or []) if post.get("account_id") else []
    if not acc_rows:
        return fail("needs_reconnect", "No LinkedIn account selected - connect one and reschedule.")
    account = acc_rows[0]

    info = plan_info(supabase, post["user_id"])
    if not info["enabled"]:
        return fail("failed", "Your plan does not include LinkedIn Studio (Pro or Agency required).")
    if info["used"] >= info["limit"]:
        return fail("failed", f"Monthly LinkedIn post limit reached ({info['limit']}).")

    day_ago = _iso(_now() - timedelta(hours=24))
    published_today = (supabase.table("linkedin_posts").select("id", count="exact")
                       .eq("account_id", account["id"]).eq("status", "published")
                       .gte("published_at", day_ago).execute().count or 0)
    if published_today >= settings.linkedin_daily_post_cap:
        nxt = _now() + timedelta(hours=1)
        _update(supabase, pid, status="scheduled", next_attempt_at=_iso(nxt), attempts=max(0, attempts - 1),
                error=f"Daily safety limit ({settings.linkedin_daily_post_cap} posts/day) reached - retrying later.")
        return {"status": "scheduled"}

    try:
        token = account_token(supabase, account)
        media = list(post.get("media") or [])
        for m in media:
            if m.get("urn"):
                continue
            data = _load_media(supabase, m["storage_path"])
            m["urn"] = (li.upload_document(token, account["urn"], data) if m["type"] == "document"
                        else li.upload_image(token, account["urn"], data))
        if media:
            _update(supabase, pid, media=media)  # never re-upload on a retry
        body = li.build_post_body(account["urn"], post.get("commentary") or "",
                                  post.get("visibility") or "PUBLIC", media)
        urn, url = li.create_post(token, body)
    except li.LinkedInError as exc:
        if exc.kind == "auth":
            mark_account_expired(supabase, account["id"])
            return fail("needs_reconnect", "LinkedIn connection expired or was revoked - please reconnect.")
        if exc.kind in ("rate_limited", "transient"):
            return fail("failed", str(exc), retry=True)
        return fail("failed", str(exc))
    except token_crypto.TokenCryptoError as exc:
        return fail("needs_reconnect", str(exc))
    except Exception as exc:  # noqa: BLE001 - storage or unexpected -> retry then fail
        logger.exception("LinkedIn publish failed for post %s", pid)
        return fail("failed", f"Publishing failed: {exc}", retry=True)

    fields = {"status": "published", "linkedin_post_urn": urn, "post_url": url,
              "published_at": _iso(_now()), "error": None, "next_attempt_at": None}
    _update(supabase, pid, **fields)
    consume_post_quota(supabase, info["quota_user"], info["limit"])
    logger.info("LinkedIn post %s published as %s", pid, urn)
    return fields


def delete_published(supabase, post: dict[str, Any]) -> None:
    acc = (supabase.table("linkedin_accounts").select("*").eq("id", post.get("account_id") or "")
           .limit(1).execute().data or [None])[0]
    if acc and post.get("linkedin_post_urn"):
        li.delete_post(account_token(supabase, acc), post["linkedin_post_urn"])
