"""Post liveness: deleted / filled LinkedIn posts never reach the user (offline)."""
import pytest

import liveness
from discovery.base import activity_urn
from liveness import PostCheck, check_post, is_filled

LIVE_HTML = ('<html><body><div class="feed-shared-update">'
             '<p class="attributed-text-segment-list__content">Looking for a freelance video editor '
             'for 12 reels this month, paid per reel - DM me!</p></div></body></html>')
URL = "https://www.linkedin.com/posts/jane-doe_need-an-editor-activity-7507437522902466560-JqXy"


class Resp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(liveness.time, "sleep", lambda s: None)


def _serve(monkeypatch, responder):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return responder(url)

    monkeypatch.setattr(liveness, "_get", fake_get)
    return calls


def test_activity_urn_kinds():
    assert activity_urn(URL) == ("activity", "7507437522902466560")
    assert activity_urn("https://www.linkedin.com/posts/x_y-ugcPost-7300000000000000000-aa") == \
        ("ugcPost", "7300000000000000000")
    assert activity_urn("https://www.linkedin.com/feed/update/urn:li:share:7100000000000000000/") == \
        ("share", "7100000000000000000")
    assert activity_urn("https://www.linkedin.com/posts/no-id-here") is None


def test_live_post_is_alive_with_full_text(monkeypatch):
    calls = _serve(monkeypatch, lambda u: Resp(200, LIVE_HTML))
    res = check_post(URL)
    assert res.status == "alive"
    assert "12 reels this month" in (res.text or "")
    assert calls == ["https://www.linkedin.com/embed/feed/update/urn:li:activity:7507437522902466560"]


def test_deleted_post_is_dead(monkeypatch):
    _serve(monkeypatch, lambda u: Resp(404, "<title>LinkedIn</title> Page not found"))
    assert check_post(URL) == PostCheck("dead")


def test_ugcpost_url_tries_its_own_urn_then_activity(monkeypatch):
    calls = _serve(monkeypatch, lambda u: Resp(200, LIVE_HTML) if ":activity:" in u else Resp(404))
    res = check_post("https://www.linkedin.com/posts/x_y-ugcPost-7300000000000000000-aa")
    assert res.status == "alive"
    assert calls[0].endswith("urn:li:ugcPost:7300000000000000000")


@pytest.mark.parametrize("status", [429, 999, 500, 503])
def test_throttle_is_unknown_after_one_retry(monkeypatch, status):
    calls = _serve(monkeypatch, lambda u: Resp(status, "blocked"))
    assert check_post(URL).status == "unknown"  # fail-open: lead is kept
    assert len(calls) == 2  # one retry


def test_network_error_and_missing_id_are_unknown(monkeypatch):
    def boom(url, timeout):
        raise OSError("reset")

    monkeypatch.setattr(liveness, "_get", boom)
    assert check_post(URL).status == "unknown"
    assert check_post("https://www.linkedin.com/posts/no-id").status == "unknown"


@pytest.mark.parametrize("text", [
    "UPDATE: CONTRACT NOW AWARDED 🚀 Looking for a Web Designer",
    "Update - filled! Thanks everyone for the recommendations",
    "The position has been filled, thank you all",
    "We are no longer looking, found someone great",
    "Thanks everyone, we hired a fantastic editor",
    "Role is now closed.",
])
def test_filled_asks_are_detected(text):
    assert is_filled(text)


@pytest.mark.parametrize("text", [
    "Looking for a freelance video editor for our launch, budget ready",
    "We need someone to fill the gap in our design team for 3 months",
    "Anyone know a good lawyer? The contract needs review this week",
    "",
])
def test_normal_asks_are_not_filled(text):
    assert not is_filled(text)
