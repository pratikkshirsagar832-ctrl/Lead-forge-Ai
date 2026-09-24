"""Auth middleware: single-flight verification, 401 only for bad tokens,
503 (not a logout) when Supabase Auth is unreachable."""
import asyncio
import time
import types

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import app.middleware.auth_middleware as am
from supabase_auth.errors import AuthApiError, AuthRetryableError


class _Q:
    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return types.SimpleNamespace(data=[{"id": 1}])


@pytest.fixture
def fake(monkeypatch):
    state = {"calls": 0, "mode": "ok"}

    class Auth:
        def get_user(self, token):
            state["calls"] += 1
            time.sleep(0.05)
            if state["mode"] == "bad":
                raise AuthApiError("invalid JWT", 401, None)
            if state["mode"] == "down":
                raise AuthRetryableError("timeout", 0)
            return types.SimpleNamespace(user=types.SimpleNamespace(id="u1", email="a@b.c", user_metadata={}))

    class SB:
        auth = Auth()

        def table(self, name):
            return _Q()

    monkeypatch.setattr(am, "get_supabase_admin", lambda: SB())
    monkeypatch.setattr(am.time, "sleep", lambda s: None if s > 0.1 else None)
    am._token_cache.clear()
    return state


def _cred(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_concurrent_requests_share_one_check(fake):
    async def run():
        return await asyncio.gather(*[am.get_current_user(_cred("tok-a")) for _ in range(8)])

    users = asyncio.run(run())
    assert fake["calls"] == 1 and all(u["id"] == "u1" for u in users)
    asyncio.run(am.get_current_user(_cred("tok-a")))  # cached
    assert fake["calls"] == 1


def test_invalid_token_is_401(fake):
    fake["mode"] = "bad"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(am.get_current_user(_cred("tok-b")))
    assert exc.value.status_code == 401


def test_supabase_outage_is_503_not_logout(fake):
    fake["mode"] = "down"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(am.get_current_user(_cred("tok-c")))
    assert exc.value.status_code == 503
    assert fake["calls"] == 2  # retried once


def test_expired_jwt_rejected_without_network(fake):
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"exp": int(time.time()) - 10}).encode()).decode().rstrip("=")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(am.get_current_user(_cred(f"h.{payload}.s")))
    assert exc.value.status_code == 401 and fake["calls"] == 0
