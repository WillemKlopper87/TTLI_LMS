"""Pure-function tests for `services/orders.py::price_order_lines`
(extracted from `create_order`'s resolve-and-validate loop per
TTLI_Audit_Report_2026-09-02.md M5) — no Postgres, no Redis.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.services.orders import ResolvedLine, price_order_lines

pytestmark = pytest.mark.unit


def test_single_exclusive_line_adds_tax_on_top():
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("100.00"),
                quantity=1,
                tax_rate=Decimal("0.15"),
                tax_behaviour="exclusive",
            )
        ]
    )
    line = pricing.lines[0]
    assert line.subtotal == Decimal("100.00")
    assert line.tax == Decimal("15.00")
    assert line.total == Decimal("115.00")
    assert pricing.subtotal == Decimal("100.00")
    assert pricing.tax_total == Decimal("15.00")
    assert pricing.grand_total == Decimal("115.00")


def test_single_inclusive_line_total_excludes_tax_from_the_displayed_total():
    # tax_behaviour="inclusive" means unit_amount is the advertised,
    # all-in price -- R115 at 15% VAT means R15.00 of that R115 is tax
    # (extracted: 115 * 0.15 / 1.15), not a further 15% added on top of
    # it (which would wrongly charge R132.25 for a R115 sticker price --
    # fable5.1_review.md H-1). line_total stays at the advertised gross;
    # subtotal is the net amount tax was extracted from.
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("115.00"),
                quantity=1,
                tax_rate=Decimal("0.15"),
                tax_behaviour="inclusive",
            )
        ]
    )
    line = pricing.lines[0]
    assert line.subtotal == Decimal("100.00")
    assert line.tax == Decimal("15.00")
    assert line.total == Decimal("115.00")
    assert pricing.subtotal == Decimal("100.00")
    assert pricing.tax_total == Decimal("15.00")
    assert pricing.grand_total == Decimal("115.00")


def test_inclusive_grand_total_never_exceeds_the_advertised_price():
    # The buyer must never be charged more than the sticker price they
    # were shown -- the exact regression H-1 describes: grand_total was
    # unconditionally subtotal + tax_total, and for an inclusive line
    # tax_total was computed as if the price were exclusive, adding a
    # second helping of VAT on top of the advertised total.
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("115.00"),
                quantity=1,
                tax_rate=Decimal("0.15"),
                tax_behaviour="inclusive",
            )
        ]
    )
    assert pricing.grand_total == Decimal("115.00")


def test_inclusive_quantity_multiplies_before_tax_extraction():
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("115.00"),
                quantity=2,
                tax_rate=Decimal("0.15"),
                tax_behaviour="inclusive",
            )
        ]
    )
    line = pricing.lines[0]
    assert line.subtotal == Decimal("200.00")
    assert line.tax == Decimal("30.00")
    assert line.total == Decimal("230.00")
    assert pricing.grand_total == Decimal("230.00")


def test_quantity_multiplies_before_tax():
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("50.00"),
                quantity=3,
                tax_rate=Decimal("0.15"),
                tax_behaviour="exclusive",
            )
        ]
    )
    line = pricing.lines[0]
    assert line.subtotal == Decimal("150.00")
    assert line.tax == Decimal("22.50")
    assert line.total == Decimal("172.50")


def test_multiple_lines_aggregate_correctly_and_preserve_order():
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("100.00"),
                quantity=1,
                tax_rate=Decimal("0.15"),
                tax_behaviour="exclusive",
            ),
            ResolvedLine(
                unit_amount=Decimal("50.00"),
                quantity=2,
                tax_rate=Decimal("0.00"),
                tax_behaviour="exclusive",
            ),
        ]
    )
    assert len(pricing.lines) == 2
    assert pricing.lines[0].subtotal == Decimal("100.00")
    assert pricing.lines[1].subtotal == Decimal("100.00")
    assert pricing.subtotal == Decimal("200.00")
    assert pricing.tax_total == Decimal("15.00")
    assert pricing.grand_total == Decimal("215.00")


def test_zero_tax_rate_is_a_real_zero_not_untaxed_total_change():
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("100.00"),
                quantity=1,
                tax_rate=Decimal("0"),
                tax_behaviour="exclusive",
            )
        ]
    )
    assert pricing.lines[0].tax == Decimal("0.00")
    assert pricing.lines[0].total == Decimal("100.00")


def test_empty_lines_produce_zero_totals():
    pricing = price_order_lines([])
    assert pricing.lines == ()
    assert pricing.subtotal == Decimal("0")
    assert pricing.tax_total == Decimal("0")
    assert pricing.grand_total == Decimal("0")


def test_rounding_uses_half_up_per_line_not_on_the_aggregate():
    # 33.335 * 3 lines of odd amounts -- confirms quantisation happens per
    # line (matching _quantize's ROUND_HALF_UP), not once at the end,
    # which would silently change the invoiced total by a cent in edge cases.
    pricing = price_order_lines(
        [
            ResolvedLine(
                unit_amount=Decimal("10.005"),
                quantity=1,
                tax_rate=Decimal("0"),
                tax_behaviour="exclusive",
            ),
            ResolvedLine(
                unit_amount=Decimal("10.005"),
                quantity=1,
                tax_rate=Decimal("0"),
                tax_behaviour="exclusive",
            ),
        ]
    )
    assert pricing.lines[0].subtotal == Decimal("10.01")  # half-up from 10.005
    assert pricing.lines[1].subtotal == Decimal("10.01")
    assert pricing.subtotal == Decimal("20.02")
