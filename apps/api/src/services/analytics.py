"""Payment & Revenue Analytics — read-only, tenant-scoped aggregation
(docs/research/payment-analytics-dashboard.md §3, §4.1).

Every function takes an explicit `tenant_id` and filters on it, on top of
the RLS the session already carries — the same belt-and-braces every other
admin read in `services/orders.py` uses. Nothing here writes.

Definitions, resolved (§3):

* **Actual revenue** = net cash collected in the period, from the
  append-only ledger: `payment_received` minus `refund_issued`, per
  currency. The ledger, not `orders.grand_total`, because it is the
  audit-authoritative record of money actually moving, and refunds net
  out without a second join.
* **Predicted revenue** = pipeline (orders created in the period still in
  a pending/awaiting state, at their grand total — deliberately not
  risk-weighted, there is no stored conversion rate to weight by) plus
  subscription renewals (plan list price for every active, non-cancelling
  subscription whose `current_period_end` falls in the window).
* Money is per-currency everywhere; nothing is summed across currencies.

`orders.status = 'paid'` exists in the enum but no code path ever sets it
(`services/orders.py::_fulfil_order` goes straight to `'fulfilled'`); the
buckets below treat it as paid for completeness but never rely on it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, case, exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError
from src.models.commerce import Entitlement, LedgerEntry, Order, Payment, Price
from src.models.event import Event
from src.models.organisation import Organisation, OrganisationMember
from src.models.podcast import PodcastEpisode
from src.models.subscription import Subscription, SubscriptionPlan
from src.models.user import User
from src.schemas.analytics import (
    PRESETS,
    MoneyByCurrency,
    OrganisationRow,
    PackageRow,
    PaidVsWaitingResponse,
    PredictedRevenueResponse,
    ProviderBreakdownRow,
    TopCtaEpisode,
    TopPagePath,
)
from src.services.events import EventName
from src.services.ledger import EntryType
from src.services.podcasts import PodcastEventName

PAID_STATUSES = ("fulfilled", "paid")
AWAITING_STATUSES = (
    "draft",
    "pending_payment",
    "eft_pending_proof",
    "eft_pending_approval",
    "po_pending_approval",
)
DID_NOT_CONVERT_STATUSES = ("eft_rejected", "cancelled", "refunded")
# The pipeline is narrower than "awaiting": a `draft` order was never
# checked out (no payment method chosen), so it isn't money anyone has
# committed to yet and would inflate the forecast.
PIPELINE_STATUSES = (
    "pending_payment",
    "eft_pending_proof",
    "eft_pending_approval",
    "po_pending_approval",
)

# Beyond this many organisations the tail folds into one "Other" row —
# a chart with hundreds of one-user bars says nothing (dataviz: fold the
# tail rather than draw more marks); the CSV export carries the same rows.
ORGANISATION_ROW_CAP = 20

# A leaderboard, not a full report — same "fold the tail" reasoning as
# ORGANISATION_ROW_CAP, just with no "Other" row since the ask (docs/
# BACKLOG.md R2) is specifically the *top* CTA-converting episodes.
TOP_CTA_EPISODE_LIMIT = 5
# Same "top N, not every path" reasoning for site traffic.
TOP_PATH_LIMIT = 10

PACKAGE_ONE_TIME = "One-time purchase"
PACKAGE_GUEST = "Guest access"
PACKAGE_NONE = "No purchase"
ORGANISATION_NONE = "Individual (no organisation)"

_PRESET_DELTAS: dict[str, timedelta] = {
    "last_24h": timedelta(hours=24),
    "last_7d": timedelta(days=7),
    "last_30d": timedelta(days=30),
    "last_3m": timedelta(days=91),
    "last_6m": timedelta(days=182),
    "last_1y": timedelta(days=365),
}
DEFAULT_PRESET = "last_30d"


@dataclass(frozen=True, slots=True)
class Period:
    """A half-open UTC window `[start, end)`."""

    preset: str | None
    start: datetime
    end: datetime


def resolve_period(
    preset: str | None,
    from_date: date | None,
    to_date: date | None,
    *,
    now: datetime | None = None,
) -> Period:
    """Server-side resolution of the timeframe (§6) — a preset anchors to
    `now()` at request time; a custom range expands its two dates to a
    full-day UTC window `[from 00:00:00, to + 1 day 00:00:00)`, so `to` is
    inclusive of that whole day. Exactly one of the two forms may be
    supplied; with neither, `last_30d` is the default. Refusals are
    `AppError` (400), matching every other endpoint's validation style."""
    has_custom = from_date is not None or to_date is not None
    if preset is not None and has_custom:
        raise AppError("Supply either a preset or a from/to range, not both.")
    if has_custom:
        if from_date is None or to_date is None:
            raise AppError("A custom range needs both from and to dates.")
        if from_date > to_date:
            raise AppError("The from date must not be after the to date.")
        start = datetime.combine(from_date, time.min, tzinfo=UTC)
        end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        return Period(preset=None, start=start, end=end)

    chosen = preset or DEFAULT_PRESET
    if chosen not in PRESETS:
        raise AppError("Unknown preset.", {"preset": chosen, "allowed": list(PRESETS)})
    anchor = now or datetime.now(UTC)
    return Period(preset=chosen, start=anchor - _PRESET_DELTAS[chosen], end=anchor)


