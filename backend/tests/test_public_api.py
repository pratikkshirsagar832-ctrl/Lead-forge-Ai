"""Public API v1: keys, wallet hold/settle, per-lead billing, webhooks, top-ups.

Runs fully offline against an in-memory Supabase fake whose wallet RPCs
mirror supabase/migration_public_api_v20.sql exactly.
"""
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ----------------------------------------------------------------- fake DB

class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.kind, self.payload = "select", None
        self.filters, self.negated_in = [], []
        self._order, self._limit, self._range, self._count = None, None, None, None
        self._on_conflict = None

    # builders
    def select(self, _cols="*", count=None):
        self.kind, self._count = "select", count
        return self

    def insert(self, payload):
        self.kind, self.payload = "insert", payload
        return self

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self.kind, self.payload, self._on_conflict = "insert", payload, on_conflict
        return self

    def update(self, payload):
        self.kind, self.payload = "update", payload
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def eq(self, col, val):
        self.filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def is_(self, col, val):
        self.filters.append(lambda r, c=col: r.get(c) is None)
        return self

    def in_(self, col, vals):
        self.filters.append(lambda r, c=col, v=tuple(vals): r.get(c) in v)
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def in_(self, col, vals):
                outer.filters.append(lambda r, c=col, v=tuple(vals): r.get(c) not in v)
                return outer
        return _Not()

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.kind == "insert":
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            for it in items:
                row = {"id": str(uuid.uuid4()), "created_at": time.time(), **it}
                rows.append(row)
                out.append(row)
            return _Resp(out)
        match = [r for r in rows if all(f(r) for f in self.filters)]
        if self.kind == "update":
            for r in match:
                r.update(self.payload)
            return _Resp(match)
        if self.kind == "delete":
            self.db.tables[self.table] = [r for r in rows if r not in match]
            return _Resp(match)
        if self._order:
            col, desc = self._order
            match = sorted(match, key=lambda r: (r.get(col) is None, r.get(col) or 0), reverse=desc)
        total = len(match)
        if self._range:
            match = match[self._range[0]: self._range[1] + 1]
        if self._limit is not None:
            match = match[: self._limit]
        return _Resp([dict(r) for r in match], count=total if self._count else None)


class _Rpc:
    def __init__(self, db, name, params):
        self.db, self.name, self.params = db, name, params

    def execute(self):
        return _Resp(getattr(self.db, "rpc_" + self.name)(**self.params))


class FakeSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params):
        return _Rpc(self, name, params)

    # --- helpers
    def wallet(self, user_id):
        ws = self.tables.setdefault("api_wallets", [])
        for w in ws:
            if w["user_id"] == user_id:
                return w
        w = {"user_id": user_id, "balance_paise": 0, "held_paise": 0}
        ws.append(w)
        return w

    def ledger(self, **row):
        self.tables.setdefault("api_wallet_ledger", []).append({"created_at": time.time(), **row})

    def search(self, sid):
        return next((r for r in self.tables.get("searches", []) if r["id"] == sid), None)

    # --- RPCs mirroring migration_public_api_v20.sql
    def rpc_api_wallet_hold(self, p_user_id, p_search_id, p_amount):
        w = self.wallet(p_user_id)
        if w["balance_paise"] - w["held_paise"] < p_amount:
            return False
        w["held_paise"] += p_amount
        s = self.search(p_search_id)
        if s:
            s["wallet_hold_paise"] = p_amount
        self.ledger(user_id=p_user_id, kind="hold", amount_paise=p_amount,
                    balance_after=w["balance_paise"], search_id=p_search_id)
        return True

    def rpc_api_wallet_settle(self, p_search_id, p_delivered):
        s = self.search(p_search_id)
        if not s or s.get("billing") != "api" or s.get("wallet_settled_at"):
            return 0
        hold = int(s.get("wallet_hold_paise") or 0)
        charge = min(max(p_delivered, 0) * int(s.get("price_per_lead_paise") or 0), hold)
        w = self.wallet(s["user_id"])
        w["balance_paise"] = max(0, w["balance_paise"] - charge)
        w["held_paise"] = max(0, w["held_paise"] - hold)
        if charge:
            self.ledger(user_id=s["user_id"], kind="charge", amount_paise=-charge,
                        balance_after=w["balance_paise"], search_id=p_search_id)
        if hold - charge:
            self.ledger(user_id=s["user_id"], kind="release", amount_paise=hold - charge,
                        balance_after=w["balance_paise"], search_id=p_search_id)
        s["wallet_settled_at"] = "now"
        s["wallet_charged_paise"] = charge
        return charge

    def rpc_api_wallet_credit(self, p_user_id, p_amount, p_payment_id, p_kind="topup", p_note=None):
        w = self.wallet(p_user_id)
        if p_payment_id and any(r.get("payment_id") == p_payment_id
                                for r in self.tables.get("api_wallet_ledger", [])):
            return w["balance_paise"]
        w["balance_paise"] += p_amount
        self.ledger(user_id=p_user_id, kind=p_kind, amount_paise=p_amount,
                    balance_after=w["balance_paise"], payment_id=p_payment_id, note=p_note)
        return w["balance_paise"]


