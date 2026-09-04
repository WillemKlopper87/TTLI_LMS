"""Multi-tier subscriptions (02 §6, REQ-PAY-12).

This module never imports `services/orders.py` — `orders.py::_fulfil_order`
calls `fulfil_subscription_order` (below) for every subscription-kind
product it fulfils, and the reverse direction (this module creating an
`Order` itself) would make the two modules mutually dependent. Instead,
`prepare_subscribe`/`prepare_change_plan`/`prepare_renewal` validate state
and return the `Price` to buy; `routers/subscriptions.py` is what actually
calls `orders_service.create_order`, the same "router orchestrates two
services" shape `routers/orders.py::create_order` already uses for
`organisations_service` + `orders_service`.

Renewals are funded through the existing EFT/PO manual-approval checkout
flow, not automatic card charging (0021's migration docstring) — a
subscription period only truly starts once its `Order` is fulfilled, which
is where `fulfil_subscription_order` does the real work: extend the
period, grant a fresh `expires_at`-bound `Entitlement` per bundled course.

Anti-abuse: `Subscription.last_plan_change_at` plus a cooldown equal to the
*current* plan's `billing_interval_days`, checked on every call that would
change `plan_id` (upgrade, queue-a-downgrade, reactivate-after-cancel).
Renewing the same plan is never cooldown-gated — no plan_id is changing.

`GRACE_DAYS` is baked directly into the `Entitlement.expires_at` granted on
fulfilment (`current_period_end + GRACE_DAYS`), not applied later at sweep
time — access is gated by a plain, live `expires_at > now()` check
(`services/entitlements.py::has_valid_course_entitlement`), so it lapses
honestly the moment grace genuinely runs out, never dependent on the daily
`revoke_lapsed_subscriptions` cron having already run. `Subscription.
current_period_end` itself stays the pure billing boundary with no grace
baked in — it is what a "renew before this date" prompt should read, not
the access deadline. The migration's SQL function must keep its own
`grace_days` default (3) in sync with this constant; it re-derives the same
cutoff independently since it compares against `current_period_end`
(ungraced) to decide when to flip `Subscription.status`, not `expires_at`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.errors import AppError, NotFound
from src.core.ids import uuid7
from src.models.commerce import Order, Price, Product
from src.models.course import Course
from src.models.subscription import Subscription, SubscriptionPlan, SubscriptionPlanCourse
from src.services import enrolment as enrolment_service
from src.services import entitlements

GRACE_DAYS = 3


def compute_renewal_period(
    current_period_end: datetime | None, now: datetime, billing_interval_days: int
) -> tuple[datetime, datetime, datetime]:
    """Pure period math extracted out of `fulfil_subscription_order`'s
    transaction (TTLI_Audit_Report_2026-09-02.md M5) — the transaction
    itself, and every DB read/write around this calculation, stays exactly
    where it was; only the arithmetic moved, so it can be unit-tested
    without a session. Returns (period_start, period_end, access_expires_at).
    The entitlement outlives the billing period by GRACE_DAYS — access is
    gated by a live `expires_at > now()` check (entitlements.py), so the
    grace has to live here, not just in the sweep (module docstring)."""
    period_start = max(now, current_period_end or now)
    period_end = period_start + timedelta(days=billing_interval_days)
    access_expires_at = period_end + timedelta(days=GRACE_DAYS)
    return period_start, period_end, access_expires_at


class SubscriptionError(AppError):
    """A refusal in the subscription flow — an active subscription already
    exists, a plan change is still in cooldown, or a plan doesn't belong
    to this tenant."""

    code = "SUBSCRIPTION_ERROR"


async def create_plan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    name: str,
    description: str | None,
    currency: str,
    unit_amount: str,
    tax_behaviour: str,
    billing_interval_days: int,
) -> SubscriptionPlan:
    product = Product(
        id=uuid7(),
        tenant_id=tenant_id,
        slug=f"subscription-{slug}",
        name=name,
        description=description,
        kind="subscription",
    )
    session.add(product)
    await session.flush()

    price = Price(
        id=uuid7(),
        tenant_id=tenant_id,
        product_id=product.id,
        currency=currency,
        unit_amount=unit_amount,
        tax_behaviour=tax_behaviour,
    )
    session.add(price)
    await session.flush()

    plan = SubscriptionPlan(
        id=uuid7(),
        tenant_id=tenant_id,
        slug=slug,
        name=name,
        description=description,
        product_id=product.id,
        price_id=price.id,
        billing_interval_days=billing_interval_days,
    )
    session.add(plan)
    await session.flush()

    product.subscription_plan_id = plan.id
    await session.flush()
    return plan


async def get_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID
) -> SubscriptionPlan:
    plan = await session.get(SubscriptionPlan, plan_id)
    if plan is None or plan.tenant_id != tenant_id:
        raise NotFound("No such subscription plan.")
    return plan


async def list_plans(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[SubscriptionPlan]:
    stmt = (
        select(SubscriptionPlan)
        .where(SubscriptionPlan.tenant_id == tenant_id)
        .order_by(SubscriptionPlan.name)
    )
    return list((await session.execute(stmt)).scalars().all())


async def update_plan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> SubscriptionPlan:
    """`price_id` is deliberately not editable here — Price rows are never
    mutated in this codebase (services/orders.py resolves prices server-
    side); a plan's price changes by creating a new plan, not by editing
    this one's price_id underneath subscribers already on it."""
    plan = await get_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    if name is not None:
        plan.name = name
    if description is not None:
        plan.description = description
    if is_active is not None:
        plan.is_active = is_active
    await session.flush()
    return plan


