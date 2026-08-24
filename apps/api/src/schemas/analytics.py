"""Payment & Revenue Analytics response shapes (docs/research/payment-
analytics-dashboard.md §4.2).

Money is always `list[MoneyByCurrency]`, never a bare number — this
platform sells in more than one currency (ZAR and USD) and a figure summed
across currencies would be a fabrication (§3.3). Every list is per-currency
and the frontend renders one series per currency present, not a blend.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

PRESETS = ("last_24h", "last_7d", "last_30d", "last_3m", "last_6m", "last_1y")


class MoneyByCurrency(BaseModel):
    currency: str
    amount: Decimal


class PeriodResponse(BaseModel):
    """The server-resolved window `[from, to)` every figure below was
    computed over — echoed back so the report can state exactly what it
    covers rather than the client re-deriving it."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    preset: str | None
    from_: datetime = Field(alias="from")
    to: datetime


class PaidVsWaitingResponse(BaseModel):
    """Buyers in the period, bucketed by their most recent order's status:
    `fulfilled` -> paid; any pending/awaiting state -> awaiting_payment;
    rejected/cancelled/refunded -> did_not_convert (kept as a third bucket
    rather than folded into either side — §12.5)."""

    paid: int
    awaiting_payment: int
    did_not_convert: int
    total_users: int


class ProviderBreakdownRow(BaseModel):
    provider: str  # "card" | "eft" | "po"
    payment_count: int
    amount: list[MoneyByCurrency]


class PredictedRevenueResponse(BaseModel):
    """Two labelled components plus their sum. `pipeline` is orders still
    awaiting payment/approval (not risk-weighted — there is no stored
    conversion-rate to weight by); `subscription_renewals` is plan list
    price for every active, non-cancelling subscription whose current
    period ends inside the window — a forecast of expected billing, not
    a guarantee (renewals still go through manual EFT/PO approval)."""

    pipeline: list[MoneyByCurrency]
    pipeline_order_count: int
    subscription_renewals: list[MoneyByCurrency]
    subscription_renewal_count: int
    total: list[MoneyByCurrency]


class RevenueSummaryResponse(BaseModel):
    period: PeriodResponse
    paid_vs_waiting: PaidVsWaitingResponse
    payment_methods: list[ProviderBreakdownRow]
    # Net cash collected: payments received minus refunds issued, from the
    # append-only ledger (§3.1). The two components are also exposed so the
    # dashboard can show the gross and the refund line, not just the net.
    actual_revenue: list[MoneyByCurrency]
    payments_received: list[MoneyByCurrency]
    refunds_issued: list[MoneyByCurrency]
    predicted_revenue: PredictedRevenueResponse


class RevenuePoint(BaseModel):
    """One bucket of the revenue series. `amounts` is per currency for the
    same reason every other money field is: currencies are never blended,
    so a bucket carries one figure per currency present, not a total."""

    bucket: datetime
    label: str
    amounts: list[MoneyByCurrency]


class RevenueSeriesResponse(BaseModel):
    """Net revenue over time — the one thing the dashboard could not show,
    because every other figure it serves is a single aggregate for the
    whole period.

    Granularity is chosen server-side from the window's length, not by the
    client: a year bucketed by day is 365 unreadable points, and a day
    bucketed by month is one. The client renders what it is given.
    """

    period: PeriodResponse
    granularity: str
    currencies: list[str]
    points: list[RevenuePoint]


class PackageRow(BaseModel):
    package_label: str
    user_count: int


class OrganisationRow(BaseModel):
    organisation_id: str | None
    organisation_name: str
    user_count: int


class RegistrationsResponse(BaseModel):
    period: PeriodResponse
    total_registered: int
    by_package: list[PackageRow]
    by_organisation: list[OrganisationRow]


class TopCtaEpisode(BaseModel):
    episode_id: str
    title: str
    course_clicks: int


class PodcastEngagementResponse(BaseModel):
    """R2 (docs/BACKLOG.md; docs/research/podcast-platform-integration.md
    §6's explicit hand-off note) — the six `podcast.*` event names
    `routers/podcasts.py::log_podcast_event` already writes into the
    shared `events` table, aggregated. Raw counts only, no server-side
    rates: completion rate and click-through rate are `value/total`
    the same way every other share on this dashboard is — computed by
    the frontend's existing `ShareRow`, not duplicated here."""

    period: PeriodResponse
    episode_views: int
    plays_started: int
    plays_completed: int
    embed_click_throughs: int
    cta_clicks: int
    top_cta_episodes: list[TopCtaEpisode]


__all__ = [
    "PRESETS",
    "MoneyByCurrency",
    "OrganisationRow",
    "PackageRow",
    "PaidVsWaitingResponse",
    "PeriodResponse",
    "PodcastEngagementResponse",
    "PredictedRevenueResponse",
    "ProviderBreakdownRow",
    "RegistrationsResponse",
    "RevenueSummaryResponse",
    "TopCtaEpisode",
]
