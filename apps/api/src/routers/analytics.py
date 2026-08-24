"""Payment & Revenue Analytics (docs/research/payment-analytics-dashboard.md
§4.3) — four read-only, tenant-scoped, `analytics:view`-gated GETs.

Two JSON reports and a CSV twin of each. The CSV is built server-side from
the *same* aggregation functions as the JSON route (stdlib `csv` — the
same module `routers/organisations.py` already uses for import), so the
export can never drift from what's on screen. No `Idempotency-Key`: that
middleware gates mutating commerce endpoints only, and nothing here
writes.

`analytics:view` (seeded in 0002 for admin/super_admin, extended to
finance in 0028) is the gate — a purpose-built read-only reporting
permission, deliberately distinct from `payment:approve` the same way
`refund:process` is kept distinct from it in `routers/orders.py`.

The timeframe (`preset` XOR `from`+`to`) is a shared dependency resolved
server-side into a concrete UTC window; the client never computes a
boundary the server trusts.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import PrincipalDep, SessionDep
from src.schemas.analytics import (
    PRESETS,
    MoneyByCurrency,
    PeriodResponse,
    PodcastEngagementResponse,
    RegistrationsResponse,
    RevenuePoint,
    RevenueSeriesResponse,
    RevenueSummaryResponse,
)
from src.services import analytics as analytics_service
from src.services.analytics import Period

router = APIRouter(prefix="/analytics", tags=["analytics"])

PERMISSION = "analytics:view"
_PRESET_HELP = "One of: " + ", ".join(PRESETS) + ". Mutually exclusive with from/to."


def get_period(
    preset: Annotated[str | None, Query(description=_PRESET_HELP)] = None,
    from_: Annotated[
        date | None, Query(alias="from", description="Custom range start (UTC day, inclusive)")
    ] = None,
    to: Annotated[date | None, Query(description="Custom range end (UTC day, inclusive)")] = None,
) -> Period:
    return analytics_service.resolve_period(preset, from_, to)


PeriodDep = Annotated[Period, Depends(get_period)]


def _period_response(period: Period) -> PeriodResponse:
    return PeriodResponse(preset=period.preset, from_=period.start, to=period.end)


async def _revenue_summary(
    session: AsyncSession, principal: PrincipalDep, period: Period
) -> RevenueSummaryResponse:
    tenant_id = principal.tenant_id
    net, received, refunded = await analytics_service.actual_revenue(
        session, tenant_id=tenant_id, period=period
    )
    return RevenueSummaryResponse(
        period=_period_response(period),
        paid_vs_waiting=await analytics_service.paid_vs_waiting(
            session, tenant_id=tenant_id, period=period
        ),
        payment_methods=await analytics_service.payment_method_breakdown(
            session, tenant_id=tenant_id, period=period
        ),
        actual_revenue=net,
        payments_received=received,
        refunds_issued=refunded,
        predicted_revenue=await analytics_service.predicted_revenue(
            session, tenant_id=tenant_id, period=period
        ),
    )


async def _registrations(
    session: AsyncSession, principal: PrincipalDep, period: Period
) -> RegistrationsResponse:
    tenant_id = principal.tenant_id
    return RegistrationsResponse(
        period=_period_response(period),
        total_registered=await analytics_service.total_registered(
            session, tenant_id=tenant_id, period=period
        ),
        by_package=await analytics_service.registrations_by_package(
            session, tenant_id=tenant_id, period=period
        ),
        by_organisation=await analytics_service.registrations_by_organisation(
            session, tenant_id=tenant_id, period=period
        ),
    )


@router.get(
    "/revenue-summary",
    response_model=RevenueSummaryResponse,
    summary="Paid vs waiting, payment methods, actual and predicted revenue for a period",
)
async def revenue_summary(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> RevenueSummaryResponse:
    principal.require(PERMISSION)
    return await _revenue_summary(session, principal, period)


@router.get(
    "/revenue-series",
    response_model=RevenueSeriesResponse,
    summary="Net revenue over time, bucketed server-side, one figure per currency",
)
async def revenue_series(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> RevenueSeriesResponse:
    principal.require(PERMISSION)
    granularity, currencies, points = await analytics_service.revenue_series(
        session, tenant_id=principal.tenant_id, period=period
    )
    return RevenueSeriesResponse(
        period=_period_response(period),
        granularity=granularity,
        currencies=currencies,
        points=[
            RevenuePoint(bucket=stamp, label=label, amounts=amounts)
            for stamp, label, amounts in points
        ],
    )


@router.get(
    "/registrations",
    response_model=RegistrationsResponse,
    summary="Registrations in a period, by package and by organisation",
)
async def registrations(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> RegistrationsResponse:
    principal.require(PERMISSION)
    return await _registrations(session, principal, period)


@router.get(
    "/podcast-engagement",
    response_model=PodcastEngagementResponse,
    summary="Plays, completion rate, click-through rate and top CTA-converting episodes",
)
async def podcast_engagement(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> PodcastEngagementResponse:
    principal.require(PERMISSION)
    tenant_id = principal.tenant_id
    counts = await analytics_service.podcast_event_counts(
        session, tenant_id=tenant_id, period=period
    )
    top = await analytics_service.top_cta_episodes(session, tenant_id=tenant_id, period=period)
    return PodcastEngagementResponse(
        period=_period_response(period),
        episode_views=counts.episode_views,
        plays_started=counts.plays_started,
        plays_completed=counts.plays_completed,
        embed_click_throughs=counts.embed_click_throughs,
        cta_clicks=counts.cta_clicks,
        top_cta_episodes=top,
    )


# ---- CSV export --------------------------------------------------------------
#
# One long-format table per report: section,label,currency,count,amount.
# Long rather than wide because the number of currencies is data, not
# schema — a wide layout would need a column per currency and change
# shape between tenants.

CSV_HEADER = ("section", "label", "currency", "count", "amount")


def _csv_response(rows: list[tuple[object, ...]], filename: str) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    writer.writerows(rows)
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _period_rows(period: PeriodResponse) -> list[tuple[object, ...]]:
    return [
        ("period", "preset", "", "", period.preset or "custom"),
        ("period", "from", "", "", period.from_.isoformat()),
        ("period", "to", "", "", period.to.isoformat()),
    ]


def _money_rows(
    section: str, label: str, money: list[MoneyByCurrency], count: int | str = ""
) -> list[tuple[object, ...]]:
    if not money:
        return [(section, label, "", count, "0")]
    return [(section, label, m.currency, count, str(m.amount)) for m in money]


@router.get(
    "/revenue-summary/export.csv",
    summary="CSV of the revenue summary, same rows as the JSON report",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def revenue_summary_csv(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> Response:
    principal.require(PERMISSION)
    data = await _revenue_summary(session, principal, period)
    pvw = data.paid_vs_waiting
    rows: list[tuple[object, ...]] = _period_rows(data.period)
    rows += [
        ("paid_vs_waiting", "paid", "", pvw.paid, ""),
        ("paid_vs_waiting", "awaiting_payment", "", pvw.awaiting_payment, ""),
        ("paid_vs_waiting", "did_not_convert", "", pvw.did_not_convert, ""),
        ("paid_vs_waiting", "total_users", "", pvw.total_users, ""),
    ]
    for method in data.payment_methods:
        rows += _money_rows("payment_methods", method.provider, method.amount, method.payment_count)
    rows += _money_rows("actual_revenue", "net", data.actual_revenue)
    rows += _money_rows("actual_revenue", "payments_received", data.payments_received)
    rows += _money_rows("actual_revenue", "refunds_issued", data.refunds_issued)
    predicted = data.predicted_revenue
    rows += _money_rows(
        "predicted_revenue", "pipeline", predicted.pipeline, predicted.pipeline_order_count
    )
    rows += _money_rows(
        "predicted_revenue",
        "subscription_renewals",
        predicted.subscription_renewals,
        predicted.subscription_renewal_count,
    )
    rows += _money_rows("predicted_revenue", "total", predicted.total)
    return _csv_response(rows, "revenue-summary.csv")


@router.get(
    "/registrations/export.csv",
    summary="CSV of the registrations report, same rows as the JSON report",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def registrations_csv(
    principal: PrincipalDep, session: SessionDep, period: PeriodDep
) -> Response:
    principal.require(PERMISSION)
    data = await _registrations(session, principal, period)
    rows: list[tuple[object, ...]] = _period_rows(data.period)
    rows.append(("registrations", "total_registered", "", data.total_registered, ""))
    rows += [("by_package", row.package_label, "", row.user_count, "") for row in data.by_package]
    rows += [
        ("by_organisation", row.organisation_name, "", row.user_count, "")
        for row in data.by_organisation
    ]
    return _csv_response(rows, "registrations.csv")


__all__ = ["router"]
