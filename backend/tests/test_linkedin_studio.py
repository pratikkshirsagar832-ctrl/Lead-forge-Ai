"""LinkedIn Studio: OAuth state, token encryption, Posts API payloads,
publishing/scheduler behaviour, autopilot, plan gate, AI writer. Offline -
LinkedIn HTTP and Supabase are faked."""
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import linkedin_api as li  # noqa: E402
from app.services import linkedin_scheduler as sched  # noqa: E402
from app.services import linkedin_studio as studio  # noqa: E402
from app.services import linkedin_writer as writer  # noqa: E402
from app.services import token_crypto  # noqa: E402

USER = "11111111-1111-1111-1111-111111111111"


# ------------------------------------------------------------------ fakes

class _Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.kind, self.payload = db, table, "select", None
        self.f, self._count, self._limit, self._order, self._conflict = [], None, None, None, None

    def select(self, _c="*", count=None):
        self._count = count
        return self

    def insert(self, p):
        self.kind, self.payload = "insert", p
        return self

    def upsert(self, p, on_conflict=None):
        self.kind, self.payload, self._conflict = "upsert", p, on_conflict
        return self

    def update(self, p):
        self.kind, self.payload = "update", p
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def eq(self, c, v):
        self.f.append(lambda r: r.get(c) == v)
        return self

    def in_(self, c, vs):
        self.f.append(lambda r, vs=tuple(vs): r.get(c) in vs)
        return self

    def gte(self, c, v):
        self.f.append(lambda r: r.get(c) is not None and str(r.get(c)) >= str(v))
        return self

    def lt(self, c, v):
        self.f.append(lambda r: r.get(c) is not None and str(r.get(c)) < str(v))
        return self

    def order(self, c, desc=False, nullsfirst=False):
        self._order = (c, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self.db.t.setdefault(self.table, [])
        if self.kind in ("insert", "upsert"):
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for it in items:
                if self.kind == "upsert" and self._conflict:
                    keys = self._conflict.split(",")
                    hit = next((r for r in rows if all(r.get(k) == it.get(k) for k in keys)), None)
                    if hit:
                        hit.update(it)
                        out.append(hit)
                        continue
                row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                       "attempts": 0, "media": [], **it}
                rows.append(row)
                out.append(row)
            return _Resp(out)
        match = [r for r in rows if all(fn(r) for fn in self.f)]
        if self.kind == "update":
            for r in match:
                r.update(self.payload)
            return _Resp(match)
        if self.kind == "delete":
            self.db.t[self.table] = [r for r in rows if r not in match]
            return _Resp(match)
        if self._limit is not None:
            match = match[: self._limit]
        return _Resp([dict(r) for r in match], count=len(match) if self._count else None)


class _Bucket:
    def __init__(self, store):
        self.store = store

    def upload(self, path, data, opts):
        self.store[path] = data

    def download(self, path):
        return self.store[path]


class _Storage:
    def __init__(self):
        self.files = {}

    def from_(self, _bucket):
        return _Bucket(self.files)


class FakeDB:
    def __init__(self):
        self.t, self.storage, self.rpcs = {}, _Storage(), []

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        db = self

        class R:
            def execute(self_inner):
                if name == "claim_due_linkedin_posts":
                    now = datetime.now(timezone.utc).isoformat()
                    due = [p for p in db.t.get("linkedin_posts", []) if p["status"] == "scheduled"
                           and p["scheduled_at"] <= now
                           and (not p.get("next_attempt_at") or p["next_attempt_at"] <= now)]
                    for p in due:
                        p["status"] = "publishing"
                        p["attempts"] = p.get("attempts", 0) + 1
                    return _Resp([dict(p) for p in due])
                return _Resp(-1)
        return R()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "linkedin_token_key", Fernet.generate_key().decode())
    monkeypatch.setattr(s, "linkedin_client_id", "cid")
    monkeypatch.setattr(s, "linkedin_client_secret", "csecret")
    monkeypatch.setattr(s, "linkedin_pages_enabled", False)
    token_crypto._fernet.cache_clear()


def _plan(monkeypatch, **over):
    info = {"plan_id": "pro", "quota_user": USER, "limit": 60, "used": 0, "scheduled": 0,
            "remaining": 60, "enabled": True, **over}
    monkeypatch.setattr(studio, "plan_info", lambda db, uid: dict(info))
    return info


