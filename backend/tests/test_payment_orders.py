"""Regression tests for the payment-order ledger.

`user_subscriptions.razorpay_order_id` is a single slot. Starting a second
checkout used to overwrite the first order id, after which a payment for the
abandoned order could neither be verified nor webhooked — the customer was
charged and got no plan, and `.limit(1)` with no ordering could activate an
arbitrary subscription row. Orders now resolve through `payment_orders`
(migration v14) with the legacy slot as a fallback.
"""
import asyncio
import hashlib
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.routers import subscriptions as subs  # noqa: E402

SECRET = "test_secret"


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, client, table, kind="select", payload=None):
        self.client = client
        self.table = table
        self.kind = kind
        self.payload = payload
        self.filters: list[tuple] = []
        self._order = None
        self._limit = None

    def select(self, cols="*"):
        self.kind = "select"
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def neq(self, col, val):
        self.filters.append((col, ("__neq__", val)))
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, payload):
        self.kind = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.kind = "update"
        self.payload = payload
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def _matches(self, row) -> bool:
        for col, val in self.filters:
            if isinstance(val, tuple) and val[0] == "__neq__":
                if row.get(col) == val[1]:
                    return False
            elif row.get(col) != val:
                return False
        return True

    def execute(self):
        if self.table in self.client.missing_tables:
            raise RuntimeError(f'relation "{self.table}" does not exist')
        rows = self.client.rows.setdefault(self.table, [])
        if self.kind == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            for row in payload:
                rows.append(dict(row))
            return _Resp([dict(r) for r in payload])
        if self.kind == "update":
            changed = []
            for row in rows:
                if self._matches(row):
                    row.update(dict(self.payload))
                    changed.append(row)
            return _Resp(changed)
        if self.kind == "delete":
            keep = [r for r in rows if not self._matches(r)]
            removed = [r for r in rows if self._matches(r)]
            self.client.rows[self.table] = keep
            return _Resp(removed)
        found = [r for r in rows if self._matches(r)]
        if self._order:
            col, desc = self._order
            found.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit:
            found = found[: self._limit]
        return _Resp(found, count=len(found))


class FakeSupabase:
    def __init__(self, missing_tables=()):
        self.rows: dict[str, list[dict]] = {}
        self.missing_tables = set(missing_tables)

    def table(self, name):
        return _Query(self, name)


class _FakeRazorpay:
    def __init__(self, notes, pay_amount=4900, pay_status="captured"):
        self._notes = notes
        self._pay_amount = pay_amount
        self._pay_status = pay_status

    def order(self):
        return self

    def payment(self):
        return self

    def fetch(self, _id):
        return {"notes": self._notes, "id": _id}

    class _pay:
        pass


class FakeRazorpayClient:
    """Stands in for razorpay.Client: order.fetch / payment.fetch."""

    def __init__(self, notes, pay_amount=4900, pay_status="captured"):
        self.notes = notes
        self.pay_amount = pay_amount
        self.pay_status = pay_status

    def __getattr__(self, name):
        client = self
        if name == "order":
            return _RazorpayNamespace(client, "order")
        if name == "payment":
            return _RazorpayNamespace(client, "payment")
        raise AttributeError(name)


class _RazorpayNamespace:
    def __init__(self, client, kind):
        self.client = client
        self.kind = kind

    def fetch(self, _id):
        if self.kind == "order":
            return {"id": _id, "notes": self.client.notes}
        return {"id": _id, "status": self.client.pay_status, "amount": self.client.pay_amount}


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch):
    # The "table exists" probe is cached per process; tests must not inherit it.
    monkeypatch.setattr(subs, "_PAYMENT_ORDERS_SUPPORTED", None, raising=False)


def _settings():
    class _S:
        razorpay_key_id = "key"
        razorpay_key_secret = SECRET
        razorpay_solo_amount_inr = 1900
        razorpay_pro_amount_inr = 4900
        razorpay_agency_amount_inr = 29900

    return _S()