# ---------------------------------------------------------------- fixtures

USER = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture()
def env(monkeypatch):
    from app.main import app
    from app.middleware import api_key_auth
    from app.routers import developer, public_api
    from app.services import api_keys, api_public, hyperagent_service, pipeline

    db = FakeSupabase()
    api_keys._cache.clear()
    for mod in (api_key_auth, developer, public_api):
        monkeypatch.setattr(mod, "get_supabase_admin", lambda: db)
    monkeypatch.setattr(api_keys, "_touch_last_used", lambda *a, **k: None)
    monkeypatch.setattr(api_public, "deliver_search_webhook_async", lambda *a, **k: None)
    started = []
    monkeypatch.setattr(hyperagent_service, "run_hyperagent_pipeline",
                        lambda **kw: started.append(("linkedin", kw)))

    async def fake_maps(**kw):
        started.append(("google_maps", kw))

    monkeypatch.setattr(pipeline, "run_search_pipeline", fake_maps)
    key = api_keys.create_key(db, USER, "test")
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {key['api_key']}"})
    return {"db": db, "client": client, "key": key, "started": started}


def _fund(db, user, inr):
    db.rpc_api_wallet_credit(user, inr * 100, None, "adjust", "test")


# ------------------------------------------------------------------- keys

def test_raw_key_is_never_stored(env):
    row = env["db"].tables["api_keys"][0]
    assert env["key"]["api_key"].startswith("hc_live_")
    assert row["key_hash"] == hashlib.sha256(env["key"]["api_key"].encode()).hexdigest()
    assert env["key"]["api_key"] not in json.dumps(row, default=str)


def test_auth_errors(env):
    c = env["client"]
    assert c.get("/v1/wallet", headers={"Authorization": ""}).json()["error"]["code"] == "unauthorized"
    r = c.get("/v1/wallet", headers={"Authorization": "Bearer hc_live_" + "x" * 40})
    assert r.status_code == 401
    from app.services import api_keys

    api_keys.revoke_key(env["db"], USER, env["key"]["id"])
    assert c.get("/v1/wallet").status_code == 401  # revoked key stops immediately


def test_x_api_key_header_works(env):
    c = TestClient(env["client"].app)
    assert c.get("/v1/wallet", headers={"X-API-Key": env["key"]["api_key"]}).status_code == 200