def _account(db, **over):
    row = {"id": str(uuid.uuid4()), "user_id": USER, "kind": "person", "urn": "urn:li:person:abc",
           "app": "member", "status": "active", "access_token_enc": token_crypto.encrypt("tok"),
           "refresh_token_enc": None,
           "expires_at": (datetime.now(timezone.utc) + timedelta(days=50)).isoformat(), **over}
    db.t.setdefault("linkedin_accounts", []).append(row)
    return row


def _post(db, account, **over):
    row = {"id": str(uuid.uuid4()), "user_id": USER, "account_id": account["id"], "status": "scheduled",
           "commentary": "Need a video editor? We learned 3 things (the hard way). #video #editing",
           "media": [], "visibility": "PUBLIC", "attempts": 0,
           "scheduled_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), **over}
    db.t.setdefault("linkedin_posts", []).append(row)
    return row


# ------------------------------------------------------------ OAuth / crypto

def test_state_roundtrip_tamper_and_expiry():
    st = li.sign_state(USER, "member")
    assert li.verify_state(st)["u"] == USER
    tampered = st[:-2] + ("A" if st[-2] != "A" else "B") + st[-1]
    with pytest.raises(li.LinkedInError):
        li.verify_state(tampered)
    with pytest.raises(li.LinkedInError, match="expired"):
        li.verify_state(li.sign_state(USER, "member", now=time.time() - 700))


def test_authorize_url_uses_official_endpoint_and_scopes():
    url = li.authorize_url(USER, "member")
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "w_member_social" in url and "openid" in url
    with pytest.raises(li.LinkedInError, match="not enabled"):
        li.authorize_url(USER, "pages")  # pages stay dark until LinkedIn approval


def test_tokens_are_encrypted_at_rest():
    enc = token_crypto.encrypt("AQX-secret-token")
    assert "AQX" not in enc and token_crypto.decrypt(enc) == "AQX-secret-token"


def test_save_connection_stores_ciphertext_only():
    db = FakeDB()
    tokens = li.TokenSet(access_token="AQX-plain", expires_in=5184000, scope="w_member_social")
    studio.save_connection(db, USER, "member", tokens, [{"urn": "urn:li:person:z", "name": "Z"}], "person")
    row = db.t["linkedin_accounts"][0]
    assert "AQX-plain" not in json.dumps(row) and token_crypto.decrypt(row["access_token_enc"]) == "AQX-plain"
    assert "access_token_enc" not in studio.public_account(row)


# ------------------------------------------------------------- post payloads

def test_little_text_escaping_and_hashtags():
    out = li.to_little_text("Tips (2026) for @brands: *bold* [x] #growth #b2b_sales")
    assert r"\(2026\)" in out and r"\@brands" in out and r"\*bold\*" in out and r"\[x\]" in out
    assert "{hashtag|\\#|growth}" in out


def test_post_body_shapes():
    text = li.build_post_body("urn:li:person:a", "hi")
    assert text["lifecycleState"] == "PUBLISHED" and "content" not in text
    img = li.build_post_body("urn:li:person:a", "hi", media=[{"type": "image", "urn": "urn:li:image:1"}])
    assert img["content"]["media"]["id"] == "urn:li:image:1"
    multi = li.build_post_body("urn:li:person:a", "hi", media=[{"type": "image", "urn": f"urn:li:image:{i}"} for i in range(3)])
    assert len(multi["content"]["multiImage"]["images"]) == 3
    doc = li.build_post_body("urn:li:organization:9", "hi", media=[{"type": "document", "urn": "urn:li:document:7", "title": "Deck"}])
    assert doc["content"]["media"] == {"id": "urn:li:document:7", "title": "Deck"}


def test_create_post_reads_restli_id(monkeypatch):
    import httpx

    class R:
        status_code = 201
        headers = {"x-restli-id": "urn:li:share:7300"}

    seen = {}

    def fake(method, url, headers, timeout, **kw):
        seen.update(url=url, headers=headers, body=kw.get("json"))
        return R()

    monkeypatch.setattr(httpx, "request", fake)
    urn, url = li.create_post("tok", li.build_post_body("urn:li:person:a", "hello"))
    assert urn == "urn:li:share:7300" and url.endswith("/feed/update/urn:li:share:7300/")
    assert seen["url"] == "https://api.linkedin.com/rest/posts"
    assert seen["headers"]["LinkedIn-Version"] and seen["headers"]["X-Restli-Protocol-Version"] == "2.0.0"


# ------------------------------------------------------------- publishing

def test_publish_success_uploads_media_once_and_consumes_quota(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    acc = _account(db)
    db.storage.files[f"{USER}/a.png"] = b"\x89PNG"
    post = _post(db, acc, media=[{"type": "image", "storage_path": f"{USER}/a.png", "title": "", "alt": ""}])
    uploads = []
    monkeypatch.setattr(li, "upload_image", lambda tok, owner, data: uploads.append(owner) or "urn:li:image:9")
    monkeypatch.setattr(li, "create_post", lambda tok, body: ("urn:li:share:1", "https://x/1"))
    claimed = sched.publish_due(db)
    assert claimed == 1
    row = db.t["linkedin_posts"][0]
    assert row["status"] == "published" and row["linkedin_post_urn"] == "urn:li:share:1"
    assert row["media"][0]["urn"] == "urn:li:image:9" and uploads == ["urn:li:person:abc"]
    assert ("consume_linkedin_post_quota", {"p_user_id": USER, "p_limit": 60}) in db.rpcs
    assert sched.publish_due(db) == 0  # never published twice


def test_publish_revoked_token_needs_reconnect(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    acc = _account(db)
    _post(db, acc)

    def boom(tok, body):
        raise li.LinkedInError("auth", "401 revoked", 401)

    monkeypatch.setattr(li, "create_post", boom)
    sched.publish_due(db)
    assert db.t["linkedin_posts"][0]["status"] == "needs_reconnect"
    assert db.t["linkedin_accounts"][0]["status"] == "expired"


def test_publish_rate_limited_is_retried_later(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    _post(db, _account(db))

    def boom(tok, body):
        raise li.LinkedInError("rate_limited", "429", 429)

    monkeypatch.setattr(li, "create_post", boom)
    sched.publish_due(db)
    row = db.t["linkedin_posts"][0]
    assert row["status"] == "scheduled" and row["next_attempt_at"] > datetime.now(timezone.utc).isoformat()
    assert sched.publish_due(db) == 0  # waits for the backoff


def test_expired_member_token_is_not_used(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    acc = _account(db, expires_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    _post(db, acc)
    monkeypatch.setattr(li, "create_post", lambda *a: pytest.fail("must not call LinkedIn"))
    sched.publish_due(db)
    assert db.t["linkedin_posts"][0]["status"] == "needs_reconnect"


def test_quota_exhausted_and_downgraded_plan(monkeypatch):
    db = FakeDB()
    acc = _account(db)
    _post(db, acc)
    _plan(monkeypatch, used=60)
    sched.publish_due(db)
    assert db.t["linkedin_posts"][0]["status"] == "failed"
    assert "limit" in db.t["linkedin_posts"][0]["error"]
    _post(db, acc)
    _plan(monkeypatch, enabled=False, limit=0)
    sched.publish_due(db)
    assert "Pro or Agency" in db.t["linkedin_posts"][1]["error"]


def test_daily_safety_cap(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    acc = _account(db)
    now = datetime.now(timezone.utc).isoformat()
    for _ in range(get_settings().linkedin_daily_post_cap):
        _post(db, acc, status="published", published_at=now)
    _post(db, acc)
    monkeypatch.setattr(li, "create_post", lambda *a: pytest.fail("cap must hold"))
    sched.publish_due(db)
    last = db.t["linkedin_posts"][-1]
    assert last["status"] == "scheduled" and "Daily safety limit" in last["error"]


# --------------------------------------------------------------- autopilot

def test_upcoming_slots_respect_timezone():
    now = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)  # a Monday
    cfg = {"timezone": "Asia/Kolkata", "lookahead_days": 2, "slots": [{"dow": 0, "time": "09:30"}]}
    slots = sched.upcoming_slots(cfg, now)
    assert slots == [datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)]  # 09:30 IST


def test_autopilot_fills_only_free_slots_and_needs_consent_to_autopost(monkeypatch):
    _plan(monkeypatch)
    db = FakeDB()
    acc = _account(db)
    now = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)
    cfg = {"user_id": USER, "enabled": True, "account_id": acc["id"], "timezone": "UTC", "lookahead_days": 3,
           "slots": [{"dow": 0, "time": "10:00"}, {"dow": 1, "time": "10:00"}], "pillars": ["editing tips"],
           "auto_approve": False}
    _post(db, acc, status="scheduled", scheduled_at="2026-09-21T10:00:00+00:00")  # Monday taken
    monkeypatch.setattr(writer, "plan_posts", lambda pillars, count, **kw: [
        {"pillar": "editing tips", "topic": f"t{i}", "post": "A real post body " * 5} for i in range(count)])
    assert sched.plan_autopilot(db, cfg, now) == 1
    new = [p for p in db.t["linkedin_posts"] if p.get("source") == "autopilot"]
    assert len(new) == 1 and new[0]["status"] == "draft" and new[0]["scheduled_at"].startswith("2026-09-22T10:00")
    # auto_approve without consent timestamp still produces drafts
    cfg.update(auto_approve=True, slots=[{"dow": 2, "time": "10:00"}])
    sched.plan_autopilot(db, cfg, now)
    assert [p["status"] for p in db.t["linkedin_posts"] if p.get("source") == "autopilot"][-1] == "draft"
    cfg.update(consent_at="2026-09-20T00:00:00+00:00", slots=[{"dow": 3, "time": "10:00"}], lookahead_days=5)
    sched.plan_autopilot(db, cfg, now)
    assert [p["status"] for p in db.t["linkedin_posts"] if p.get("source") == "autopilot"][-1] == "scheduled"


# ---------------------------------------------------------------- API gate

def test_free_plan_is_blocked_and_autopilot_needs_consent(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.middleware.auth_middleware import get_current_user
    from app.routers import linkedin_studio as router

    db = FakeDB()
    monkeypatch.setattr(router, "get_supabase_admin", lambda: db)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER, "email": "", "name": "Jane"}
    try:
        c = TestClient(app)
        _plan(monkeypatch, plan_id="free", enabled=False, limit=0, remaining=0)
        r = c.post("/api/linkedin/ai/draft", json={"topic": "video editing tips"})
        assert r.status_code == 403 and "Pro and Agency" in r.json()["detail"]["message"]
        _plan(monkeypatch)
        acc = _account(db)
        r = c.put("/api/linkedin/autopilot", json={
            "enabled": True, "auto_approve": True, "account_id": acc["id"], "timezone": "UTC",
            "slots": [{"dow": 0, "time": "09:00"}], "pillars": ["tips"]})
        assert r.status_code == 400 and "consent" in r.json()["detail"]
        r = c.put("/api/linkedin/autopilot", json={
            "enabled": True, "auto_approve": True, "consent": True, "account_id": acc["id"],
            "timezone": "UTC", "slots": [{"dow": 0, "time": "09:00"}], "pillars": ["tips"]})
        assert r.status_code == 200 and r.json()["consent_at"]
        r = c.post("/api/linkedin/posts", json={"account_id": acc["id"], "commentary": "hi",
                                                "action": "schedule",
                                                "scheduled_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()})
        assert r.status_code == 400 and "2 minutes" in r.json()["detail"]
        r = c.post("/api/linkedin/posts", json={"account_id": acc["id"], "commentary": "hi", "action": "schedule",
                                                "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()})
        assert r.status_code == 201 and r.json()["status"] == "scheduled"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_media_validation(monkeypatch):
    db = FakeDB()
    with pytest.raises(ValueError, match="PDF"):
        studio.store_media(db, USER, b"not a pdf", "application/pdf", "x.pdf")
    with pytest.raises(ValueError, match="Only"):
        studio.store_media(db, USER, b"x", "application/zip", "x.zip")
    item = studio.store_media(db, USER, b"%PDF-1.4 data", "application/pdf", "Deck.pdf")
    assert item["type"] == "document" and item["storage_path"].startswith(USER + "/")
    with pytest.raises(ValueError, match="Invalid media"):
        studio.validate_media(USER, [{"type": "image", "storage_path": "someone-else/x.png"}])
    with pytest.raises(ValueError, match="OR one document"):
        studio.validate_media(USER, [{"type": "image", "storage_path": f"{USER}/a.png"},
                                     {"type": "document", "storage_path": f"{USER}/b.pdf"}])


# ------------------------------------------------------------------ writer

def test_writer_fails_closed_and_cleans_output(monkeypatch):
    class Choice:
        def __init__(self, content):
            self.message = type("M", (), {"content": content})

    def client_returning(content):
        class C:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        return type("R", (), {"choices": [Choice(content)]})
        return lambda: C

    monkeypatch.setattr(writer, "_client", client_returning("not json"))
    with pytest.raises(writer.WriterError):
        writer.draft_post("video editing")
    body = "**Bold hook** with “curly” quotes\n\n\n\nNext line " + "x" * 3200
    monkeypatch.setattr(writer, "_client", client_returning(json.dumps({"variants": [{"hook_style": "n", "post": body}]})))
    out = writer.draft_post("video editing", variants=1)[0]["post"]
    assert "**" not in out and '"curly"' in out and "\n\n\n" not in out and len(out) <= 3000


def test_carousel_pdf_pages():
    from app.services.carousel_pdf import render_carousel

    pdf = render_carousel([{"title": f"Slide {i}", "body": "Body text " * 10} for i in range(6)], author="Jane")
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 6