def _money(rows: list[tuple[str, Decimal | None]]) -> list[MoneyByCurrency]:
    out = [
        MoneyByCurrency(currency=currency, amount=Decimal(amount or 0)) for currency, amount in rows
    ]
    out.sort(key=lambda m: m.currency)
    return out


def _sum_by_currency(*parts: list[MoneyByCurrency]) -> list[MoneyByCurrency]:
    totals: dict[str, Decimal] = {}
    for part in parts:
        for m in part:
            totals[m.currency] = totals.get(m.currency, Decimal(0)) + m.amount
    return [MoneyByCurrency(currency=c, amount=a) for c, a in sorted(totals.items())]


async def paid_vs_waiting(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> PaidVsWaitingResponse:
    """One row per distinct buyer with an order created in the period,
    classified by that buyer's most recent order in the period."""
    rn = (
        func.row_number()
        .over(partition_by=Order.user_id, order_by=(Order.created_at.desc(), Order.id.desc()))
        .label("rn")
    )
    latest = (
        select(Order.user_id, Order.status, rn)
        .where(
            Order.tenant_id == tenant_id,
            Order.created_at >= period.start,
            Order.created_at < period.end,
        )
        .subquery("latest_order")
    )
    status_col = latest.c.status
    stmt = select(
        func.coalesce(func.sum(case((status_col.in_(PAID_STATUSES), 1), else_=0)), 0),
        func.coalesce(func.sum(case((status_col.in_(AWAITING_STATUSES), 1), else_=0)), 0),
        func.coalesce(func.sum(case((status_col.in_(DID_NOT_CONVERT_STATUSES), 1), else_=0)), 0),
        func.count(),
    ).where(latest.c.rn == 1)
    row = (await session.execute(stmt)).one()
    return PaidVsWaitingResponse(
        paid=int(row[0]),
        awaiting_payment=int(row[1]),
        did_not_convert=int(row[2]),
        total_users=int(row[3]),
    )


async def payment_method_breakdown(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> list[ProviderBreakdownRow]:
    """Cash received per provider (card / eft / po) — from the ledger's
    `payment_received` entries joined back to the payment they record, so
    a payment only counts once it actually funded a fulfilment."""
    stmt = (
        select(
            Payment.provider,
            LedgerEntry.currency,
            func.count(LedgerEntry.id),
            func.coalesce(func.sum(LedgerEntry.amount), 0),
        )
        .join(
            Payment,
            and_(Payment.id == LedgerEntry.entity_id, Payment.tenant_id == LedgerEntry.tenant_id),
        )
        .where(
            LedgerEntry.tenant_id == tenant_id,
            LedgerEntry.entity_type == "payment",
            LedgerEntry.entry_type == EntryType.PAYMENT_RECEIVED,
            LedgerEntry.created_at >= period.start,
            LedgerEntry.created_at < period.end,
        )
        .group_by(Payment.provider, LedgerEntry.currency)
        .order_by(Payment.provider, LedgerEntry.currency)
    )
    grouped: dict[str, tuple[int, list[tuple[str, Decimal | None]]]] = {}
    for provider, currency, count, amount in (await session.execute(stmt)).all():
        total, amounts = grouped.get(provider, (0, []))
        amounts.append((currency, amount))
        grouped[provider] = (total + int(count), amounts)
    return [
        ProviderBreakdownRow(provider=provider, payment_count=count, amount=_money(amounts))
        for provider, (count, amounts) in sorted(grouped.items())
    ]


async def actual_revenue(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> tuple[list[MoneyByCurrency], list[MoneyByCurrency], list[MoneyByCurrency]]:
    """Returns `(net, payments_received, refunds_issued)`, each per
    currency, from the ledger over the period (§3.1)."""
    stmt = (
        select(
            LedgerEntry.currency,
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == EntryType.PAYMENT_RECEIVED, LedgerEntry.amount),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.entry_type == EntryType.REFUND_ISSUED, LedgerEntry.amount),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .where(
            LedgerEntry.tenant_id == tenant_id,
            LedgerEntry.entry_type.in_((EntryType.PAYMENT_RECEIVED, EntryType.REFUND_ISSUED)),
            LedgerEntry.created_at >= period.start,
            LedgerEntry.created_at < period.end,
        )
        .group_by(LedgerEntry.currency)
    )
    received: list[tuple[str, Decimal | None]] = []
    refunded: list[tuple[str, Decimal | None]] = []
    net: list[tuple[str, Decimal | None]] = []
    for currency, paid, refunds in (await session.execute(stmt)).all():
        received.append((currency, paid))
        refunded.append((currency, refunds))
        net.append((currency, Decimal(paid) - Decimal(refunds)))
    return _money(net), _money(received), _money(refunded)


async def predicted_revenue(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> PredictedRevenueResponse:
    pipeline_stmt = (
        select(Order.currency, func.count(Order.id), func.coalesce(func.sum(Order.grand_total), 0))
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_(PIPELINE_STATUSES),
            Order.created_at >= period.start,
            Order.created_at < period.end,
        )
        .group_by(Order.currency)
    )
    pipeline_rows = (await session.execute(pipeline_stmt)).all()
    pipeline = _money([(currency, amount) for currency, _, amount in pipeline_rows])
    pipeline_count = sum(int(count) for _, count, _ in pipeline_rows)

    renewals_stmt = (
        select(
            Price.currency,
            func.count(Subscription.id),
            func.coalesce(func.sum(Price.unit_amount), 0),
        )
        .select_from(Subscription)
        .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
        .join(Price, Price.id == SubscriptionPlan.price_id)
        .where(
            Subscription.tenant_id == tenant_id,
            Subscription.status == "active",
            Subscription.cancel_at_period_end.is_(False),
            Subscription.current_period_end.is_not(None),
            Subscription.current_period_end >= period.start,
            Subscription.current_period_end < period.end,
        )
        .group_by(Price.currency)
    )
    renewal_rows = (await session.execute(renewals_stmt)).all()
    renewals = _money([(currency, amount) for currency, _, amount in renewal_rows])
    renewal_count = sum(int(count) for _, count, _ in renewal_rows)

    return PredictedRevenueResponse(
        pipeline=pipeline,
        pipeline_order_count=pipeline_count,
        subscription_renewals=renewals,
        subscription_renewal_count=renewal_count,
        total=_sum_by_currency(pipeline, renewals),
    )


def _users_in_period(tenant_id: uuid.UUID, period: Period) -> ColumnElement[bool]:
    return and_(
        User.tenant_id == tenant_id,
        User.created_at >= period.start,
        User.created_at < period.end,
    )


async def total_registered(session: AsyncSession, *, tenant_id: uuid.UUID, period: Period) -> int:
    stmt = select(func.count(User.id)).where(_users_in_period(tenant_id, period))
    return int((await session.execute(stmt)).scalar_one())


async def registrations_by_package(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> list[PackageRow]:
    """Users registered in the period, by their *current* package state
    (§12.3 — there is no temporal tier history to query instead): an
    active subscription's plan name; else "One-time purchase" if they hold
    a live entitlement from a fulfilled non-subscription order (a direct
    course purchase or an assigned organisation seat); else "Guest access"
    for free-lesson guests; else "No purchase"."""
    active_plan = (
        select(Subscription.user_id, SubscriptionPlan.name.label("plan_name"))
        .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
        .where(Subscription.tenant_id == tenant_id, Subscription.status == "active")
        .subquery("active_plan")
    )
    has_purchase = exists(
        select(literal(1))
        .select_from(Entitlement)
        .join(Order, Order.id == Entitlement.source_order_id)
        .where(
            Entitlement.tenant_id == tenant_id,
            Entitlement.user_id == User.id,
            Entitlement.revoked_at.is_(None),
            Order.status.in_(PAID_STATUSES),
            Order.subscription_id.is_(None),
        )
    )
    label = case(
        (active_plan.c.plan_name.is_not(None), active_plan.c.plan_name),
        (has_purchase, literal(PACKAGE_ONE_TIME)),
        (User.is_guest.is_(True), literal(PACKAGE_GUEST)),
        else_=literal(PACKAGE_NONE),
    ).label("package_label")
    stmt = (
        select(label, func.count(User.id))
        .select_from(User)
        .outerjoin(active_plan, active_plan.c.user_id == User.id)
        .where(_users_in_period(tenant_id, period))
        .group_by(label)
        .order_by(func.count(User.id).desc(), label)
    )
    return [
        PackageRow(package_label=str(row[0]), user_count=int(row[1]))
        for row in (await session.execute(stmt)).all()
    ]


async def registrations_by_organisation(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> list[OrganisationRow]:
    """Users registered in the period by the organisation they belong to;
    no membership -> "Individual (no organisation)". Sorted by count, the
    tail beyond `ORGANISATION_ROW_CAP` folded into one "Other" row."""
    stmt = (
        select(Organisation.id, Organisation.name, func.count(func.distinct(User.id)))
        .select_from(User)
        .outerjoin(
            OrganisationMember,
            and_(
                OrganisationMember.user_id == User.id,
                OrganisationMember.tenant_id == tenant_id,
            ),
        )
        .outerjoin(Organisation, Organisation.id == OrganisationMember.organisation_id)
        .where(_users_in_period(tenant_id, period))
        .group_by(Organisation.id, Organisation.name)
        .order_by(func.count(func.distinct(User.id)).desc(), Organisation.name)
    )
    rows = (await session.execute(stmt)).all()
    out: list[OrganisationRow] = []
    individual: OrganisationRow | None = None
    for org_id, name, count in rows:
        if org_id is None:
            individual = OrganisationRow(
                organisation_id=None, organisation_name=ORGANISATION_NONE, user_count=int(count)
            )
            continue
        out.append(
            OrganisationRow(
                organisation_id=str(org_id), organisation_name=str(name), user_count=int(count)
            )
        )
    if len(out) > ORGANISATION_ROW_CAP:
        head, tail = out[:ORGANISATION_ROW_CAP], out[ORGANISATION_ROW_CAP:]
        out = [
            *head,
            OrganisationRow(
                organisation_id=None,
                organisation_name=f"Other organisations ({len(tail)})",
                user_count=sum(r.user_count for r in tail),
            ),
        ]
    if individual is not None:
        out.append(individual)
    return out


@dataclass(frozen=True, slots=True)
class PodcastEventCounts:
    episode_views: int
    plays_started: int
    plays_completed: int
    embed_click_throughs: int
    cta_clicks: int


_PODCAST_EVENT_NAMES = (
    PodcastEventName.EPISODE_VIEWED,
    PodcastEventName.PLAY_STARTED,
    PodcastEventName.PLAY_COMPLETED,
    PodcastEventName.EMBED_CLICK_THROUGH,
    PodcastEventName.CTA_COURSE_CLICKED,
)


async def podcast_event_counts(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> PodcastEventCounts:
    """R2 (docs/BACKLOG.md; docs/research/podcast-platform-integration.md
    §6's explicit hand-off note) — one `GROUP BY event_name` over the
    same `podcast.*` rows `routers/podcasts.py::log_podcast_event`
    writes into the shared, monthly-partitioned `events` table
    (`podcast.play.progress` is written but has no counter here — it's
    checkpoint telemetry for a future retention curve, not a headline
    figure). Raw counts only; rates are `value/total` on the frontend,
    the same as every other share on this dashboard."""
    stmt = (
        select(Event.event_name, func.count())
        .where(
            Event.tenant_id == tenant_id,
            Event.event_name.in_(_PODCAST_EVENT_NAMES),
            Event.created_at >= period.start,
            Event.created_at < period.end,
        )
        .group_by(Event.event_name)
    )
    counts = {name: int(count) for name, count in (await session.execute(stmt)).all()}
    return PodcastEventCounts(
        episode_views=counts.get(PodcastEventName.EPISODE_VIEWED, 0),
        plays_started=counts.get(PodcastEventName.PLAY_STARTED, 0),
        plays_completed=counts.get(PodcastEventName.PLAY_COMPLETED, 0),
        embed_click_throughs=counts.get(PodcastEventName.EMBED_CLICK_THROUGH, 0),
        cta_clicks=counts.get(PodcastEventName.CTA_COURSE_CLICKED, 0),
    )


async def top_cta_episodes(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> list[TopCtaEpisode]:
    """The episodes actually converting listeners toward a course
    purchase — `event_properties->>'episode_id'` grouped and ranked,
    the real signal REQ-STORE-04 exists to capture. An episode deleted
    since the click still shows (attributed to "(deleted episode)"),
    rather than silently dropping real conversions from the count."""
    # Built once and reused by reference (not re-written per clause): two
    # separately-constructed `event_properties["episode_id"].astext`
    # expressions bind their literal key as two different parameters,
    # so Postgres no longer sees SELECT/GROUP BY as the same expression
    # and refuses with a GroupingError.
    episode_id_col = Event.event_properties["episode_id"].astext.label("episode_id")
    stmt = (
        select(episode_id_col, func.count())
        .where(
            Event.tenant_id == tenant_id,
            Event.event_name == PodcastEventName.CTA_COURSE_CLICKED,
            Event.created_at >= period.start,
            Event.created_at < period.end,
        )
        .group_by(episode_id_col)
        .order_by(func.count().desc())
        .limit(TOP_CTA_EPISODE_LIMIT)
    )
    # A malformed episode_id (overall-review F7) is skipped, not a 500:
    # today only log_podcast_event writes this property and always a
    # real UUID, but the panel reading a hand-inserted or future-writer
    # row's junk value should degrade the leaderboard by one row, not
    # take the whole dashboard down.
    rows: list[tuple[str, int]] = []
    for eid, count in (await session.execute(stmt)).all():
        if not eid:
            continue
        try:
            uuid.UUID(eid)
        except ValueError:
            continue
        rows.append((eid, int(count)))
    if not rows:
        return []

    episode_ids = [uuid.UUID(eid) for eid, _ in rows]
    title_stmt = select(PodcastEpisode.id, PodcastEpisode.title).where(
        PodcastEpisode.id.in_(episode_ids)
    )
    titles = {row[0]: row[1] for row in (await session.execute(title_stmt)).all()}
    return [
        TopCtaEpisode(
            episode_id=eid,
            title=titles.get(uuid.UUID(eid), "(deleted episode)"),
            course_clicks=count,
        )
        for eid, count in rows
    ]


async def page_view_counts(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> tuple[int, list[TopPagePath]]:
    """Site-traffic pageviews on public marketing pages (checklist item
    20 follow-up; 01_PRD.md §5.11's first-party-analytics decision, kept
    deliberately instead of a third-party tracker). `page.viewed` is
    written by the client-side beacon in routers/events.py for public
    marketing routes only — admin/account/auth/checkout/learn never fire
    it (components/page-view-tracker.tsx), the same "what counts as the
    public site" boundary robots.ts already draws."""
    path_col = Event.event_properties["path"].astext.label("path")
    base_filters = (
        Event.tenant_id == tenant_id,
        Event.event_name == EventName.PAGE_VIEWED,
        Event.created_at >= period.start,
        Event.created_at < period.end,
    )
    total = int((await session.execute(select(func.count()).where(*base_filters))).scalar_one())
    top_stmt = (
        select(path_col, func.count())
        .where(*base_filters)
        .group_by(path_col)
        .order_by(func.count().desc())
        .limit(TOP_PATH_LIMIT)
    )
    top_paths = [
        TopPagePath(path=path, views=int(count))
        for path, count in (await session.execute(top_stmt)).all()
        if path
    ]
    return total, top_paths


__all__ = [
    "AWAITING_STATUSES",
    "DEFAULT_PRESET",
    "DID_NOT_CONVERT_STATUSES",
    "ORGANISATION_NONE",
    "ORGANISATION_ROW_CAP",
    "PACKAGE_GUEST",
    "PACKAGE_NONE",
    "PACKAGE_ONE_TIME",
    "PAID_STATUSES",
    "PIPELINE_STATUSES",
    "TOP_CTA_EPISODE_LIMIT",
    "TOP_PATH_LIMIT",
    "Period",
    "PodcastEventCounts",
    "actual_revenue",
    "page_view_counts",
    "paid_vs_waiting",
    "payment_method_breakdown",
    "podcast_event_counts",
    "predicted_revenue",
    "registrations_by_organisation",
    "registrations_by_package",
    "resolve_period",
    "top_cta_episodes",
    "total_registered",
]


# Granularity is a server decision, not a client one: a year bucketed by
# day is 365 points nobody can read, and a day bucketed by month is one.
# Thresholds are in days of window span.
_DAY_MAX = 45
_WEEK_MAX = 200


def choose_granularity(period: Period) -> str:
    span_days = (period.end - period.start).days
    if span_days <= _DAY_MAX:
        return "day"
    if span_days <= _WEEK_MAX:
        return "week"
    return "month"


def _bucket_label(bucket: datetime, granularity: str) -> str:
    if granularity == "month":
        return bucket.strftime("%b %Y")
    return bucket.strftime("%d %b")


async def revenue_series(
    session: AsyncSession, *, tenant_id: uuid.UUID, period: Period
) -> tuple[str, list[str], list[tuple[datetime, str, list[MoneyByCurrency]]]]:
    """Net revenue per time bucket, per currency, from the ledger.

    Same definition of "actual revenue" as `actual_revenue` — payments
    received minus refunds issued, read from the append-only ledger — so
    the series and the headline figure are the same number sliced two
    ways, and summing the series must reproduce the total.

    Buckets with no movement are emitted as zero rather than omitted: a
    gap in a revenue line reads as missing data, while a zero reads as a
    quiet week, and only one of those is true.
    """
    granularity = choose_granularity(period)
    bucket = func.date_trunc(granularity, LedgerEntry.created_at)

    rows = (
        await session.execute(
            select(
                bucket.label("bucket"),
                LedgerEntry.currency,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                LedgerEntry.entry_type == EntryType.PAYMENT_RECEIVED,
                                LedgerEntry.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                )
                - func.coalesce(
                    func.sum(
                        case(
                            (LedgerEntry.entry_type == EntryType.REFUND_ISSUED, LedgerEntry.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .where(
                LedgerEntry.tenant_id == tenant_id,
                LedgerEntry.entry_type.in_((EntryType.PAYMENT_RECEIVED, EntryType.REFUND_ISSUED)),
                LedgerEntry.created_at >= period.start,
                LedgerEntry.created_at < period.end,
            )
            .group_by(bucket, LedgerEntry.currency)
            .order_by(bucket)
        )
    ).all()

    by_bucket: dict[datetime, dict[str, Decimal]] = {}
    currencies: list[str] = []
    for stamp, currency, net in rows:
        if currency not in currencies:
            currencies.append(currency)
        by_bucket.setdefault(stamp, {})[currency] = Decimal(net)

    currencies.sort()
    points = [
        (
            stamp,
            _bucket_label(stamp, granularity),
            [
                MoneyByCurrency(currency=c, amount=by_bucket[stamp].get(c, Decimal("0.00")))
                for c in currencies
            ],
        )
        for stamp in sorted(by_bucket)
    ]
    return granularity, currencies, points