async def add_course_to_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID, course_id: uuid.UUID
) -> SubscriptionPlanCourse:
    await get_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    if await session.get(Course, course_id) is None:
        raise NotFound("No such course.")
    existing = (
        await session.execute(
            select(SubscriptionPlanCourse).where(
                SubscriptionPlanCourse.plan_id == plan_id,
                SubscriptionPlanCourse.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = SubscriptionPlanCourse(
        id=uuid7(), tenant_id=tenant_id, plan_id=plan_id, course_id=course_id
    )
    session.add(row)
    await session.flush()
    return row


async def remove_course_from_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID, course_id: uuid.UUID
) -> None:
    await get_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    row = (
        await session.execute(
            select(SubscriptionPlanCourse).where(
                SubscriptionPlanCourse.plan_id == plan_id,
                SubscriptionPlanCourse.course_id == course_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.flush()


async def list_plan_courses(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID
) -> list[Course]:
    await get_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    stmt = (
        select(Course)
        .join(SubscriptionPlanCourse, SubscriptionPlanCourse.course_id == Course.id)
        .where(SubscriptionPlanCourse.plan_id == plan_id)
        .order_by(Course.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_own_subscription(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Subscription | None:
    stmt = select(Subscription).where(
        Subscription.tenant_id == tenant_id, Subscription.user_id == user_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _cooldown_remaining(subscription: Subscription, plan: SubscriptionPlan) -> timedelta | None:
    if subscription.last_plan_change_at is None:
        return None
    unlocks_at = subscription.last_plan_change_at + timedelta(days=plan.billing_interval_days)
    now = datetime.now(UTC)
    return unlocks_at - now if now < unlocks_at else None


async def prepare_subscribe(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, plan_id: uuid.UUID
) -> tuple[Subscription, SubscriptionPlan]:
    """Validates and updates subscription state; does not create the
    `Order` itself (see module docstring). Caller must still call
    `orders_service.create_order(..., subscription_id=subscription.id)`
    with the returned plan's `price_id`."""
    plan = await get_plan(session, tenant_id=tenant_id, plan_id=plan_id)
    if not plan.is_active:
        raise SubscriptionError("This plan is not currently available.")

    subscription = await get_own_subscription(session, tenant_id=tenant_id, user_id=user_id)
    if subscription is not None and subscription.status != "cancelled":
        raise SubscriptionError(
            "You already have a subscription — use change-plan to switch, "
            "or renew to fund the next period."
        )

    if subscription is not None:
        # Reactivating a cancelled subscription is a plan change — cooldown
        # measured against the plan it's reactivating from.
        current_plan = await get_plan(session, tenant_id=tenant_id, plan_id=subscription.plan_id)
        remaining = _cooldown_remaining(subscription, current_plan)
        if remaining is not None:
            raise SubscriptionError(f"You can change plans again in {remaining.days + 1} day(s).")
        subscription.plan_id = plan_id
        subscription.pending_plan_id = None
        subscription.last_plan_change_at = datetime.now(UTC)
    else:
        # A brand-new subscription hasn't "changed" anything yet — the
        # cooldown clock must start on a real change (prepare_change_plan),
        # not on the first-ever plan choice, or nobody could switch plans
        # for a full billing interval after subscribing at all.
        subscription = Subscription(
            id=uuid7(), tenant_id=tenant_id, user_id=user_id, plan_id=plan_id, status="pending"
        )
        session.add(subscription)

    await session.flush()
    return subscription, plan


async def prepare_change_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, new_plan_id: uuid.UUID
) -> tuple[Subscription, SubscriptionPlan, bool]:
    """Returns (subscription, plan_to_buy, is_upgrade). For a downgrade,
    `plan_to_buy` is returned for display purposes only — the caller must
    NOT create an order for it; the switch is deferred to the next
    renewal (`prepare_renewal`), per 02 §6's "downgrade at next cycle"."""
    subscription = await get_own_subscription(session, tenant_id=tenant_id, user_id=user_id)
    if subscription is None or subscription.status == "cancelled":
        raise NotFound("No active subscription to change.")

    current_plan = await get_plan(session, tenant_id=tenant_id, plan_id=subscription.plan_id)
    new_plan = await get_plan(session, tenant_id=tenant_id, plan_id=new_plan_id)
    if not new_plan.is_active:
        raise SubscriptionError("This plan is not currently available.")

    remaining = _cooldown_remaining(subscription, current_plan)
    if remaining is not None:
        raise SubscriptionError(f"You can change plans again in {remaining.days + 1} day(s).")

    current_price = await session.get(Price, current_plan.price_id)
    new_price = await session.get(Price, new_plan.price_id)
    if current_price is None or new_price is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such price.")

    is_upgrade = new_price.unit_amount >= current_price.unit_amount
    subscription.last_plan_change_at = datetime.now(UTC)
    if is_upgrade:
        subscription.pending_plan_id = None
    else:
        subscription.pending_plan_id = new_plan_id
    await session.flush()
    return subscription, new_plan, is_upgrade


async def prepare_renewal(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Subscription, SubscriptionPlan]:
    """Same-plan (or previously-queued-downgrade) renewal — never cooldown-
    gated, since no plan_id changes at this call; `fulfil_subscription_order`
    is what actually applies a queued downgrade, once this order is paid."""
    subscription = await get_own_subscription(session, tenant_id=tenant_id, user_id=user_id)
    if subscription is None or subscription.status == "cancelled":
        raise NotFound("No active subscription to renew.")
    effective_plan_id = subscription.pending_plan_id or subscription.plan_id
    plan = await get_plan(session, tenant_id=tenant_id, plan_id=effective_plan_id)
    return subscription, plan


async def cancel(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Subscription:
    subscription = await get_own_subscription(session, tenant_id=tenant_id, user_id=user_id)
    if subscription is None:
        raise NotFound("No subscription to cancel.")
    subscription.cancel_at_period_end = True
    await session.flush()
    return subscription


async def resume(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> Subscription:
    subscription = await get_own_subscription(session, tenant_id=tenant_id, user_id=user_id)
    if subscription is None:
        raise NotFound("No subscription to resume.")
    subscription.cancel_at_period_end = False
    await session.flush()
    return subscription


async def fulfil_subscription_order(
    session: AsyncSession, *, tenant_id: uuid.UUID, order: Order, product: Product
) -> None:
    """Called from `orders.py::_fulfil_order` for every `kind="subscription"`
    product it fulfils. `product.subscription_plan_id` is the plan actually
    bought in *this* order — the authoritative answer to "which plan", not
    `Subscription.pending_plan_id` (that only decides what a bare *renewal*
    buys; an upgrade/downgrade order already names its own plan via the
    product it was created against)."""
    if order.subscription_id is None:  # pragma: no cover - only called for such orders
        raise SubscriptionError("Order is not a subscription order.")
    if (
        product.subscription_plan_id is None
    ):  # pragma: no cover - kind="subscription" guarantees this
        raise SubscriptionError("Subscription product has no linked plan.")

    subscription = await session.get(Subscription, order.subscription_id)
    if subscription is None:  # pragma: no cover - FK guarantees this
        raise NotFound("No such subscription.")
    plan = await get_plan(session, tenant_id=tenant_id, plan_id=product.subscription_plan_id)

    now = datetime.now(UTC)
    period_start, period_end, access_expires_at = compute_renewal_period(
        subscription.current_period_end, now, plan.billing_interval_days
    )

    for course in await list_plan_courses(session, tenant_id=tenant_id, plan_id=plan.id):
        entitlement = await entitlements.grant(
            session,
            tenant_id=tenant_id,
            user_id=order.user_id,
            source_order_id=order.id,
            kind="course",
            target_id=course.id,
            expires_at=access_expires_at,
        )
        await enrolment_service.get_or_create_enrolment(
            session,
            tenant_id=tenant_id,
            user_id=order.user_id,
            course_id=course.id,
            entitlement_id=entitlement.id,
        )

    subscription.plan_id = plan.id
    subscription.pending_plan_id = None
    subscription.status = "active"
    subscription.current_period_start = period_start
    subscription.current_period_end = period_end
    await session.flush()


__all__ = [
    "SubscriptionError",
    "add_course_to_plan",
    "cancel",
    "compute_renewal_period",
    "create_plan",
    "fulfil_subscription_order",
    "get_own_subscription",
    "get_plan",
    "list_plan_courses",
    "list_plans",
    "prepare_change_plan",
    "prepare_renewal",
    "prepare_subscribe",
    "remove_course_from_plan",
    "resume",
    "update_plan",
]
