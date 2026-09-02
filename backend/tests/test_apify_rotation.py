"""Tests for Apify key-rotation blacklist/cooldown logic.

Prove that a recoverable 403 (monthly usage hard limit exceeded) is NOT
permanently blacklisted, so a working key that momentarily hits its limit is
retried later instead of being removed from rotation forever.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.apify_service import _is_perm_feature_disabled  # noqa: E402


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
