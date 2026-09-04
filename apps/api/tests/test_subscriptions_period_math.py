"""Pure-function tests for `services/subscriptions.py::compute_renewal_period`
(extracted from `fulfil_subscription_order`'s transaction per
TTLI_Audit_Report_2026-09-02.md M5) — no Postgres, no Redis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.services.subscriptions import GRACE_DAYS, compute_renewal_period

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def test_first_period_starts_now_when_no_prior_period_exists():
    start, end, expires = compute_renewal_period(None, NOW, billing_interval_days=30)
    assert start == NOW
    assert end == NOW + timedelta(days=30)
    assert expires == end + timedelta(days=GRACE_DAYS)


def test_renewal_before_period_end_starts_from_the_existing_period_end():
    # Renewing early must not shorten the paid-for period -- the new
    # period starts where the old one ends, not from "now".
    current_end = NOW + timedelta(days=10)
    start, end, _expires = compute_renewal_period(current_end, NOW, billing_interval_days=30)
    assert start == current_end
    assert end == current_end + timedelta(days=30)


def test_renewal_after_period_end_starts_from_now_not_the_stale_end():
    # A lapsed subscription renewing late must not backdate the new
    # period into the past.
    stale_end = NOW - timedelta(days=5)
    start, end, _expires = compute_renewal_period(stale_end, NOW, billing_interval_days=30)
    assert start == NOW
    assert end == NOW + timedelta(days=30)


def test_access_always_outlives_the_billing_period_by_grace_days():
    _start, end, expires = compute_renewal_period(None, NOW, billing_interval_days=7)
    assert expires == end + timedelta(days=GRACE_DAYS)
    assert expires > end
