"""Tests for Apify key-rotation blacklist/cooldown logic.

Prove that a recoverable 403 (monthly usage hard limit exceeded) is NOT
permanently blacklisted, so a working key that momentarily hits its limit is
retried later instead of being removed from rotation forever.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.apify_service import (  # noqa: E402
    _is_perm_feature_disabled,
    _build_negative_query,
    add_negative_signal_queries,
)


def test_monthly_usage_hard_limit_is_recoverable():
    # This exact 403 message trips up both keys in production. It is temporary.
    assert _is_perm_feature_disabled("platform-feature-disabled: Monthly usage hard limit exceeded") is False


def test_billing_credit_limit_is_recoverable():
    assert _is_perm_feature_disabled("platform-feature-disabled: not enough credits") is False


def test_paid_actor_blocked_is_recoverable():
    # A free-account paid-actor restriction can be resolved by funding the account.
    assert _is_perm_feature_disabled("platform-feature-disabled: paid actor not allowed on free plan") is False


def test_generic_feature_disabled_not_permanent():
    assert _is_perm_feature_disabled("platform-feature-disabled") is False


def test_non_feature_error_not_permanent():
    assert _is_perm_feature_disabled("some other error") is False


# ── Boolean NOT discovery queries (research-backed, LinkedIn operators) ────
def test_negative_query_uses_boolean_not():
    q = _build_negative_query("looking for marketing agency", ['"i offer"', '"we offer"'])
    assert q.startswith('"looking for marketing agency"')
    assert " NOT " in q
    assert '"i offer"' in q and '"we offer"' in q


def test_negative_query_respects_500_char_limit():
    long_intent = "looking for " + ("agency " * 60)
    q = _build_negative_query(long_intent, ['"i offer"'] * 10)
    assert q is None or len(q) <= 500


def test_negative_query_caps_operators():
    # Only up to 4 NOT terms — stays within LinkedIn's 5-operator limit.
    q = _build_negative_query("need a seo agency", ['"a"', '"b"', '"c"', '"d"', '"e"', '"f"'])
    assert q.count(" NOT ") <= 4


def test_add_negative_signal_queries_returns_variants():
    qs = add_negative_signal_queries(["looking for marketing agency"], max_per_intent=2)
    assert len(qs) >= 1
    assert all(" NOT " in q for q in qs)
