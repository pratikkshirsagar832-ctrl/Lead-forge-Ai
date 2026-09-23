"""LinkedIn official API client (OAuth 2.0 + REST Posts / Images / Documents).

Only LinkedIn's own endpoints are used:
  OAuth       https://www.linkedin.com/oauth/v2/{authorization,accessToken}
  Identity    https://api.linkedin.com/v2/userinfo            (OpenID Connect)
  Pages       https://api.linkedin.com/rest/organizationAcls   (Community Mgmt API)
  Media       https://api.linkedin.com/rest/{images,documents}?action=initializeUpload
  Posts       https://api.linkedin.com/rest/posts

Two LinkedIn apps (LinkedIn requires Community Management API on its own app):
  "member" - Sign In with LinkedIn (OIDC) + Share on LinkedIn -> personal posts
  "pages"  - Community Management API -> company-page posts (after approval)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
MEMBER_SCOPES = "openid profile email w_member_social"
PAGES_SCOPES = "r_basicprofile w_member_social r_organization_social w_organization_social rw_organization_admin"
POSTING_ROLES = ("ADMINISTRATOR", "CONTENT_ADMINISTRATOR", "DIRECT_SPONSORED_CONTENT_POSTER")
STATE_TTL_S = 600
MAX_COMMENTARY = 3000


class LinkedInError(Exception):
    """kind: auth (reconnect needed) | rate_limited | transient | invalid | config"""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class TokenSet:
    access_token: str
    expires_in: int
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
    scope: str = ""


# ------------------------------------------------------------------ OAuth

def _app_credentials(app: str) -> tuple[str, str]:
    s = get_settings()
    if app == "pages":
        if not s.linkedin_pages_enabled:
            raise LinkedInError("config", "Company pages are not enabled yet (awaiting LinkedIn approval).")
        cid, secret = s.linkedin_pages_client_id, s.linkedin_pages_client_secret
    else:
        cid, secret = s.linkedin_client_id, s.linkedin_client_secret
    if not cid or not secret:
        raise LinkedInError("config", f"LinkedIn {app} app is not configured.")
    return cid, secret


def _state_key() -> bytes:
    s = get_settings()
    material = (s.linkedin_token_key or s.linkedin_client_secret or "hyperclients-li-state").encode()
    return hashlib.sha256(b"li-oauth-state|" + material).digest()


def sign_state(user_id: str, app: str, now: float | None = None) -> str:
    """Opaque, tamper-proof OAuth `state`: who started the flow, which app,
    when (expires after 10 min) + a nonce."""
    payload = json.dumps({"u": user_id, "a": app, "t": int(now or time.time()),
                          "n": secrets.token_urlsafe(8)}, separators=(",", ":")).encode()
    mac = hmac.new(_state_key(), payload, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(payload + mac).decode().rstrip("=")


def verify_state(state: str, now: float | None = None) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(state + "=" * (-len(state) % 4))
        payload, mac = raw[:-16], raw[-16:]
    except (ValueError, TypeError):
        raise LinkedInError("invalid", "Invalid OAuth state")
    expected = hmac.new(_state_key(), payload, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        raise LinkedInError("invalid", "Invalid OAuth state")
    data = json.loads(payload)
    if (now or time.time()) - int(data["t"]) > STATE_TTL_S:
        raise LinkedInError("invalid", "The LinkedIn connection link expired. Please try again.")
    return data


def authorize_url(user_id: str, app: str = "member") -> str:
    cid, _ = _app_credentials(app)
    return AUTH_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": get_settings().linkedin_redirect_uri,
        "state": sign_state(user_id, app),
        "scope": PAGES_SCOPES if app == "pages" else MEMBER_SCOPES,
    })


def _token_request(app: str, data: dict[str, str]) -> TokenSet:
    cid, secret = _app_credentials(app)
    resp = httpx.post(TOKEN_URL, data={**data, "client_id": cid, "client_secret": secret}, timeout=20)
    if resp.status_code != 200:
        raise LinkedInError("auth", f"LinkedIn token request failed: {_err_text(resp)}", resp.status_code)
    body = resp.json()
    return TokenSet(
        access_token=body["access_token"],
        expires_in=int(body.get("expires_in") or 0),
        refresh_token=body.get("refresh_token"),
        refresh_expires_in=int(body["refresh_token_expires_in"]) if body.get("refresh_token_expires_in") else None,
        scope=body.get("scope") or "",
    )


def exchange_code(app: str, code: str) -> TokenSet:
    return _token_request(app, {"grant_type": "authorization_code", "code": code,
                                "redirect_uri": get_settings().linkedin_redirect_uri})


def refresh(app: str, refresh_token: str) -> TokenSet:
    return _token_request(app, {"grant_type": "refresh_token", "refresh_token": refresh_token})


# ------------------------------------------------------------------ HTTP

def _headers(token: str, json_body: bool = True) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": get_settings().linkedin_api_version,
        "X-Restli-Protocol-Version": "2.0.0",
    }
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _err_text(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("message") or body.get("error_description") or body.get("error") or body)[:300]
    except ValueError:
        return (resp.text or "")[:300]


def _raise_for(resp: httpx.Response, what: str) -> None:
    code = resp.status_code
    if code < 400:
        return
    msg = f"{what}: {_err_text(resp)}"
    if code == 401:
        raise LinkedInError("auth", msg, code)
    if code == 429:
        raise LinkedInError("rate_limited", msg, code)
    if code >= 500:
        raise LinkedInError("transient", msg, code)
    if code == 403 and "scope" in msg.lower():
        raise LinkedInError("auth", msg, code)
    raise LinkedInError("invalid", msg, code)


def _request(method: str, url: str, token: str, what: str, **kw) -> httpx.Response:
    try:
        resp = httpx.request(method, url, headers=_headers(token, "json" in kw), timeout=60, **kw)
    except httpx.HTTPError as exc:
        raise LinkedInError("transient", f"{what}: {exc}")
    _raise_for(resp, what)
    return resp


# --------------------------------------------------------------- identity

def member_profile(token: str) -> dict[str, Any]:
    """OpenID userinfo -> {urn, name, avatar_url, email}."""
    body = _request("GET", f"{API}/v2/userinfo", token, "userinfo").json()
    return {
        "urn": f"urn:li:person:{body['sub']}",
        "name": body.get("name") or " ".join(filter(None, [body.get("given_name"), body.get("family_name")])),
        "avatar_url": body.get("picture"),
        "email": body.get("email"),
    }


def admin_organizations(token: str) -> list[dict[str, Any]]:
    """Company pages this member may post for (Community Management API)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role in POSTING_ROLES:
        url = f"{API}/rest/organizationAcls?q=roleAssignee&role={role}&state=APPROVED&count=100"
        try:
            elements = _request("GET", url, token, "organizationAcls").json().get("elements", [])
        except LinkedInError as exc:
            if exc.kind == "invalid":
                continue
            raise
        for el in elements:
            org = el.get("organization") or el.get("organizationTarget")
            if not org or org in seen:
                continue
            seen.add(org)
            org_id = org.rsplit(":", 1)[-1]
            name = None
            try:
                info = _request("GET", f"{API}/rest/organizations/{org_id}", token, "organization").json()
                name = info.get("localizedName") or (info.get("name") or {}).get("localized", {}).get("en_US")
            except LinkedInError:
                pass
            out.append({"urn": org, "name": name or f"Company page {org_id}", "avatar_url": None})
    return out