def test_ledger_resolves_an_order_after_the_slot_was_overwritten():
    """The orphaned-order case: no subscription row matches the order id."""
    client = FakeSupabase()
    client.rows["payment_orders"] = [{
        "order_id": "order-old", "user_id": "user-1", "plan_id": "pro",
        "amount": 4900, "status": "pending",
    }]
    client.rows["user_subscriptions"] = [{
        "id": "sub-1", "user_id": "user-1", "plan_id": "free",
        "razorpay_order_id": "order-new",  # overwritten by a later checkout
        "status": "trial", "created_at": "2026-09-01T00:00:00+00:00",
    }]

    resolved = subs._resolve_order_owner(client, "order-old")

    assert resolved["user_id"] == "user-1"
    assert resolved["source"] == "payment_orders"


def test_falls_back_to_the_subscription_slot_when_ledger_is_missing():
    client = FakeSupabase(missing_tables={"payment_orders"})
    client.rows["user_subscriptions"] = [{
        "id": "sub-9", "user_id": "user-2", "plan_id": "free",
        "razorpay_order_id": "order-live", "status": "pending",
        "created_at": "2026-09-02T00:00:00+00:00",
    }]

    resolved = subs._resolve_order_owner(client, "order-live")

    assert resolved == {
        "user_id": "user-2", "plan_id": "free",
        "subscription_id": "sub-9", "source": "user_subscriptions",
    }


def test_unknown_order_resolves_to_none():
    client = FakeSupabase(missing_tables={"payment_orders"})
    client.rows["user_subscriptions"] = []

    assert subs._resolve_order_owner(client, "nope") is None


