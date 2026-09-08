"""Regression tests for the content-direction gate shared by the Hyperagent
engine (pre-LLM `content_filter`) and the save-time store wrapper.

Invariant guarded here: a search that claims N leads really saves N, because
the engine and the store use the SAME predicate — nothing accepted by the
engine can later be discarded by the store, and nothing the store would
discard ever spends a DeepSeek call.
"""
import pytest

from app.services.hyperagent_service import _ForceTypeStore, _content_matches_requested_type


class _FakeInner:
    def __init__(self):
        self.seen: list[dict] = []

    def insert_leads_many(self, rows) -> int:
        self.seen.extend(dict(r) for r in rows)
        return len(rows)


# ---- predicate: need_freelancer direction -----------------------------------

@pytest.mark.parametrize("text", [
    "Looking for a freelance video editor for our campaign. Budget is ready.",
    "We are hiring a freelance video editor for a 6-week project, not full-time.",
    "Anyone know a good video editor? We need 20 shorts cut this month.",
    "Does anyone have recommendations for a video editor for wedding films?",
])
def test_need_freelancer_keeps_genuine_freelance_asks(text: str):
    assert _content_matches_requested_type(text, "need_freelancer") is True


@pytest.mark.parametrize("text", [
    "We are hiring a full-time video editor. Salary range 60-70k, apply now at our careers page.",
    "Open position: in-house video editor, benefits package included.",
])
def test_need_freelancer_drops_employee_job_ads_without_freelance_wording(text: str):
    assert _content_matches_requested_type(text, "need_freelancer") is False


@pytest.mark.parametrize("text", [
    "Our agency is recruiting freelancers for client projects — white label welcome.",
    "Looking for freelancers to work with our agency on client work. Paid per project.",
])
def test_need_freelancer_drops_agency_sourcing(text: str):
    assert _content_matches_requested_type(text, "need_freelancer") is False


# ---- predicate: our_agency direction ----------------------------------------

@pytest.mark.parametrize("text", [
    "We're a video production agency looking for freelancers for overflow client projects.",
    "Our agency needs extra video editing help this quarter. White-label collaboration welcome.",
    "We need editors and writers for our channel — looking for a team to handle it.",
])
def test_our_agency_keeps_agency_and_team_sourcing(text: str):
    assert _content_matches_requested_type(text, "our_agency") is True


@pytest.mark.parametrize("text", [
    "I'm a freelance video editor available for projects, DM me.",
    "Open to work — seeking new opportunities as a video editor.",
])
def test_our_agency_drops_pure_individual_freelance_asks(text: str):
    assert _content_matches_requested_type(text, "our_agency") is False


def test_empty_text_never_cheap_dropped():
    assert _content_matches_requested_type("", "need_freelancer") is True
    assert _content_matches_requested_type(None, "our_agency") is True
    assert _content_matches_requested_type("   ", "need_freelancer") is True


# ---- store wrapper applies the same predicate -------------------------------

def test_force_type_store_drops_exactly_what_predicate_rejects():
    inner = _FakeInner()
    store = _ForceTypeStore(inner, "need_freelancer")

    rows = [
        {"post_text": "Looking for a freelance video editor. Budget ready.", "lead_type": "need_freelancer"},
        {"post_text": "We are hiring a full-time video editor, salary plus benefits.", "lead_type": "need_freelancer"},
        {"post_text": "Our agency needs freelancers for client projects.", "lead_type": "our_agency"},
        {"post_text": "Anyone know a video editor? Need a promo cut this week.", "lead_type": "need_freelancer"},
    ]
    inserted = store.insert_leads_many(rows)

    assert inserted == 2                       # exactly the two genuine asks
    assert len(inner.seen) == 2
    # Surviving rows are stamped with the requested wire type.
    assert all(r["lead_type"] == "need_freelancer" for r in inner.seen)
    # Everything the store keeps passes the predicate the engine uses pre-LLM.
    for r in inner.seen:
        assert _content_matches_requested_type(r["post_text"], "need_freelancer") is True


def test_force_type_store_keeps_all_rows_that_pass_predicate():
    inner = _FakeInner()
    store = _ForceTypeStore(inner, "our_agency")
    rows = [
        {"post_text": "Our agency is looking for extra editors for client projects.", "lead_type": "our_agency"},
        {"post_text": "We need a team to handle our channel's daily edits.", "lead_type": "our_agency"},
    ]
    assert store.insert_leads_many(rows) == 2
    assert len(inner.seen) == 2