# ------------------------------------------------------------------ media

def _upload(kind: str, token: str, owner: str, data: bytes) -> str:
    """kind: images | documents. Returns the asset URN."""
    init = _request("POST", f"{API}/rest/{kind}?action=initializeUpload", token, f"{kind} init",
                    json={"initializeUploadRequest": {"owner": owner}}).json()["value"]
    urn = init.get("image") or init.get("document")
    try:
        put = httpx.put(init["uploadUrl"], content=data, timeout=180,
                        headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise LinkedInError("transient", f"{kind} upload: {exc}")
    _raise_for(put, f"{kind} upload")
    return urn


def upload_image(token: str, owner: str, data: bytes) -> str:
    return _upload("images", token, owner, data)


def upload_document(token: str, owner: str, data: bytes) -> str:
    return _upload("documents", token, owner, data)


# ------------------------------------------------------------------ posts

_RESERVED = re.compile(r"([\\|{}@\[\]()<>*_~])")
_HASHTAG = re.compile(r"(?<![\w#])#(\w{1,100})")


def to_little_text(text: str) -> str:
    """Escape LinkedIn 'little text' reserved characters so the commentary is
    published verbatim; #hashtags become real (clickable) hashtags."""
    escaped = _RESERVED.sub(r"\\\1", text or "")
    parts: list[str] = []
    last = 0
    for m in _HASHTAG.finditer(escaped):
        parts.append(escaped[last:m.start()].replace("#", "\\#"))
        parts.append("{hashtag|\\#|" + m.group(1) + "}")
        last = m.end()
    parts.append(escaped[last:].replace("#", "\\#"))
    return "".join(parts)


def build_post_body(author: str, commentary: str, visibility: str = "PUBLIC",
                    media: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Posts API payload. `media` items carry an uploaded `urn` + type."""
    body: dict[str, Any] = {
        "author": author,
        "commentary": to_little_text(commentary)[:MAX_COMMENTARY * 2],
        "visibility": visibility if visibility in ("PUBLIC", "CONNECTIONS") else "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    media = [m for m in (media or []) if m.get("urn")]
    docs = [m for m in media if m.get("type") == "document"]
    images = [m for m in media if m.get("type") == "image"]
    if docs:
        d = docs[0]
        body["content"] = {"media": {"id": d["urn"], "title": (d.get("title") or "Document")[:200]}}
    elif len(images) == 1:
        img = images[0]
        body["content"] = {"media": {"id": img["urn"], "altText": (img.get("alt") or "")[:4000]}}
    elif len(images) > 1:
        body["content"] = {"multiImage": {"images": [
            {"id": i["urn"], "altText": (i.get("alt") or "")[:4000]} for i in images[:20]]}}
    return body


def create_post(token: str, body: dict[str, Any]) -> tuple[str, str]:
    """Publish; returns (post URN, public post URL)."""
    resp = _request("POST", f"{API}/rest/posts", token, "create post", json=body)
    urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id") or ""
    if not urn:
        raise LinkedInError("transient", "LinkedIn did not return the post id")
    return urn, f"https://www.linkedin.com/feed/update/{urn}/"


def delete_post(token: str, urn: str) -> None:
    _request("DELETE", f"{API}/rest/posts/{quote(urn, safe='')}", token, "delete post")
