"""Classifier regression set built from docs/linkedin-pipeline-audit.md §9.

Two concerns, mirrored as two lists:

1. REJECT_REGRESSIONS — employee job-ads / recruiter funnels that the audit
   found being wrongly accepted as need_freelancer. The classifier MUST NOT
   accept these as need_freelancer (lead_type must be "irrelevant").
2. ACCEPT_REGRESSIONS — genuine buyer asks that must never regress (must be
   classified need_freelancer and is_qualified=true).

Static test: guards that the system prompt still carries the project-vs-
employment decision signals (so a future prompt edit can't silently delete
them without a test failing).
Live test: runs the real classifier against the full set; skipped unless
RUN_CLASSIFIER_LIVE=1 (costs DeepSeek calls).
"""
import json
import os
from types import SimpleNamespace

import pytest

from classifier import GptClassifier, _SYSTEM_PROMPT

REJECT_REGRESSIONS = [
    {
        "label": "uiux_2yr_experience_employee",
        "text": ("We are looking for a talented UI/UX Product Designer with 2+ years of "
                 "hands-on experience designing modern, complex web applications. Join our team."),
        "why": "audit §9 #2 — employee job ad phrasing (experience threshold + join our team)",
    },
    {
        "label": "5yr_hands_on_application_funnel",
        "text": ("We are hiring a UI/UX designer with 5+ years of hands-on experience to design "
                 "complex web applications. Fill out the form below to apply."),
        "why": "prompt few-shot #6 — experience threshold + application funnel",
    },
    {
        "label": "recruiter_funnel_video_editor",
        "text": ("I'm hiring a video editor to help coaches get high-paying clients through "
                 "LinkedIn content. Fill out the form below — we'll review applications."),
        "why": "audit §9 #6 — recruiter/application funnel, not a freelancer ask",
    },
]

ACCEPT_REGRESSIONS = [
    {
        "label": "logo_for_business",
        "text": ("Need a logo for my business. SID Sports Center, sells football jerseys and "
                 "soccer boots. Sportswear, social media."),
        "service": "logo design",
        "why": "audit §9 #1 — genuine small-owner buy",
    },
    {
        "label": "ai_video_editor_dtc",
        "text": ("Looking for an AI video editor who knows how to create and edit videos for "
                 "DTC brands. Claymations. AI UGC."),
        "why": "audit §9 #3 — genuine buyer ask",
    },
    {
        "label": "bounded_project_deadline",
        "text": ("Need 20 short videos cut for our campaign before the 15th — freelance, project "
                 "basis, budget ready."),
        "why": "prompt few-shot #7 — bounded deliverable + deadline + freelance framing",
    },
]

# Static guard: the Tier-2 decision guidance must remain in the prompt.
_PROMPT_GUARDS = (
    "years-of-experience",
    "application funnel",
    "fill out the form",
    "PROJECT-leaning",
    "does NOT override",
    "5+ years of hands-on experience",
    "before the 15th",
)


def test_prompt_contains_project_vs_employment_decision_signals():
    for guard in _PROMPT_GUARDS:
        assert guard in _SYSTEM_PROMPT, f"prompt lost Tier-2 signal: {guard!r}"


def _fake_post(text: str):
    return SimpleNamespace(
        post_url=f"https://www.linkedin.com/posts/regression-{abs(hash(text)) % 10**9}",
        author_name="Regression Case",
        author_profile_url="https://www.linkedin.com/in/regression-case",
        posted_at=None,
        text=text,
    )


def run_classifier_regression() -> list[dict]:
    """Run the live classifier over the full regression set. Returns verdicts."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return []
    clf = GptClassifier(
        key,
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        provider="deepseek",
        json_mode="json_object",
    )
    out = []
    for case in REJECT_REGRESSIONS + ACCEPT_REGRESSIONS:
        verdict = clf._classify_one(
            _fake_post(case["text"]),
            service=case.get("service", "video editing"),
            requested_type="need_freelancer",
            country="",
        )
        out.append({
            "label": case["label"],
            "expected_reject": case in REJECT_REGRESSIONS,
            "lead_type": verdict.lead_type if verdict else None,
            "is_qualified": verdict.is_qualified if verdict else None,
            "reason": verdict.reason if verdict else "no verdict",
            "why": case["why"],
        })
    return out


@pytest.mark.skipif(
    os.environ.get("RUN_CLASSIFIER_LIVE") != "1",
    reason="live classifier run costs DeepSeek calls; set RUN_CLASSIFIER_LIVE=1",
)
def test_classifier_live_regression():
    verdicts = run_classifier_regression()
    assert verdicts, "no DEEPSEEK_API_KEY — cannot run live regression"
    failures = []
    for v in verdicts:
        if v["expected_reject"]:
            if v["lead_type"] == "need_freelancer" or v["is_qualified"]:
                failures.append(v)
        else:
            if v["lead_type"] != "need_freelancer" or not v["is_qualified"]:
                failures.append(v)
    assert not failures, "regression failures:\n" + json.dumps(verdicts, indent=2)