def test_rate_limit(env, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_rate_read_per_min", 2)
    c = env["client"]
    codes = [c.get("/v1/wallet").status_code for _ in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


# ----------------------------------------------------------------- create

def test_insufficient_balance_is_402_and_leaves_nothing_behind(env):
    _fund(env["db"], USER, 100)  # < 3 × ₹50
    r = env["client"].post("/v1/searches", json={"source": "linkedin", "service": "video editing", "leads": 3})
    assert r.status_code == 402
    body = r.json()["error"]
    assert body["code"] == "insufficient_balance" and body["required_inr"] == 150.0
    assert env["db"].tables.get("searches", []) == []
    assert env["db"].wallet(USER)["held_paise"] == 0
    assert env["started"] == []


def test_create_holds_funds_and_starts_the_engine(env):
    _fund(env["db"], USER, 1000)
    r = env["client"].post("/v1/searches", json={
        "source": "linkedin", "service": "I am a CA", "mode": "agency", "leads": 5})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued" and body["requested"] == 5
    assert body["price_per_lead_inr"] == 50.0 and body["max_charge_inr"] == 250.0
    row = env["db"].search(body["id"])
    assert row["billing"] == "api" and row["reserved_leads"] == 5 and row["wallet_hold_paise"] == 25000
    assert env["db"].wallet(USER)["held_paise"] == 25000
    kind, kw = env["started"][0]
    assert kind == "linkedin" and kw["lead_type"] == "need_agency" and kw["leads_needed"] == 5
    assert body["wallet"]["available_inr"] == 750.0


def test_maps_needs_location_and_linkedin_max_10(env):
    _fund(env["db"], USER, 10000)
    c = env["client"]
    r = c.post("/v1/searches", json={"source": "google_maps", "service": "dentists", "leads": 5})
    assert r.status_code == 400 and "location" in r.json()["error"]["message"]
    r = c.post("/v1/searches", json={"source": "linkedin", "service": "seo", "leads": 11})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_request"
    r = c.post("/v1/searches", json={"source": "google_maps", "service": "dentists",
                                     "location": "Pune", "leads": 40})
    assert r.status_code == 202 and r.json()["max_charge_inr"] == 200.0  # 40 × ₹5
    assert env["started"][-1][0] == "google_maps"


def test_webhook_url_must_be_https_public(env):
    _fund(env["db"], USER, 1000)
    for bad in ("http://example.com/h", "https://localhost/h", "https://x.internal/h"):
        r = env["client"].post("/v1/searches", json={"source": "linkedin", "service": "seo",
                                                     "leads": 1, "webhook_url": bad})
        assert r.status_code == 400, bad


# ----------------------------------------------------------------- settle

def _create(env, leads=10):
    _fund(env["db"], USER, 1000)
    return env["client"].post("/v1/searches", json={"source": "linkedin", "service": "seo",
                                                    "leads": leads}).json()["id"]


def test_charged_only_for_delivered_leads(env):
    from app.services.usage import _settle_sync

    sid = _create(env, 10)  # hold ₹500
    assert _settle_sync(env["db"], sid, USER, 7) is True
    w = env["db"].wallet(USER)
    assert w["balance_paise"] == 100000 - 35000 and w["held_paise"] == 0  # ₹350 charged, ₹150 released
    # Idempotent: a second settle never charges again.
    _settle_sync(env["db"], sid, USER, 10)
    assert env["db"].wallet(USER)["balance_paise"] == 65000
    s = env["client"].get(f"/v1/searches/{sid}").json()
    assert s["charged_inr"] == 350.0


def test_failed_search_charges_nothing(env):
    from app.services.usage import _settle_sync

    sid = _create(env, 4)
    _settle_sync(env["db"], sid, USER, 0)
    w = env["db"].wallet(USER)
    assert w["balance_paise"] == 100000 and w["held_paise"] == 0


def test_plan_billed_search_still_uses_monthly_quota(env):
    from app.services import usage

    db = env["db"]
    db.tables.setdefault("searches", []).append({"id": "plan-search", "user_id": USER, "billing": "plan",
                                                 "quota_source": "linkedin", "reserved_leads": 3})
    assert usage._settle_api_wallet(db, "plan-search", 3) is False  # not handled by the wallet


def test_cancel_charges_delivered_so_far(env, monkeypatch):
    from app.services import hyperagent_service

    monkeypatch.setattr(hyperagent_service, "request_cancel", lambda sid: None)
    sid = _create(env, 5)
    env["db"].tables.setdefault("ha_leads", []).extend(
        [{"id": f"l{i}", "search_id": sid, "post_url": f"u{i}"} for i in range(2)])
    r = env["client"].post(f"/v1/searches/{sid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert env["db"].wallet(USER)["balance_paise"] == 100000 - 10000  # 2 × ₹50
    assert env["client"].post(f"/v1/searches/{sid}/cancel").status_code == 409


# ------------------------------------------------------------ read / scope

def test_leads_shape_and_owner_scoping(env):
    sid = _create(env, 3)
    db = env["db"]
    db.tables.setdefault("ha_leads", []).append({
        "id": "lead-1", "search_id": sid, "lead_type": "need_freelancer", "author_name": "Jane",
        "post_url": "https://www.linkedin.com/posts/jane-activity-1", "post_text": "Need a video editor",
        "posted_at": "2026-09-22T10:00:00+00:00", "overall_quality_score": 81.26})
    body = env["client"].get(f"/v1/searches/{sid}/leads").json()
    lead = body["data"][0]
    assert body["count"] == 1 and lead["type"] == "freelancer_needed" and lead["quality_score"] == 81.3
    assert set(lead) >= {"author_name", "post_url", "post_text", "posted_at"}
    # Another account's search is invisible.
    db.search(sid)["user_id"] = OTHER
    assert env["client"].get(f"/v1/searches/{sid}").status_code == 404
    assert env["client"].get("/v1/searches/not-a-uuid").status_code == 404


def test_list_searches(env):
    _create(env, 1)
    _create(env, 2)
    body = env["client"].get("/v1/searches?limit=1").json()
    assert body["total"] == 2 and len(body["data"]) == 1


# ---------------------------------------------------------------- webhooks

def test_webhook_signature_roundtrip():
    from app.services.api_public import sign_payload, verify_signature

    body = b'{"event":"search.completed"}'
    ts = int(time.time())
    header = sign_payload("whsec_test", ts, body)
    assert verify_signature("whsec_test", header, body)
    assert not verify_signature("whsec_other", header, body)
    assert not verify_signature("whsec_test", header, body + b" ")
    expected = hmac.new(b"whsec_test", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert header == f"t={ts},v1={expected}"


def test_webhook_delivery_retries_and_signs(monkeypatch):
    from app.services import api_public

    db = FakeSupabase()
    db.tables["api_keys"] = [{"id": "k1", "webhook_secret": "whsec_x"}]
    db.tables["searches"] = [{"id": "s1", "user_id": USER, "billing": "api", "api_key_id": "k1",
                              "status": "completed", "source": "linkedin", "niche": "seo",
                              "max_results": 1, "price_per_lead_paise": 5000,
                              "webhook_url": "https://hooks.example.com/h"}]
    db.tables["ha_leads"] = [{"id": "l1", "search_id": "s1", "post_url": "u"}]
    monkeypatch.setattr(api_public, "_resolves_public", lambda host: True)
    monkeypatch.setattr(api_public.time, "sleep", lambda s: None)
    sent = []

    class R:
        def __init__(self, code):
            self.status_code = code

    import httpx

    def fake_post(url, content, timeout, follow_redirects, headers):
        sent.append(headers)
        return R(500 if len(sent) < 2 else 200)

    monkeypatch.setattr(httpx, "post", fake_post)
    api_public.deliver_search_webhook(db, "s1")
    assert len(sent) == 2 and db.search("s1")["webhook_status"] == "delivered"
    assert sent[-1]["X-Hyperclients-Event"] == "search.completed"
    assert sent[-1]["X-Hyperclients-Signature"].startswith("t=")


def test_webhook_blocks_private_targets(monkeypatch):
    from app.services import api_public

    assert api_public._resolves_public("127.0.0.1") is False
    assert api_public._resolves_public("10.0.0.5") is False


# ----------------------------------------------------------------- top-ups

class _FakeRazorpay:
    def __init__(self, status="captured", amount=1000000):
        self.payment = self
        self._status, self._amount = status, amount

    def fetch(self, payment_id):
        return {"id": payment_id, "status": self._status, "amount": self._amount, "order_id": "order_1"}


def test_topup_credits_once_and_validates(env):
    from app.routers.developer import WalletPaymentError, credit_wallet_from_payment

    db = env["db"]
    db.tables["payment_orders"] = [{"order_id": "order_1", "user_id": USER, "plan_id": "api_wallet",
                                    "amount": 1000000}]
    assert credit_wallet_from_payment(db, _FakeRazorpay(), "order_1", "pay_1", USER) == 1000000
    # Replayed webhook / double verify: never double-credits.
    assert credit_wallet_from_payment(db, _FakeRazorpay(), "order_1", "pay_1") == 1000000
    with pytest.raises(WalletPaymentError):
        credit_wallet_from_payment(db, _FakeRazorpay(amount=500), "order_1", "pay_2", USER)
    with pytest.raises(WalletPaymentError):
        credit_wallet_from_payment(db, _FakeRazorpay(status="failed"), "order_1", "pay_3", USER)
    with pytest.raises(WalletPaymentError):
        credit_wallet_from_payment(db, _FakeRazorpay(), "order_1", "pay_4", OTHER)


def test_topup_amount_limits(env, monkeypatch):
    from app.main import app
    from app.middleware.auth_middleware import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": USER, "email": "", "name": ""}
    try:
        c = TestClient(app)
        for amount in (9999, 100001):
            r = c.post("/api/developer/wallet/topup", json={"amount_inr": amount})
            assert r.status_code == 400 and "10,000" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
