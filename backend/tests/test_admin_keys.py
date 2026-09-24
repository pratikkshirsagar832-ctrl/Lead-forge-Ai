"""Admin key endpoints: token-protected, never return raw keys."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import admin_keys
from app.services import socialcrawl_keys


def _client(monkeypatch, token="secret-token"):
    monkeypatch.setattr(admin_keys, "get_settings", lambda: type("S", (), {"admin_api_token": token})())
    monkeypatch.setattr(admin_keys, "get_supabase_admin", lambda: object())
    app = FastAPI()
    app.include_router(admin_keys.router)
    return TestClient(app)


def test_requires_token(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/api/internal/admin/socialcrawl-keys").status_code == 401
    assert c.get("/api/internal/admin/socialcrawl-keys", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert _client(monkeypatch, token="").get("/api/internal/admin/socialcrawl-keys",
                                              headers={"X-Admin-Token": ""}).status_code == 503


def test_list_add_and_errors(monkeypatch):
    c = _client(monkeypatch)
    h = {"X-Admin-Token": "secret-token"}
    monkeypatch.setattr(socialcrawl_keys, "list_keys", lambda sb: {"keys": [{"id": "1", "key_hint": "abcd"}], "totals": {}, "in_use": "1"})
    r = c.get("/api/internal/admin/socialcrawl-keys", headers=h)
    assert r.status_code == 200 and r.json()["keys"][0]["key_hint"] == "abcd"

    def bad_add(sb, key, label):
        raise ValueError("SocialCrawl rejected this key. Check it and try again.")
    monkeypatch.setattr(socialcrawl_keys, "add_key", bad_add)
    r = c.post("/api/internal/admin/socialcrawl-keys", headers=h, json={"key": "sc_1234567890abc", "label": ""})
    assert r.status_code == 400 and "rejected" in r.json()["detail"]

    monkeypatch.setattr(socialcrawl_keys, "remove_key", lambda sb, key_id: False)
    assert c.delete("/api/internal/admin/socialcrawl-keys/nope", headers=h).status_code == 404


def test_public_row_never_contains_key():
    row = {"id": "1", "key_enc": "gAAAA-secret", "key_hash": "abc", "key_hint": "wxyz", "status": "active"}
    out = socialcrawl_keys.public_row(row)
    assert "key_enc" not in out and "key_hash" not in out and out["key_hint"] == "wxyz"


def test_env_keys_merge_and_dedupe(monkeypatch):
    s = type("S", (), {"socialcrawl_api_key": "sc_one", "socialcrawl_api_keys": "sc_two, sc_one,\nsc_three"})()
    monkeypatch.setattr(socialcrawl_keys, "get_settings", lambda: s)
    assert socialcrawl_keys.env_keys() == ["sc_one", "sc_two", "sc_three"]
