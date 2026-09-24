"""Bearer-token auth for every API route.

The Supabase access token is verified with Supabase Auth (`/auth/v1/user`),
which also rejects revoked sessions. Three properties matter for users on
flaky mobile networks and for several devices sharing one account:

* the check runs OFF the event loop (a slow Supabase call never stalls other
  requests) and concurrent requests carrying the same token share ONE check;
* only a genuinely invalid/expired/revoked token is a 401 (the frontend then
  refreshes or signs out). A network error, timeout or Supabase 5xx/429 is a
  503 - the user stays logged in and simply retries;
* results are cached briefly (never past the token's own expiry).
"""
import asyncio
import base64
import json
import logging
import time

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_supabase_admin

try:  # supabase-py >= 2.10 ships the auth client as `supabase_auth`
    from supabase_auth.errors import AuthApiError, AuthError, AuthRetryableError
except ImportError:  # pragma: no cover - older installs
    from gotrue.errors import AuthApiError, AuthError, AuthRetryableError  # type: ignore

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_token_cache: dict[str, dict] = {}
CACHE_TTL = 60
_last_cache_cleanup = time.time()
CACHE_CLEANUP_INTERVAL = 300  # purge expired entries every 5 minutes

_inflight: dict[str, asyncio.Future] = {}
_subscription_checked: set[str] = set()


class _InvalidToken(Exception):
    pass


class _AuthUnavailable(Exception):
    pass


def _token_exp(token: str) -> float | None:
    """`exp` claim of a JWT (unverified - only used to bound the cache)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp"))
    except Exception:  # noqa: BLE001
        return None


def _ensure_subscription_row(supabase, user_id: str) -> None:
    """Safety net for accounts created before the signup trigger existed.
    Runs at most once per user per process (the DB trigger handle_new_user
    normally creates the row)."""
    if user_id in _subscription_checked:
        return
    try:
        existing = supabase.table("user_subscriptions").select("id").eq("user_id", user_id).limit(1).execute()
        if not existing.data:
            from datetime import datetime, timedelta, timezone

            now = datetime.now(timezone.utc)
            trial_days = 1
            try:
                plan_row = supabase.table("plans").select("trial_days").eq("id", "free").limit(1).execute()
                if plan_row.data and plan_row.data[0].get("trial_days") is not None:
                    trial_days = max(1, int(plan_row.data[0]["trial_days"]))
            except Exception:  # noqa: BLE001
                pass
            try:
                supabase.table("user_subscriptions").insert({
                    "user_id": user_id,
                    "plan_id": "free",
                    "status": "trial",
                    "trial_end": (now + timedelta(days=trial_days)).isoformat(),
                    "current_period_end": (now + timedelta(days=trial_days)).isoformat(),
                }).execute()
                logger.info("Created free trial subscription for user %s", user_id)
            except Exception:  # noqa: BLE001 - another request created it first
                pass
        _subscription_checked.add(user_id)
    except Exception as exc:  # noqa: BLE001 - never blocks login
        logger.warning("Subscription auto-creation failed (non-critical): %s", exc)


def _verify(token: str) -> dict:
    """Blocking Supabase check (run in a worker thread)."""
    supabase = get_supabase_admin()
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            user_resp = supabase.auth.get_user(token)
            break
        except AuthApiError as exc:
            code = int(getattr(exc, "status", 0) or 0)
            if code in (401, 403) or 400 <= code < 429:
                raise _InvalidToken(str(exc)) from exc
            last_exc = exc  # 429 / 5xx: Supabase is struggling, not the user
        except AuthRetryableError as exc:
            last_exc = exc
        except AuthError as exc:  # session missing / invalid JWT
            raise _InvalidToken(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - network / timeout
            last_exc = exc
        if attempt == 0:
            time.sleep(0.4)
    else:
        raise _AuthUnavailable(str(last_exc))

    if not user_resp or not user_resp.user:
        raise _InvalidToken("no user for token")
    user = user_resp.user
    meta = user.user_metadata or {}
    _ensure_subscription_row(supabase, user.id)
    return {
        "id": user.id,
        "email": user.email or "",
        "name": meta.get("full_name", meta.get("name", user.email or "")),
    }


def _cleanup_cache(now: float) -> None:
    global _last_cache_cleanup
    if now - _last_cache_cleanup > CACHE_CLEANUP_INTERVAL:
        for k in [k for k, v in _token_cache.items() if v["expires_at"] <= now]:
            _token_cache.pop(k, None)
        _last_cache_cleanup = now


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached["expires_at"] > now:
        return cached["user"]

    exp = _token_exp(token)
    if exp is not None and exp <= now:
        _token_cache.pop(token, None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please log in again.",
                            headers={"WWW-Authenticate": "Bearer"})

    # Single-flight: a dashboard load fires many requests with the same new
    # token at once - they all wait on ONE Supabase check.
    fut = _inflight.get(token)
    owner = fut is None
    if owner:
        fut = asyncio.get_running_loop().create_future()
        _inflight[token] = fut
        try:
            user = await asyncio.to_thread(_verify, token)
            ttl = CACHE_TTL if exp is None else max(1.0, min(CACHE_TTL, exp - time.time()))
            _cleanup_cache(time.time())
            _token_cache[token] = {"user": user, "expires_at": time.time() + ttl}
            fut.set_result(user)
        except BaseException as exc:  # noqa: BLE001 - forwarded to waiters below
            fut.set_exception(exc)
        finally:
            _inflight.pop(token, None)

    try:
        return await asyncio.shield(fut)
    except _InvalidToken as exc:
        _token_cache.pop(token, None)
        logger.debug("Rejected token: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session expired. Please log in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    except _AuthUnavailable as exc:
        logger.warning("Auth service unavailable: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Sign-in service is busy. Please retry in a moment.",
                            headers={"Retry-After": "2"})
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Auth check failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Sign-in service is busy. Please retry in a moment.",
                            headers={"Retry-After": "2"})


async def get_current_user_id(current_user: dict = Depends(get_current_user)) -> str:
    return current_user["id"]