def test_target_row_is_deterministic_newest_non_cancelled():
    client = FakeSupabase()
    client.rows["user_subscriptions"] = [
        {"id": "old", "user_id": "user-1", "status": "active", "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "newest-cancelled", "user_id": "user-1", "status": "cancelled", "created_at": "2026-09-10T00:00:00+00:00"},
        {"id": "middle", "user_id": "user-1", "status": "trial", "created_at": "2026-09-05T00:00:00+00:00"},
    ]

    assert subs._target_subscription_row(client, "user-1")["id"] == "middle"


def test_target_row_falls_back_to_newest_when_all_cancelled():
    client = FakeSupabase()
    client.rows["user_subscriptions"] = [
        {"id": "a", "user_id": "user-1", "status": "cancelled", "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "b", "user_id": "user-1", "status": "cancelled", "created_at": "2026-09-01T00:00:00+00:00"},
    ]

    assert subs._target_subscription_row(client, "user-1")["id"] == "b"


def _signature(order_id: str, payment_id: str) -> str:
    return hmac.new(
        SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()


def _wire(monkeypatch, client, notes, pay_amount=4900, pay_status="captured"):
    monkeypatch.setattr(subs, "get_settings", _settings)
    monkeypatch.setattr(subs, "get_supabase_admin", lambda: client)
    monkeypatch.setattr(
        subs, "_get_razorpay_client",
        lambda settings: FakeRazorpayClient(notes, pay_amount, pay_status),
    )


def test_verify_activates_the_plan_for_an_orphaned_order(monkeypatch):
    """A paid order that is no longer in the single slot must still activate."""
    client = FakeSupabase()
    client.rows["payment_orders"] = [{
        "order_id": "order-old", "user_id": "user-1", "plan_id": "pro",
        "amount": 4900, "status": "pending",
    }]
    client.rows["user_subscriptions"] = [{
        "id": "sub-1", "user_id": "user-1", "plan_id": "free",
        "razorpay_order_id": "order-new", "status": "trial",
        "created_at": "2026-09-01T00:00:00+00:00",
    }]
    client.rows["plans"] = [{"id": "pro", "name": "Pro", "billing_cycle_days": 30}]
    _wire(monkeypatch, client, {"user_id": "user-1", "plan_id": "pro"})

    result = asyncio.run(subs.verify_payment(
        {
            "razorpay_order_id": "order-old",
            "razorpay_payment_id": "pay-1",
            "razorpay_signature": _signature("order-old", "pay-1"),
        },
        current_user={"id": "user-1"},
    ))

    assert result["status"] == "success"
    assert result["plan_id"] == "pro"
    row = client.rows["user_subscriptions"][0]
    assert row["plan_id"] == "pro"
    assert row["status"] == "active"
    assert row["razorpay_payment_id"] == "pay-1"
    assert client.rows["payment_orders"][0]["status"] == "paid"


def test_verify_rejects_another_users_order(monkeypatch):
    from fastapi import HTTPException

    client = FakeSupabase()
    client.rows["payment_orders"] = [{
        "order_id": "order-x", "user_id": "someone-else", "plan_id": "pro",
        "amount": 4900, "status": "pending",
    }]
    _wire(monkeypatch, client, {"user_id": "user-1", "plan_id": "pro"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(subs.verify_payment(
            {
                "razorpay_order_id": "order-x",
                "razorpay_payment_id": "pay-2",
                "razorpay_signature": _signature("order-x", "pay-2"),
            },
            current_user={"id": "user-1"},
        ))

    assert exc.value.status_code == 400
    assert client.rows["payment_orders"][0]["status"] == "pending"


class _ExplodingRazorpay:
    """order.fetch blows up — stands in for a Razorpay/network failure."""

    def __getattr__(self, name):
        raise RuntimeError("razorpay unavailable")


class FakeRequest:
    def __init__(self, body: bytes, signature: str):
        self._body = body
        self.headers = {"X-Razorpay-Signature": signature}

    async def body(self) -> bytes:
        return self._body


def _webhook_event(event_id: str = "evt_1"):
    import json

    body = json.dumps({
        "event": "payment.captured",
        "id": event_id,
        "payload": {"payment": {"entity": {
            "order_id": "order-1", "id": "pay-1", "status": "captured",
        }}},
    }).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, FakeRequest(body, signature)


def test_webhook_answers_5xx_and_releases_claim_on_failure(monkeypatch):
    """A transient failure must be retryable, not silently swallowed as 200."""
    body, request = _webhook_event()
    client = FakeSupabase()
    client.rows["payment_orders"] = [{
        "order_id": "order-1", "user_id": "user-1", "plan_id": "pro",
        "amount": 4900, "status": "pending",
    }]
    monkeypatch.setattr(subs, "get_settings", _settings)
    monkeypatch.setattr(subs, "get_supabase_admin", lambda: client)
    monkeypatch.setattr(subs, "_get_razorpay_client", lambda settings: _ExplodingRazorpay())

    response = asyncio.run(subs.razorpay_webhook(request))

    assert response.status_code == 500
    # The idempotency claim is released so Razorpay's retry can process it.
    assert client.rows.get("payment_events", []) == []
    assert client.rows["payment_orders"][0]["status"] == "pending"


def test_webhook_ignores_a_replayed_event(monkeypatch):
    body, request = _webhook_event(event_id="evt-dupe")
    client = FakeSupabase()
    client.rows["payment_events"] = [{"id": "row-1", "event_id": "evt-dupe"}]
    monkeypatch.setattr(subs, "get_settings", _settings)
    monkeypatch.setattr(subs, "get_supabase_admin", lambda: client)

    response = asyncio.run(subs.razorpay_webhook(request))

    assert response == {"status": "ok", "duplicate": True}


def test_webhook_rejects_a_bad_signature(monkeypatch):
    from fastapi import HTTPException

    body, request = _webhook_event()
    request.headers = {"X-Razorpay-Signature": "deadbeef"}
    monkeypatch.setattr(subs, "get_settings", _settings)

    try:
        asyncio.run(subs.razorpay_webhook(request))
    except HTTPException as exc:
        assert exc.status_code == 400
    else:  # pragma: no cover
        raise AssertionError("expected HTTPException(400)")


def test_verify_rejects_a_wrong_amount(monkeypatch):
    from fastapi import HTTPException

    client = FakeSupabase()
    client.rows["payment_orders"] = [{
        "order_id": "order-y", "user_id": "user-1", "plan_id": "pro",
        "amount": 4900, "status": "pending",
    }]
    client.rows["plans"] = [{"id": "pro", "name": "Pro", "billing_cycle_days": 30}]
    _wire(monkeypatch, client, {"user_id": "user-1", "plan_id": "pro"},
          pay_amount=100)  # underpaid

    with pytest.raises(HTTPException) as exc:
        asyncio.run(subs.verify_payment(
            {
                "razorpay_order_id": "order-y",
                "razorpay_payment_id": "pay-3",
                "razorpay_signature": _signature("order-y", "pay-3"),
            },
            current_user={"id": "user-1"},
        ))

    assert exc.value.status_code == 400
    assert "amount" in str(exc.value.detail).lower()
