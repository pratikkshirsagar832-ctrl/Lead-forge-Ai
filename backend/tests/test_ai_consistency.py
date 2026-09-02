"""Tests for the fail-closed AI classification consistency gate.

Prove that a model output claiming is_qualified=true cannot slip through a
self-contradiction / weak service / weak intent / non-sourcing / evidence-less
classification — regardless of the reported score.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_service import LeadClassification, enforce_consistency  # noqa: E402
from tests.conftest import make_classification  # noqa: E402


def _cls(**over):
    base = make_classification()
    base.update(over)
    return LeadClassification(**base)


def test_qualified_passes_all_consistency():
    cls = enforce_consistency(_cls())
    assert cls.is_qualified is True


def test_qualified_with_seller_flag_demoted():
    cls = enforce_consistency(_cls(seller_signal=True, is_selling_offering=True))
    assert cls.is_qualified is False
    assert "self-contradictory" in cls.rejection_reason


def test_qualified_with_job_seeker_demoted():
    cls = enforce_consistency(_cls(job_seeker_signal=True, is_job_seek=True))
    assert cls.is_qualified is False


def test_qualified_with_unrelated_service_demoted():
    cls = enforce_consistency(_cls(service_relevance="unrelated", service_match_score=20))
    assert cls.is_qualified is False
    assert "unrelated" in cls.rejection_reason


def test_qualified_with_research_intent_demoted():
    cls = enforce_consistency(_cls(intent_strength="research"))
    assert cls.is_qualified is False
    assert "weak_intent" in cls.rejection_reason


def test_qualified_when_not_sourcing_demoted():
    cls = enforce_consistency(_cls(is_buying_sourcing=False))
    assert cls.is_qualified is False
    assert "not_sourcing" in cls.rejection_reason


def test_qualified_with_weak_service_match_demoted():
    cls = enforce_consistency(_cls(service_match_score=30))
    assert cls.is_qualified is False
    assert "weak_service_match" in cls.rejection_reason


def test_qualified_without_evidence_demoted():
    cls = enforce_consistency(_cls(evidence="", reason=""))
    assert cls.is_qualified is False
    assert "insufficient_evidence" in cls.rejection_reason


def test_qualified_with_irrelevant_type_demoted():
    cls = enforce_consistency(_cls(lead_type="irrelevant"))
    assert cls.is_qualified is False
    assert "wrong_intent_type" in cls.rejection_reason


def test_unqualified_never_promoted():
    cls = enforce_consistency(_cls(is_qualified=False, rejection_reason="seller"))
    assert cls.is_qualified is False
    assert cls.rejection_reason == "seller"  # untouched
